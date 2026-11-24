import hashlib
import re
from datetime import datetime

CATEGORIES = [
    "HVAC & Plumbing",
    "Construction & Repair",
    "Cleaning & Janitorial",
    "Landscaping",
    "IT & Tech",
    "Supplies & Logistics",
    "Other",
]

_CATEGORY_WORDS = [
    ("HVAC & Plumbing", ("hvac", "plumb", "pipe", "boiler", "air condition", "a/c ")),
    ("Cleaning & Janitorial", ("janitor", "custod", "cleaning", "sanitation")),
    ("Landscaping", ("landscape", "mowing", "lawn", "grounds", "tree trim")),
    ("IT & Tech", ("software", "computer", "network", "it support", "help desk")),
    ("Supplies & Logistics", ("supply", "supplies", "delivery", "fuel", "office paper", "logistics")),
    ("Construction & Repair", ("repair", "roof", "paint", "construct", "electrical", "maintenance", "hvac")),
]


def guess_category(text: str) -> str:
    blob = text.lower()
    for name, words in _CATEGORY_WORDS:
        if any(word in blob for word in words):
            return name
    return "Other"


def preview_draft(text: str) -> str:
    lines = [line.strip() for line in (text or "").splitlines() if line.strip()]
    snippet = " ".join(lines[:2])
    snippet = re.sub(r"[\w.+-]+@[\w.-]+", "[hidden]", snippet)
    snippet = re.sub(r"\+?\d[\d\s().-]{7,}\d", "[hidden]", snippet)
    return snippet[:280]


def is_member(status: str | None, period_end: datetime | None, now: datetime | None = None) -> bool:
    if status == "active":
        return True
    now = now or datetime.utcnow()
    return status == "canceled" and period_end is not None and period_end >= now


def grounded(value: str, blob: str) -> str:
    text = (value or "").strip()
    if not text:
        return ""
    return text if text.lower() in blob.lower() else ""


def text_hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8", errors="ignore")).hexdigest()
