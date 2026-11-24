from datetime import datetime

from app.services import guess_category, is_member, preview_draft
from sources.austin import attach_contact, parse_listing
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
        "descriptionText": "<p>Replace two flush valves.&nbsp;Today.</p>",
        "contactEmail": "bids@gainesville.example",
    }]}}
    found = []
    find_records(payload, found)
    notice = normalize(found[0])
    assert notice is not None
    assert notice.state == "FL"
    assert notice.external_id == "42"
    assert notice.contact_email == "bids@gainesville.example"
    assert notice.description == "Replace two flush valves. Today."


def test_austin_html():
    html = """
    <div class="well parent">
      <div class="td-space-left clearfix child">
        <strong><a href="solicitation_details.cfm?sid=142008">IFB 6100 CLMC1105</a></strong>
        <div>Due Date: <strong>12/03/2026 at  2PM</strong></div>
        <strong>Duct bank repair</strong>
        <br />Furnish labor and materials for a small duct bank repair.
      </div>
    </div>
    <div class="well parent">
      <div class="td-space-left clearfix child">
        <strong><a href="solicitation_details.cfm?sid=144241">RFQS 6100 CLMP397</a></strong>
        <div>Due Date: <strong>12/01/2026 at  2PM</strong></div>
        <strong>Staff augmentation</strong>
        <br />Staff augmentation for engineering.
      </div>
    </div>
    """
    rows = parse_listing(html)
    assert len(rows) == 2
    assert rows[0].state == "TX"
    assert rows[0].external_id == "IFB 6100 CLMC1105"
    assert rows[0].title == "Duct bank repair"
    assert rows[0].deadline_at == datetime(2026, 12, 3, 14, 0)
    assert "duct bank" in rows[0].description
    assert "sid=142008" in rows[0].source_url


def test_paypal_status_map():
    from app.paypal import membership_status

    assert membership_status("ACTIVE") == "active"
    assert membership_status("CANCELLED") == "canceled"
    assert membership_status("APPROVED") == "expired"


def test_austin_contact_block():
    from sources.types import RawNotice

    class Fake:
        status_code = 200
        text = """
        <th>Solicitation Specific<br> Questions:</th>
        <td>Jacqueline Nunez<br>(512) 978-1345<br>jackie.nunez@austintexas.gov</td>
        <td>Lisa Barney<br>smbrcompliancedocuments@austintexas.gov</td>
        """

        def get(self, url, timeout=25):
            return self

    notice = RawNotice("austin_tx", "IFB 1", "https://example.com/solicitation_details.cfm?sid=1", "TX", "City of Austin", "Gas monitors", "Lease detectors.", None, "Dec 1")
    attach_contact(Fake(), notice)
    assert notice.contact_name == "Jacqueline Nunez"
    assert notice.contact_email == "jackie.nunez@austintexas.gov"
    assert "978" in notice.contact_phone


def test_big_jobs_score_lower_than_repairs():
    from app.ai import fallback_card
    big = RawNotice("x", "1", "https://example.com", "FL", "State", "Statewide roof repair", "A statewide contract.", None, "Dec 1")
    small = RawNotice("x", "2", "https://example.com", "TX", "City", "Roof repair", "Local repair.", None, "Dec 1")
    assert fallback_card(big)["fit_score"] < fallback_card(small)["fit_score"]


def test_fallback_does_not_invent_budget():
    from app.ai import fallback_card
    notice = RawNotice("x", "1", "https://example.com", "TX", "City", "Mow three parks", "Local crew, no bond.", None, "Dec 1")
    card = fallback_card(notice)
    assert card["estimated_budget"] == "Not Disclosed"
    assert "[Your Company]" in card["bid_email_draft"]
