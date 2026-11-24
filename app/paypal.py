import json
import time
from datetime import datetime

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import Subscription, User

settings = get_settings()

STATUS_MAP = {
    "ACTIVE": "active",
    "SUSPENDED": "past_due",
    "CANCELLED": "canceled",
    "EXPIRED": "expired",
}
_token_cache = {"value": "", "until": 0.0}


def ready() -> bool:
    return all(settings.configured(value) for value in (
        settings.paypal_client_id,
        settings.paypal_client_secret,
        settings.paypal_plan_id,
    ))


def api_base() -> str:
    if settings.paypal_mode.strip().lower() == "sandbox":
        return "https://api-m.sandbox.paypal.com"
    return "https://api-m.paypal.com"


def membership_status(paypal_status: str) -> str:
    return STATUS_MAP.get((paypal_status or "").upper(), "expired")


def _token() -> str:
    now = time.time()
    if _token_cache["value"] and _token_cache["until"] > now + 30:
        return _token_cache["value"]
    response = httpx.post(
        api_base() + "/v1/oauth2/token",
        data={"grant_type": "client_credentials"},
        auth=(settings.paypal_client_id, settings.paypal_client_secret),
        timeout=25,
    )
    response.raise_for_status()
    payload = response.json()
    _token_cache["value"] = payload["access_token"]
    _token_cache["until"] = now + int(payload.get("expires_in") or 300)
    return _token_cache["value"]


def _request(method: str, path: str, body: dict | None = None) -> dict:
    response = httpx.request(
        method,
        api_base() + path,
        headers={"Authorization": f"Bearer {_token()}", "Content-Type": "application/json"},
        json=body,
        timeout=25,
    )
    response.raise_for_status()
    if not response.content:
        return {}
    return response.json()


def approval_url(return_url: str, cancel_url: str, email: str = "") -> str:
    body = {
        "plan_id": settings.paypal_plan_id,
        "application_context": {
            "brand_name": "Vendor Access Club",
            "locale": "en-US",
            "shipping_preference": "NO_SHIPPING",
            "user_action": "SUBSCRIBE_NOW",
            "return_url": return_url,
            "cancel_url": cancel_url,
        },
    }
    if "@" in email:
        body["subscriber"] = {"email_address": email}
    payload = _request("POST", "/v1/billing/subscriptions", body)
    for link in payload.get("links") or []:
        if link.get("rel") == "approve" and link.get("href"):
            return link["href"]
    raise RuntimeError("PayPal did not return an approval link")


def fetch_subscription(subscription_id: str) -> dict:
    return _request("GET", f"/v1/billing/subscriptions/{subscription_id}")


def _parse_time(value) -> datetime | None:
    if not value or not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).replace(tzinfo=None)
    except ValueError:
        return None


def grant(db: Session, resource: dict, force_active: bool = False) -> str:
    email = str((resource.get("subscriber") or {}).get("email_address") or "").strip().lower()
    sub_id = str(resource.get("id") or "")
    if "@" not in email or not sub_id:
        return "missing email"
    status = "active" if force_active else membership_status(str(resource.get("status") or ""))
    period = _parse_time((resource.get("billing_info") or {}).get("next_billing_time"))
    user = db.scalar(select(User).where(User.email == email))
    if not user:
        user = User(email=email)
        db.add(user)
        db.commit()
        db.refresh(user)
    row = db.scalar(select(Subscription).where(Subscription.user_id == user.id))
    if not row:
        row = Subscription(user_id=user.id)
        db.add(row)
    row.provider = "paypal"
    row.provider_subscription_id = sub_id[:80]
    row.status = status
    row.updated_at = datetime.utcnow()
    if period:
        row.current_period_end = period
    db.commit()
    return "ok"


def verify_webhook(headers, body: bytes) -> tuple[bool, dict | None]:
    if not settings.configured(settings.paypal_webhook_id):
        return False, None
    names = (
        "paypal-auth-algo",
        "paypal-cert-url",
        "paypal-transmission-id",
        "paypal-transmission-sig",
        "paypal-transmission-time",
    )
    if any(not headers.get(name) for name in names):
        return False, None
    try:
        event = json.loads(body)
    except (json.JSONDecodeError, TypeError):
        return False, None
    try:
        result = _request("POST", "/v1/notifications/verify-webhook-signature", {
            "auth_algo": headers.get("paypal-auth-algo"),
            "cert_url": headers.get("paypal-cert-url"),
            "transmission_id": headers.get("paypal-transmission-id"),
            "transmission_sig": headers.get("paypal-transmission-sig"),
            "transmission_time": headers.get("paypal-transmission-time"),
            "webhook_id": settings.paypal_webhook_id,
            "webhook_event": event,
        })
    except Exception:
        return False, None
    if result.get("verification_status") != "SUCCESS":
        return False, None
    return True, event


def apply_event(db: Session, event: dict) -> str:
    name = str(event.get("event_type") or "")
    resource = event.get("resource") or {}
    if name == "PAYMENT.SALE.COMPLETED":
        sub_id = str(resource.get("billing_agreement_id") or "")
        if not sub_id:
            return "ignored"
        return grant(db, fetch_subscription(sub_id), force_active=True)
    if name.startswith("BILLING.SUBSCRIPTION."):
        return grant(db, resource)
    return "ignored"
