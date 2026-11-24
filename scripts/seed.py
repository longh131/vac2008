import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.db import SessionLocal
from app.models import Opportunity, Setting

SAMPLES = [
    ("sample-tx-hvac", "TX", "HVAC & Plumbing", "City of Lockhart", "Replace the library's aging AC units",
     "The city wants a small crew to swap two rooftop AC units at the public library and haul the old ones away. Work is on one building, during weekday hours. The hard part is matching the existing ducts."),
    ("sample-tx-clean", "TX", "Cleaning & Janitorial", "Travis County Facilities", "Nightly cleaning for a small county office",
     "A three-story county office needs trash, floors, and restrooms cleaned five nights a week. You supply the crew and basic chemicals. They want someone local who can start this month."),
    ("sample-tx-lawn", "TX", "Landscaping", "City of Georgetown Parks", "Mow and edge three neighborhood parks",
     "Mow, edge, and blow three small parks every two weeks through the growing season. No playground install and no irrigation rebuild. A two-person crew can cover it."),
    ("sample-fl-it", "FL", "IT & Tech", "City of Leesburg", "On-call help for a 12-person city office",
     "The city office wants a local tech to reset passwords, replace a few PCs, and keep the Wi-Fi running. This is a support retainer, not a data-center build."),
    ("sample-fl-plumb", "FL", "HVAC & Plumbing", "Alachua County Facilities", "Fix leaking restroom pipes at a community center",
     "Two restrooms have slow leaks and a failing water heater. They want the repair done in one visit if parts are on the truck. A licensed plumber is required."),
    ("sample-fl-supply", "FL", "Supplies & Logistics", "Leon County Schools", "Deliver copy paper and janitorial supplies",
     "Drop paper, soap, and trash liners at four small school offices once a month. No construction. They care about showing up on the delivery day."),
    ("sample-fl-roof", "FL", "Construction & Repair", "City of Live Oak", "Patch a flat roof over a storage shed",
     "One storage building has a leaking flat roof. They want a patch and a short warranty, not a full reroof of the civic center. A small roofing crew fits this."),
    ("sample-tx-old", "TX", "Other", "City of Bastrop", "Expired sample: paint a storage room",
     "This sample is already past its deadline so it should stay off the public list."),
]


def main() -> None:
    db = SessionLocal()
    try:
        if not db.get(Setting, "display_price"):
            db.add(Setting(key="display_price", value="29"))
        now = datetime.utcnow()
        for index, (external, state, category, agency, title, summary) in enumerate(SAMPLES):
            exists = db.query(Opportunity).filter_by(source_key="seed", external_id=external).one_or_none()
            if exists:
                continue
            expired = external.endswith("old")
            deadline = now - timedelta(days=2) if expired else now + timedelta(days=14 + index)
            db.add(Opportunity(
                source_key="seed",
                external_id=external,
                source_url=f"https://vac2008.com/sample/{external}",
                state=state,
                city_or_agency=agency,
                category=category,
                title_raw=title,
                title_clean=title,
                estimated_budget="Not Disclosed" if expired else f"${12000 + index * 3500:,} (Est.)",
                deadline_at=deadline,
                deadline_text=deadline.strftime("%b %d, %Y"),
                summary_plain=summary,
                fit_score=35 if expired else 74 + (index % 4) * 4,
                fit_reason="Past the due date." if expired else "Short local job. A small crew can price this without a bonding company.",
                contact_name="Purchasing Desk",
                contact_email=f"purchasing@{external}.example",
                contact_phone="(512) 555-0100",
                bid_email_draft=(
                    f"Subject: Interest in {title}\n\n"
                    f"Hello Purchasing Desk,\n\n"
                    f"My name is [Your Name] with [Your Company]. We are a small local crew and we can do this work: {summary} "
                    f"I can send insurance and two references.\n\n[Your Name]\n[Your Company]\n[Your Phone]"
                ),
                raw_text=summary,
                raw_hash=external,
                status="expired" if expired else "active",
                ai_status="fallback",
                published_at=now - timedelta(hours=index),
            ))
        db.commit()
        print("seed ok")
    finally:
        db.close()


if __name__ == "__main__":
    main()
