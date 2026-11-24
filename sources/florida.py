import html
import re
import time
from datetime import datetime

import httpx

from sources.types import RawNotice

LIST_URL = "https://vendor.myfloridamarketplace.com/mfmp/pub/search/bids"
DETAIL_URL = "https://vendor.myfloridamarketplace.com/mfmp/pub/search/bids/detail"
PAGE = "https://vendor.myfloridamarketplace.com/search/bids/detail/{}"
HEADERS = {
    "Accept": "application/json, text/plain, */*",
    "Content-Type": "application/json",
    "Origin": "https://vendor.myfloridamarketplace.com",
    "Referer": "https://vendor.myfloridamarketplace.com/search/bids",
}
# Public VIP search is a POST. Types 4 and 6 are Invitation to Bid and Request for Proposals.
SEARCH_BODY = {
    "page": 1,
    "pageSize": 25,
    "type": ["4", "6"],
    "status": ["OPEN"],
    "agency": [],
    "adNumber": "",
    "agencyAdvertisementNumber": "",
    "title": "",
    "publishedDate": "",
    "openDate": "",
    "endDate": "",
    "commodityCodes": [],
}


def snippet(text: str) -> str:
    flat = re.sub(r"\s+", " ", text or "").strip()
    return flat[:180]


def plain_text(value: str) -> str:
    text = html.unescape(value or "")
    text = re.sub(r"(?is)<script.*?>.*?</script>", " ", text)
    text = re.sub(r"(?is)<style.*?>.*?</style>", " ", text)
    text = re.sub(r"<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def parse_dt(value) -> datetime | None:
    if not value or not isinstance(value, str):
        return None
    text = value.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    return parsed.replace(tzinfo=None)


def find_records(node, found: list) -> None:
    if isinstance(node, list):
        rows = [item for item in node if isinstance(item, dict) and (item.get("title") or item.get("advertisementId"))]
        if rows:
            found.extend(rows)
            return
        for item in node:
            find_records(item, found)
    elif isinstance(node, dict):
        for value in node.values():
            find_records(value, found)


def contact_of(item: dict) -> tuple[str, str, str]:
    block = item.get("responseContact") if isinstance(item.get("responseContact"), dict) else {}
    name = item.get("contactName") or block.get("responseContact") or block.get("name") or ""
    email = item.get("contactEmail") or block.get("email") or ""
    phone = item.get("contactPhone") or block.get("ph") or block.get("phone") or ""
    return str(name or ""), str(email or ""), str(phone or "")


def normalize(item: dict) -> RawNotice | None:
    title = plain_text(str(item.get("title") or ""))
    kind = str(item.get("type") or "")
    status = str(item.get("status") or "OPEN").upper()
    if not title or status not in {"OPEN", ""}:
        return None
    if any(word in kind.lower() for word in ("agency decision", "single source", "informational")):
        return None
    external = str(item.get("advertisementId") or item.get("id") or item.get("agencyAdNumber") or "").strip()
    if not external:
        return None
    deadline = parse_dt(item.get("closeDate") or item.get("endDate"))
    deadline_text = deadline.strftime("%b %d, %Y") if deadline else str(item.get("closeDate") or "Deadline not stated")
    name, email, phone = contact_of(item)
    url = str(item.get("url") or item.get("source_url") or PAGE.format(external))
    description = plain_text(str(item.get("descriptionText") or item.get("description") or ""))
    agency = item.get("agency") or item.get("agencyName") or ""
    if isinstance(agency, dict):
        agency = agency.get("name") or ""
    return RawNotice(
        source_key="fl_vbs",
        external_id=external,
        source_url=url,
        state="FL",
        agency=str(agency),
        title=title[:500],
        description=description[:4000],
        deadline_at=deadline,
        deadline_text=deadline_text[:120],
        contact_name=name,
        contact_email=email,
        contact_phone=phone,
    )


def merge_detail(notice: RawNotice, item: dict) -> RawNotice:
    extra = normalize(item)
    if extra is None:
        return notice
    notice.description = extra.description or notice.description
    notice.contact_name = extra.contact_name or notice.contact_name
    notice.contact_email = extra.contact_email or notice.contact_email
    notice.contact_phone = extra.contact_phone or notice.contact_phone
    notice.deadline_at = extra.deadline_at or notice.deadline_at
    notice.deadline_text = extra.deadline_text or notice.deadline_text
    notice.agency = extra.agency or notice.agency
    return notice


def fetch(client: httpx.Client, limit: int = 12) -> tuple[list[RawNotice], str]:
    try:
        response = client.post(LIST_URL, json=SEARCH_BODY, headers=HEADERS, timeout=25)
    except Exception as exc:
        return [], f"Florida search failed: {exc}"
    content_type = response.headers.get("content-type", "")
    if response.status_code >= 400 or "json" not in content_type:
        return [], f"Florida search HTTP {response.status_code}: {snippet(response.text)}"
    try:
        payload = response.json()
    except Exception as exc:
        return [], f"Florida search was not JSON ({exc}): {snippet(response.text)}"
    if isinstance(payload, dict) and payload.get("errorMessage"):
        return [], f"Florida search error: {snippet(str(payload.get('errorMessage')))}"
    found: list[dict] = []
    find_records(payload, found)
    notices = []
    for item in found:
        notice = normalize(item)
        if notice:
            notices.append(notice)
        if len(notices) >= limit:
            break
    if not notices:
        return [], f"Florida search returned no open bids this parser kept: {snippet(response.text)}"
    detailed = []
    for index, notice in enumerate(notices):
        if index:
            time.sleep(1)
        try:
            detail = client.get(DETAIL_URL, params={"id": notice.external_id}, headers=HEADERS, timeout=25)
            if detail.status_code == 200 and "json" in detail.headers.get("content-type", ""):
                body = detail.json()
                row = body if isinstance(body, dict) and body.get("title") else None
                if row is None and isinstance(body, dict):
                    rows: list[dict] = []
                    find_records(body, rows)
                    row = rows[0] if rows else None
                if row:
                    notice = merge_detail(notice, row)
        except Exception:
            pass
        detailed.append(notice)
    return detailed, ""
