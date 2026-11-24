from datetime import datetime

from app.services import guess_category, is_member, preview_draft
from sources.austin import parse_listing
from sources.florida import find_records, normalize
from sources.types import RawNotice


def test_preview_hides_email():
    text = "Hello buyer@city.gov\nCall 512-555-0199 tomorrow\nMore secret lines"
    shown = preview_draft(text)
    assert "buyer@city.gov" not in shown
    assert "512-555-0199" not in shown
    assert "More secret" not in shown


def test_membership_window():
    assert is_member("active", None)
    assert is_member("canceled", datetime(2099, 1, 1))
    assert not is_member("past_due", datetime(2099, 1, 1))
    assert not is_member("canceled", datetime(2000, 1, 1))


def test_category():
    assert guess_category("nightly janitorial service") == "Cleaning & Janitorial"


def test_florida_nested_json():
    payload = {"page": {"content": [{
        "advertisementId": 42,
        "title": "Park restroom plumbing repair",
        "status": "OPEN",
        "type": "Invitation to Bid",
        "agency": "City of Gainesville",
        "closeDate": "2026-12-01T15:00:00Z",
        "descriptionText": "Replace two flush valves.",
        "contactEmail": "bids@gainesville.example",
    }]}}
    found = []
    find_records(payload, found)
    notice = normalize(found[0])
    assert notice is not None
    assert notice.state == "FL"
    assert notice.external_id == "42"
    assert notice.contact_email == "bids@gainesville.example"


def test_austin_html():
    html = """
    <p>IFB 6100 CLMC1105 View Details</p>
    <p>Due Date: 12/03/2026 at 2PM</p>
    <p>Furnish labor and materials for a small duct bank repair.</p>
    <p>RFQS 6100 CLMP397 View Details</p>
    <p>Due Date: 12/01/2026 at 2PM</p>
    <p>Staff augmentation for engineering.</p>
    """
    rows = parse_listing(html)
    assert len(rows) == 2
    assert rows[0].state == "TX"
    assert rows[0].deadline_at == datetime(2026, 12, 3)
    assert "duct bank" in rows[0].description


def test_fallback_does_not_invent_budget():
    from app.ai import fallback_card
    notice = RawNotice("x", "1", "https://example.com", "TX", "City", "Mow three parks", "Local crew, no bond.", None, "Dec 1")
    card = fallback_card(notice)
    assert card["estimated_budget"] == "Not Disclosed"
    assert "[Your Company]" in card["bid_email_draft"]
