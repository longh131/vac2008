import hashlib
import hmac
import json
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import Subscription, User

settings = get_settings()

STATUS_MAP = {
    "active": "active",
    "on_trial": "active",
    "cancelled": "canceled",
    "canceled": "canceled",
    "past_due": "past_due",
    "unpaid": "past_due",
    "expired": "expired",
    "paused": "past_due",
}


def apply_webhook(db: Session, body: bytes, signature: str) -> tuple[int, str]:
    secret = settings.lemonsqueezy_webhook_secret
    if not settings.configured(secret):
        return 400, "webhook secret is not configured"
    expected = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, signature or ""):
        return 400, "bad signature"
    try:
        payload = json.loads(body)
        attrs = payload["data"]["attributes"]
        email = str(attrs.get("user_email") or "").strip().lower()
        status = STATUS_MAP.get(str(attrs.get("status") or "").lower(), "expired")
        sub_id = str(payload["data"].get("id") or "")
        renews = attrs.get("renews_at") or attrs.get("ends_at")
    except (KeyError, TypeError, json.JSONDecodeError):
        return 400, "unexpected payload"
    if "@" not in email:
        return 400, "missing email"
    user = db.scalar(select(User).where(User.email == email))
    if not user:
        user = User(email=email)
        db.add(user)
        db.commit()
        db.refresh(user)
    sub = db.scalar(select(Subscription).where(Subscription.user_id == user.id))
    if not sub:
        sub = Subscription(user_id=user.id)
        db.add(sub)
    sub.provider_subscription_id = sub_id
    sub.status = status
    sub.updated_at = datetime.utcnow()
    if renews:
        try:
            sub.current_period_end = datetime.fromisoformat(str(renews).replace("Z", "+00:00")).replace(tzinfo=None)
        except ValueError:
            sub.current_period_end = None
    db.commit()
    return 200, "ok"
