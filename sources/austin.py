import html as html_lib
import re
from datetime import datetime
from urllib.parse import urljoin

import httpx

from sources.types import RawNotice

LIST_URL = "https://financeonline.austintexas.gov/afo/account_services/solicitation/solicitations.cfm"
# txsmartbuy.gov/robots.txt is "Disallow: /", so ESBD is not fetched.
WELL = re.compile(r'(?is)<div class="well parent">(.*?)</div>\s*</div>')
BID = re.compile(
    r'(?is)<a href="([^"]*solicitation_details\.cfm\?sid=\d+)">\s*((?:IFB|RFQS|RFP|RFQ)\s+[^<]+)</a>'
)
DUE = re.compile(r"(?is)Due Date:\s*<strong>\s*([^<]+)</strong>")
TITLE = re.compile(r"(?is)Due Date:.*?</div>\s*<strong>\s*([^<]+)</strong>\s*<br\s*/?\s*>(.*)")
CLOCK = re.compile(
    r"(\d{1,2}/\d{1,2}/\d{4})(?:\s+at\s+(\d{1,2})(?::(\d{2}))?\s*(AM|PM))?",
    re.I,
)


def snippet(text: str) -> str:
    flat = re.sub(r"<[^>]+>", " ", text or "")
    flat = re.sub(r"\s+", " ", flat).strip()
    return flat[:180]


def robots_block(client: httpx.Client, url: str) -> bool:
    origin = url.split("/afo/")[0]
    try:
        response = client.get(origin + "/robots.txt", timeout=15)
    except Exception:
        return False
    if response.status_code != 200:
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


def parse_due(text: str) -> datetime | None:
    match = CLOCK.search(text or "")
    if not match:
        return None
    try:
        day = datetime.strptime(match.group(1), "%m/%d/%Y")
    except ValueError:
        return None
    hour_raw = match.group(2)
    if not hour_raw:
        return day.replace(hour=23, minute=59)
    hour = int(hour_raw)
    minute = int(match.group(3) or 0)
    ampm = (match.group(4) or "").upper()
    if ampm == "PM" and hour != 12:
        hour += 12
    if ampm == "AM" and hour == 12:
        hour = 0
    return day.replace(hour=hour, minute=minute)


def parse_listing(html: str) -> list[RawNotice]:
    notices = []
    seen = set()
    for block in WELL.findall(html):
        head = BID.search(block)
        if not head:
            continue
        bid = re.sub(r"\s+", " ", head.group(2)).strip()
        if bid in seen:
            continue
        seen.add(bid)
        due = DUE.search(block)
        deadline_text = re.sub(r"\s+", " ", due.group(1)).strip() if due else "Deadline not stated"
        titled = TITLE.search(block)
        if titled:
            title = re.sub(r"\s+", " ", html_lib.unescape(titled.group(1))).strip()
            description = re.sub(r"<[^>]+>", " ", html_lib.unescape(titled.group(2)))
            description = re.sub(r"\s+", " ", description).strip()
        else:
            title = bid
            description = ""
        notices.append(RawNotice(
            source_key="austin_tx",
            external_id=bid,
            source_url=urljoin(LIST_URL, head.group(1)),
            state="TX",
            agency="City of Austin",
            title=(title or bid)[:500],
            description=(description or title)[:4000],
            deadline_at=parse_due(deadline_text),
            deadline_text=deadline_text[:120],
        ))
    return notices


def fetch(client: httpx.Client, limit: int = 24) -> tuple[list[RawNotice], str]:
    if robots_block(client, LIST_URL):
        return [], "Austin solicitations page disallows crawlers in robots.txt."
    try:
        response = client.get(LIST_URL, timeout=25)
        response.raise_for_status()
    except Exception as exc:
        return [], f"Austin solicitations failed: {exc}"
    if "html" not in response.headers.get("content-type", "").lower():
        return [], f"Austin page was not HTML: {snippet(response.text)}"
    notices = parse_listing(response.text)[:limit]
    if not notices:
        return [], f"Austin page returned no solicitation rows: {snippet(response.text)}"
    return notices, ""
