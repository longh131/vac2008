from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.mailer import send_mail, unsub_token
from app.models import EmailLog, Opportunity, Subscription, User
from app.services import is_member


def run_digest(db: Session) -> str:
    today = datetime.utcnow().date()
    since = datetime.utcnow() - timedelta(hours=36)
    notices = db.scalars(select(Opportunity).where(
        Opportunity.status == "active",
        Opportunity.fit_score >= 60,
        Opportunity.published_at >= since,
    ).order_by(Opportunity.fit_score.desc()).limit(8)).all()
    if not notices:
        return "no notices"
    users = db.scalars(select(User).where(User.digest_opt_out.is_(False))).all()
    sent = 0
    for user in users:
        sub = db.scalar(select(Subscription).where(Subscription.user_id == user.id))
        if not sub or not is_member(sub.status, sub.current_period_end):
            continue
        already = db.scalar(select(EmailLog).where(
            EmailLog.user_id == user.id,
            EmailLog.kind == "digest",
            EmailLog.sent_on == today,
        ))
        if already:
            continue
        base = f"https://{get_settings().domain}"
        lines = [f"- {item.title_clean} ({item.state}, {item.category}) {base}/opportunities/{item.id}" for item in notices]
        token = unsub_token(user.id)
        body = (
            "Today's small government jobs in Texas and Florida:\n\n"
            + "\n".join(lines)
            + f"\n\nUnsubscribe: {base}/unsubscribe?token={token}\n"
        )
        try:
            status = send_mail(user.email, "Vendor Access Club — today's jobs", body)
        except Exception as exc:
            status = "error"
            detail = str(exc)[:500]
        else:
            detail = ""
        db.add(EmailLog(user_id=user.id, kind="digest", sent_on=today, status=status, detail=detail))
        db.commit()
        sent += 1
    return f"sent {sent}"


def main() -> None:
    from app.db import SessionLocal

    db = SessionLocal()
    try:
        print(run_digest(db))
    finally:
        db.close()


if __name__ == "__main__":
    main()
