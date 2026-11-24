import re
from datetime import datetime
from urllib.parse import urljoin

import httpx

from sources.types import RawNotice

LIST_URL = "https://financeonline.austintexas.gov/afo/account_services/solicitation/solicitations.cfm"
UA = "VendorAccessClub/1.0 (+https://vac2008.com; public procurement summary)"
# txsmartbuy.gov/robots.txt is "Disallow: /", so ESBD is not fetched.


def robots_block(client: httpx.Client, url: str) -> bool:
    origin = url.split("/afo/")[0]
    try:
        response = client.get(origin + "/robots.txt", timeout=15)
    except Exception:
        return False
    if response.status_code == 404:
        return False
    agent = None
    disallow_all = False
    for line in response.text.splitlines():
        piece = line.split("#", 1)[0].strip()
        if not piece or ":" not in piece:
            continue
        key, value = [part.strip() for part in piece.split(":", 1)]
        if key.lower() == "user-agent":
            agent = value
        elif key.lower() == "disallow" and agent in {"*", None}:
            if value == "/":
                disallow_all = True
    return disallow_all


def parse_listing(html: str) -> list[RawNotice]:
    text = re.sub(r"(?is)<script.*?>.*?</script>", " ", html)
    text = re.sub(r"(?is)<style.*?>.*?</style>", " ", text)
    chunks = re.split(r"(?=(?:IFB|RFQS|RFP|RFQ)\s+\d+\s+[A-Z0-9]+)", text, flags=re.I)
    notices = []
    for chunk in chunks:
        head = re.match(r"(IFB|RFQS|RFP|RFQ)\s+(\d+\s+[A-Z0-9]+)", chunk, re.I)
        if not head:
            continue
        bid = re.sub(r"\s+", " ", head.group(0)).strip()
        due = re.search(r"Due Date:\s*([^<\n]+)", chunk, re.I)
        href = re.search(r'href="([^"]+)"', chunk, re.I)
        plain = re.sub(r"<[^>]+>", " ", chunk)
        plain = re.sub(r"\s+", " ", plain).strip()
        plain = re.sub(re.escape(bid), "", plain, count=1).strip()
        deadline_text = due.group(1).strip() if due else "Deadline not stated"
        deadline_at = None
        parsed = re.search(r"(\d{1,2}/\d{1,2}/\d{4})", deadline_text)
        if parsed:
            try:
                deadline_at = datetime.strptime(parsed.group(1), "%m/%d/%Y")
            except ValueError:
                deadline_at = None
        description = plain
        if due:
            description = plain.split(due.group(0), 1)[-1].strip()
        url = urljoin(LIST_URL, href.group(1)) if href else f"{LIST_URL}#{re.sub(r'[^A-Z0-9]+', '-', bid)}"
        notices.append(RawNotice(
            source_key="austin_tx",
            external_id=bid,
            source_url=url,
            state="TX",
            agency="City of Austin",
            title=description[:180] or bid,
            description=description[:4000],
            deadline_at=deadline_at,
            deadline_text=deadline_text,
        ))
    return notices


def fetch(client: httpx.Client, limit: int = 8) -> tuple[list[RawNotice], str]:
    if robots_block(client, LIST_URL):
        return [], "Austin solicitations page disallows crawlers in robots.txt."
    try:
        response = client.get(LIST_URL, timeout=25)
        response.raise_for_status()
    except Exception as exc:
        return [], f"Austin solicitations failed: {exc}"
    notices = parse_listing(response.text)[:limit]
    if not notices:
        return [], "Austin page returned no solicitation rows."
    return notices, ""
