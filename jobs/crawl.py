import time
from datetime import datetime, timedelta

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai import enrich
from app.models import CrawlRun, Opportunity
from app.services import text_hash
from sources.austin import fetch as fetch_austin
from sources.florida import fetch as fetch_florida
from sources.types import RawNotice

UA = "VendorAccessClub/1.0 (+https://vac2008.com; public procurement summary)"
SMB_WORDS = (
    "hvac", "plumb", "janitor", "custod", "landscape", "mowing", "lawn",
    "clean", "roof", "electrical", "repair", "maintenance", "pest",
    "supply", "supplies", "delivery", "paint", "floor",
)


def rank(notices: list[RawNotice], limit: int) -> list[RawNotice]:
    def score(notice: RawNotice) -> int:
        blob = f"{notice.title} {notice.description}".lower()
        return sum(1 for word in SMB_WORDS if word in blob)

    ordered = sorted(notices, key=score, reverse=True)
    return ordered[:limit]


def save_notice(db: Session, notice: RawNotice, run: CrawlRun) -> None:
    blob = f"{notice.title}\n{notice.agency}\n{notice.description}"
    digest = text_hash(blob)
    existing = db.scalar(select(Opportunity).where(
        Opportunity.source_key == notice.source_key,
        Opportunity.external_id == notice.external_id,
    ))
    if existing and existing.raw_hash == digest and existing.ai_status in {"ok", "fallback"}:
        existing.deadline_at = notice.deadline_at
        existing.deadline_text = notice.deadline_text
        existing.updated_at = datetime.utcnow()
        if notice.deadline_at and notice.deadline_at < datetime.utcnow() and existing.status == "active":
            existing.status = "expired"
        run.updated += 1
        return
    card = enrich(notice)
    if card["ai_status"] == "ok":
        run.ai_ok += 1
    else:
        run.ai_failed += 1
    email = notice.contact_email
    phone = notice.contact_phone
    status = "active"
    if notice.deadline_at and notice.deadline_at.date() < datetime.utcnow().date():
        status = "expired"
    values = dict(
        source_url=notice.source_url,
        state=notice.state,
        city_or_agency=notice.agency,
        category=card["category"],
        title_raw=notice.title[:500],
        title_clean=card["title_clean"],
        estimated_budget=card["estimated_budget"],
        deadline_at=notice.deadline_at,
        deadline_text=notice.deadline_text[:120],
        summary_plain=card["summary_plain"],
        fit_score=card["fit_score"],
        fit_reason=card["fit_reason"],
        contact_name=notice.contact_name[:200],
        contact_email=email[:200],
        contact_phone=phone[:80],
        bid_email_draft=card["bid_email_draft"],
        raw_text=blob[:8000],
        raw_hash=digest,
        status=status,
        ai_status=card["ai_status"],
        updated_at=datetime.utcnow(),
    )
    if existing:
        for key, value in values.items():
            setattr(existing, key, value)
        run.updated += 1
        return
    db.add(Opportunity(source_key=notice.source_key, external_id=notice.external_id[:120], published_at=datetime.utcnow(), **values))
    run.inserted += 1


def run_crawl(db: Session) -> CrawlRun:
    fresh = db.scalar(select(CrawlRun).where(
        CrawlRun.finished_at.is_(None),
        CrawlRun.started_at >= datetime.utcnow() - timedelta(minutes=20),
    ))
    if fresh:
        return fresh
    run = CrawlRun(started_at=datetime.utcnow())
    db.add(run)
    db.commit()
    errors = []
    try:
        with httpx.Client(headers={"User-Agent": UA, "Accept": "application/json,text/html"}, follow_redirects=True) as client:
            for fetcher in (fetch_florida, fetch_austin):
                notices, error = fetcher(client)
                if error:
                    errors.append(error)
                picked = rank(notices, 8)
                run.found += len(picked)
                for notice in picked:
                    save_notice(db, notice, run)
                    db.commit()
                    time.sleep(1.2)
    except Exception as exc:
        errors.append(str(exc))
    run.error = "\n".join(errors)[:4000]
    run.finished_at = datetime.utcnow()
    db.commit()
    return run


def main() -> None:
    from app.db import SessionLocal

    db = SessionLocal()
    try:
        run = run_crawl(db)
        print(f"crawl {run.id}: found={run.found} inserted={run.inserted} updated={run.updated} error={run.error}")
    finally:
        db.close()


if __name__ == "__main__":
    main()
