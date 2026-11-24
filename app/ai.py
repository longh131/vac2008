import json
import re

import httpx

from app.config import get_settings
from app.services import guess_category

settings = get_settings()


def fallback_card(notice) -> dict:
    blob = f"{notice.title}\n{notice.description}"
    budget = "Not Disclosed"
    money = re.search(r"\$[\d,]+(?:\.\d+)?", blob)
    if money:
        budget = f"{money.group(0)} (Est.)"
    score = 68
    lowered = blob.lower()
    if any(word in lowered for word in ("local", "maintenance", "repair", "janitorial", "mowing")):
        score = 78
    if any(word in lowered for word in ("statewide", "prequalification", "design-build", "million")):
        score = 42
    deadline = notice.deadline_text or "Deadline not stated"
    summary = (
        f"{notice.agency or 'The agency'} is asking for: {notice.title}. "
        f"The posting says the work is due {deadline}. "
        "Read the official notice before you bid. Small local crews should check insurance, license, and bonding rules first."
    )
    if notice.description:
        sentence = re.split(r"(?<=[.!?])\s+", notice.description.strip())[0]
        summary = (
            f"{notice.agency or 'The agency'} needs this work: {notice.title}. "
            f"{sentence} "
            f"Deadline: {deadline}. "
            "A one-to-ten person shop should confirm the license and insurance rules before spending time on a quote."
        )
    contact = notice.contact_name or "the buyer"
    draft = (
        f"Subject: Interest in {notice.title}\n\n"
        f"Hello {contact},\n\n"
        f"My name is [Your Name] with [Your Company], a small local firm. "
        f"We can take on this work and finish it before {deadline}. "
        f"I can send insurance, references, and a short price.\n\n"
        "[Your Name]\n[Your Company]\n[Your Phone]"
    )
    return {
        "title_clean": notice.title[:240],
        "category": guess_category(blob),
        "estimated_budget": budget,
        "summary_plain": summary,
        "fit_score": score,
        "fit_reason": "Budget and crew size look workable for a small local shop." if score >= 60 else "This one may expect a larger firm or a special license.",
        "bid_email_draft": draft,
        "ai_status": "fallback",
    }


def _parse_json(content: str) -> dict:
    text = content.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?", "", text).strip()
        text = re.sub(r"```$", "", text).strip()
    return json.loads(text)


def enrich(notice) -> dict:
    card = fallback_card(notice)
    if not settings.configured(settings.deepseek_api_key):
        return card
    blob = f"{notice.title}\n{notice.agency}\n{notice.description}"[:5000]
    prompt = {
        "title": notice.title,
        "agency": notice.agency,
        "state": notice.state,
        "deadline": notice.deadline_text,
        "text": blob,
    }
    system = (
        "You turn one public government bid into JSON for a very small local contractor. "
        "Return only JSON with keys title_clean, category, estimated_budget, summary_plain, "
        "fit_score, fit_reason, bid_email_draft. "
        f"category must be one of: {', '.join(['HVAC & Plumbing','Construction & Repair','Cleaning & Janitorial','Landscaping','IT & Tech','Supplies & Logistics','Other'])}. "
        "summary_plain is 3 to 5 plain sentences: the work, what must be delivered, and the hard part. "
        "fit_score is an integer 1-100 for a 1 to 10 person shop. "
        "bid_email_draft is an English email with [Your Name], [Your Company], and [Your Phone]. "
        "Do not invent a dollar amount, email, or phone. Use Not Disclosed when the budget is missing."
    )
    url = settings.deepseek_base_url.rstrip("/") + "/chat/completions"
    payload = {
        "model": settings.deepseek_model,
        "temperature": 0.2,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": json.dumps(prompt)},
        ],
    }
    headers = {"Authorization": f"Bearer {settings.deepseek_api_key}"}
    last_error = None
    for _ in range(2):
        try:
            response = httpx.post(url, json=payload, headers=headers, timeout=40)
            response.raise_for_status()
            content = response.json()["choices"][0]["message"]["content"]
            data = _parse_json(content)
            card.update({
                "title_clean": str(data.get("title_clean") or card["title_clean"])[:240],
                "category": data.get("category") if data.get("category") in {
                    "HVAC & Plumbing", "Construction & Repair", "Cleaning & Janitorial",
                    "Landscaping", "IT & Tech", "Supplies & Logistics", "Other",
                } else card["category"],
                "estimated_budget": str(data.get("estimated_budget") or "Not Disclosed")[:120],
                "summary_plain": str(data.get("summary_plain") or card["summary_plain"]),
                "fit_score": max(1, min(100, int(data.get("fit_score") or card["fit_score"]))),
                "fit_reason": str(data.get("fit_reason") or card["fit_reason"])[:300],
                "bid_email_draft": str(data.get("bid_email_draft") or card["bid_email_draft"]),
                "ai_status": "ok",
            })
            return card
        except Exception as exc:
            last_error = exc
    card["ai_status"] = "fallback"
    card["fit_reason"] = (card["fit_reason"] + f" AI fallback: {last_error}")[:300]
    return card
