import hashlib
import hmac
import json
import re

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_home_hides_expired_sample():
    page = client.get("/")
    assert page.status_code == 200
    assert "Expired sample" not in page.text
    assert "purchasing@" not in page.text
    if "City of Austin" in page.text or "Department of" in page.text:
        assert "Replace the library" not in page.text
    else:
        assert "Replace the library" in page.text


def test_sitemap_lists_real_bids():
    page = client.get("/sitemap.xml")
    assert page.status_code == 200
    assert "/opportunities/" in page.text
    assert "sample" not in page.text


def test_paywall_then_member_unlock(monkeypatch):
    monkeypatch.setattr("app.main.send_mail", lambda *args, **kwargs: "smtp-not-configured")
    home = client.get("/").text
    match = re.search(r'href="/opportunities/(\d+)"', home)
    assert match
    item_id = match.group(1)
    locked = client.get(f"/opportunities/{item_id}")
    assert "Original posting" not in locked.text
    assert "Unlock for $" in locked.text

    page = client.post("/login", data={"email": "owner@example.com"})
    token = re.search(r"/auth/verify\?token=([^\"']+)", page.text).group(1)
    assert client.get(f"/auth/verify?token={token}", follow_redirects=False).status_code == 303

    client.post("/admin/login", data={"password": "replace-me"})
    user_id = re.search(r"/admin/members/(\d+)", client.get("/admin?tab=members").text)
    assert user_id
    client.post(f"/admin/members/{user_id.group(1)}", data={"status": "active"})
    opened = client.get(f"/opportunities/{item_id}")
    assert "Original posting" in opened.text


def test_paypal_webhook_rejects_missing_signature():
    denied = client.post("/webhooks/paypal", content=b"{}")
    assert denied.status_code == 400


def test_webhook_rejects_bad_signature():
    body = json.dumps({"data": {"id": "1", "attributes": {"user_email": "a@b.com", "status": "active"}}}).encode()
    denied = client.post("/webhooks/lemonsqueezy", content=body, headers={"x-signature": "nope"})
    assert denied.status_code == 400
    secret = "replace-me"
    signature = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    # The example secret is treated as unset, so a valid-looking signature still waits for a real secret.
    waiting = client.post("/webhooks/lemonsqueezy", content=body, headers={"x-signature": signature})
    assert waiting.status_code == 400
