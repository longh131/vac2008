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
    assert "Replace the library" in page.text
    assert "Expired sample" not in page.text
    assert "purchasing@" not in page.text


def test_paywall_then_member_unlock():
    home = client.get("/").text
    cards = re.findall(r'href="/opportunities/(\d+)"(.*?)</a>', home, re.S)
    item_id = next(card_id for card_id, body in cards if "Replace the library" in body)
    locked = client.get(f"/opportunities/{item_id}")
    assert "purchasing@" not in locked.text
    assert "Unlock for $" in locked.text

    page = client.post("/login", data={"email": "owner@example.com"})
    token = re.search(r"/auth/verify\?token=([^\"']+)", page.text).group(1)
    assert client.get(f"/auth/verify?token={token}", follow_redirects=False).status_code == 303

    client.post("/admin/login", data={"password": "replace-me"})
    user_id = re.search(r"/admin/members/(\d+)", client.get("/admin").text)
    assert user_id
    client.post(f"/admin/members/{user_id.group(1)}", data={"status": "active"})
    opened = client.get(f"/opportunities/{item_id}")
    assert "purchasing@" in opened.text
    assert "Original posting" in opened.text


def test_webhook_rejects_bad_signature():
    body = json.dumps({"data": {"id": "1", "attributes": {"user_email": "a@b.com", "status": "active"}}}).encode()
    denied = client.post("/webhooks/lemonsqueezy", content=body, headers={"x-signature": "nope"})
    assert denied.status_code == 400
    secret = "replace-me"
    signature = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    # The example secret is treated as unset, so a valid-looking signature still waits for a real secret.
    waiting = client.post("/webhooks/lemonsqueezy", content=body, headers={"x-signature": signature})
    assert waiting.status_code == 400
