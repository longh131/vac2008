import hashlib
import secrets
from datetime import datetime, timedelta

from fastapi import FastAPI, Form, HTTPException, Request
from fastapi.responses import JSONResponse, PlainTextResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import case, func, or_, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import SessionLocal
from app.mailer import read_unsub_token, send_mail
from app.models import CrawlRun, EmailLog, Favorite, LoginToken, Opportunity, Setting, Subscription, User
from app.services import CATEGORIES, is_member, preview_draft

settings = get_settings()
templates = Jinja2Templates(directory="app/templates")


def create_app() -> FastAPI:
    app = FastAPI(title="Vendor Access Club")
    app.mount("/static", StaticFiles(directory="app/static"), name="static")

    from starlette.middleware.sessions import SessionMiddleware

    app.add_middleware(
        SessionMiddleware,
        secret_key=settings.secret_key,
        https_only=not settings.debug,
        same_site="lax",
    )

    @app.get("/health")
    def health():
        return {"status": "ok", "app": "Vendor Access Club"}

    @app.get("/robots.txt")
    def robots():
        return PlainTextResponse("User-agent: *\nAllow: /\n")

    @app.get("/")
    def home(request: Request, state: str = "", category: str = "", q: str = ""):
        db = _db(request)
        rows = _listing(db, state, category, q)
        return _render(request, "home.html", {
            "rows": rows,
            "state": state,
            "category": category,
            "q": q,
            "categories": CATEGORIES,
        })

    @app.get("/opportunities/{item_id}")
    def detail(request: Request, item_id: int):
        db = _db(request)
        item = db.get(Opportunity, item_id)
        if not item:
            raise HTTPException(404)
        user = _user(request, db)
        member = _member(db, user)
        favorite = None
        if user:
            favorite = db.scalar(select(Favorite).where(Favorite.user_id == user.id, Favorite.opportunity_id == item.id))
        return _render(request, "detail.html", {"item": item, "member": member, "favorite": favorite, "preview": preview_draft(item.bid_email_draft)})

    @app.post("/opportunities/{item_id}/favorite")
    def favorite(request: Request, item_id: int):
        db = _db(request)
        user = _user(request, db)
        if not user:
            return RedirectResponse("/login", status_code=303)
        item = db.get(Opportunity, item_id)
        if not item:
            raise HTTPException(404)
        existing = db.scalar(select(Favorite).where(Favorite.user_id == user.id, Favorite.opportunity_id == item.id))
        if existing:
            db.delete(existing)
        else:
            db.add(Favorite(user_id=user.id, opportunity_id=item.id))
        db.commit()
        return RedirectResponse(f"/opportunities/{item_id}", status_code=303)

    @app.get("/pricing")
    def pricing(request: Request):
        db = _db(request)
        return _render(request, "pricing.html", {"checkout": _checkout(db, _user(request, db))})

    @app.get("/login")
    def login_form(request: Request):
        return _render(request, "login.html", {"link": request.session.pop("dev_link", "")})

    @app.post("/login")
    def login_post(request: Request, email: str = Form(...)):
        db = _db(request)
        email = email.strip().lower()
        if "@" not in email:
            _flash(request, "Enter a real email address.")
            return RedirectResponse("/login", status_code=303)
        user = db.scalar(select(User).where(User.email == email))
        if not user:
            user = User(email=email)
            db.add(user)
            db.commit()
            db.refresh(user)
        token = secrets.token_urlsafe(32)
        db.add(LoginToken(
            user_id=user.id,
            token_hash=hashlib.sha256(token.encode()).hexdigest(),
            expires_at=datetime.utcnow() + timedelta(minutes=30),
        ))
        db.commit()
        link = f"https://{settings.domain}/auth/verify?token={token}"
        if settings.debug:
            link = f"/auth/verify?token={token}"
        try:
            result = send_mail(email, "Your Vendor Access Club sign-in link", f"Sign in: {link}\nThis link expires in 30 minutes.\n")
        except Exception:
            result = "error"
        if result != "sent" and settings.debug:
            request.session["dev_link"] = link
            _flash(request, "Email is not set up yet. Use the sign-in link on this page.")
        elif result != "sent":
            _flash(request, "We could not send the email. Try again after mail is configured.")
        else:
            _flash(request, "Check your inbox for the sign-in link.")
        return RedirectResponse("/login", status_code=303)

    @app.get("/auth/verify")
    def verify(request: Request, token: str = ""):
        db = _db(request)
        row = db.scalar(select(LoginToken).where(LoginToken.token_hash == hashlib.sha256(token.encode()).hexdigest()))
        if not row or row.used_at or row.expires_at < datetime.utcnow():
            _flash(request, "That sign-in link is no longer valid.")
            return RedirectResponse("/login", status_code=303)
        row.used_at = datetime.utcnow()
        request.session["user_id"] = row.user_id
        db.commit()
        return RedirectResponse("/account", status_code=303)

    @app.get("/account")
    def account(request: Request):
        db = _db(request)
        user = _user(request, db)
        if not user:
            return RedirectResponse("/login", status_code=303)
        sub = db.scalar(select(Subscription).where(Subscription.user_id == user.id))
        favorites = db.scalars(select(Opportunity).join(Favorite, Favorite.opportunity_id == Opportunity.id).where(Favorite.user_id == user.id)).all()
        return _render(request, "account.html", {"sub": sub, "favorites": favorites, "member": _member(db, user)})

    @app.post("/account/digest")
    def digest_pref(request: Request, opt_out: str = Form("")):
        db = _db(request)
        user = _user(request, db)
        if not user:
            return RedirectResponse("/login", status_code=303)
        user.digest_opt_out = opt_out == "1"
        db.commit()
        return RedirectResponse("/account", status_code=303)

    @app.post("/logout")
    def logout(request: Request):
        request.session.clear()
        return RedirectResponse("/", status_code=303)

    @app.get("/unsubscribe")
    def unsubscribe(token: str = ""):
        db = SessionLocal()
        try:
            user_id = read_unsub_token(token)
            user = db.get(User, user_id) if user_id else None
            if not user:
                return PlainTextResponse("This unsubscribe link is not valid.", status_code=400)
            user.digest_opt_out = True
            db.commit()
            return PlainTextResponse("You will no longer get the daily job email.")
        finally:
            db.close()

    @app.post("/webhooks/lemonsqueezy")
    async def webhook(request: Request):
        from app.billing import apply_webhook

        db = SessionLocal()
        try:
            body = await request.body()
            status, message = apply_webhook(db, body, request.headers.get("x-signature", ""))
            return JSONResponse({"ok": status < 400, "message": message}, status_code=status)
        finally:
            db.close()

    @app.get("/admin")
    def admin(request: Request):
        if not request.session.get("admin"):
            return _render(request, "admin_login.html", {})
        db = _db(request)
        stats = {
            "opportunities": db.scalar(select(func.count()).select_from(Opportunity)) or 0,
            "today": db.scalar(select(func.count()).select_from(Opportunity).where(Opportunity.published_at >= datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0))) or 0,
            "ai_ok": db.scalar(select(func.count()).select_from(Opportunity).where(Opportunity.ai_status == "ok")) or 0,
            "members": db.scalar(select(func.count()).select_from(Subscription).where(Subscription.status == "active")) or 0,
            "mails": db.scalar(select(func.count()).select_from(EmailLog).where(EmailLog.status == "sent")) or 0,
        }
        runs = db.scalars(select(CrawlRun).order_by(CrawlRun.id.desc()).limit(8)).all()
        rows = db.scalars(select(Opportunity).order_by(Opportunity.id.desc()).limit(30)).all()
        users = db.scalars(select(User).order_by(User.id.desc()).limit(20)).all()
        subs = {row.user_id: row.status for row in db.scalars(select(Subscription)).all()}
        price = _setting(db, "display_price", "29")
        checkout = _setting(db, "checkout_url", settings.lemonsqueezy_checkout_url)
        return _render(request, "admin.html", {"stats": stats, "runs": runs, "rows": rows, "users": users, "subs": subs, "price": price, "checkout": checkout, "warn_password": settings.admin_password == "replace-me"})

    @app.post("/admin/login")
    def admin_login(request: Request, password: str = Form(...)):
        import secrets as sec
        if sec.compare_digest(password, settings.admin_password):
            request.session["admin"] = True
            return RedirectResponse("/admin", status_code=303)
        _flash(request, "Wrong password.")
        return RedirectResponse("/admin", status_code=303)

    @app.post("/admin/crawl")
    def admin_crawl(request: Request):
        if not request.session.get("admin"):
            return RedirectResponse("/admin", status_code=303)
        import threading
        from jobs.crawl import run_crawl

        def _work():
            db = SessionLocal()
            try:
                run_crawl(db)
            finally:
                db.close()

        threading.Thread(target=_work, daemon=True).start()
        _flash(request, "Collection started. Refresh in a minute.")
        return RedirectResponse("/admin", status_code=303)

    @app.post("/admin/opportunities/{item_id}")
    def admin_edit(request: Request, item_id: int, status: str = Form(...), title_clean: str = Form(...), fit_score: int = Form(...)):
        if not request.session.get("admin"):
            return RedirectResponse("/admin", status_code=303)
        db = _db(request)
        item = db.get(Opportunity, item_id)
        if item and status in {"active", "hidden", "expired"}:
            item.status = status
            item.title_clean = title_clean[:500]
            item.fit_score = max(1, min(100, fit_score))
            item.updated_at = datetime.utcnow()
            db.commit()
        return RedirectResponse("/admin", status_code=303)

    @app.post("/admin/settings")
    def admin_settings(request: Request, display_price: str = Form(...), checkout_url: str = Form("")):
        if not request.session.get("admin"):
            return RedirectResponse("/admin", status_code=303)
        db = _db(request)
        _put_setting(db, "display_price", display_price.strip() or "29")
        _put_setting(db, "checkout_url", checkout_url.strip())
        db.commit()
        return RedirectResponse("/admin", status_code=303)

    @app.post("/admin/members/{user_id}")
    def admin_member(request: Request, user_id: int, status: str = Form(...)):
        if not request.session.get("admin"):
            return RedirectResponse("/admin", status_code=303)
        db = _db(request)
        if status not in {"active", "canceled", "past_due", "expired"}:
            return RedirectResponse("/admin", status_code=303)
        sub = db.scalar(select(Subscription).where(Subscription.user_id == user_id))
        if not sub:
            sub = Subscription(user_id=user_id)
            db.add(sub)
        sub.status = status
        sub.updated_at = datetime.utcnow()
        if status == "active":
            sub.current_period_end = datetime.utcnow() + timedelta(days=30)
        db.commit()
        return RedirectResponse("/admin", status_code=303)

    return app


def _db(request: Request) -> Session:
    if not hasattr(request.state, "db"):
        request.state.db = SessionLocal()
    return request.state.db


def _user(request: Request, db: Session) -> User | None:
    user_id = request.session.get("user_id")
    return db.get(User, user_id) if user_id else None


def _member(db: Session, user: User | None) -> bool:
    if not user:
        return False
    sub = db.scalar(select(Subscription).where(Subscription.user_id == user.id))
    return bool(sub and is_member(sub.status, sub.current_period_end))


def _flash(request: Request, message: str) -> None:
    request.session.setdefault("flashes", []).append(message)


def _setting(db: Session, key: str, default: str) -> str:
    row = db.get(Setting, key)
    return row.value if row and row.value else default


def _put_setting(db: Session, key: str, value: str) -> None:
    row = db.get(Setting, key)
    if row:
        row.value = value
    else:
        db.add(Setting(key=key, value=value))


def _checkout(db: Session, user: User | None) -> str:
    url = _setting(db, "checkout_url", settings.lemonsqueezy_checkout_url)
    if not url:
        return ""
    if user and "checkout[email]" not in url:
        join = "&" if "?" in url else "?"
        url = f"{url}{join}checkout[email]={user.email}"
    return url


def _listing(db: Session, state: str, category: str, q: str):
    stmt = select(Opportunity).where(Opportunity.status == "active").where(
        or_(Opportunity.deadline_at.is_(None), Opportunity.deadline_at >= datetime.utcnow())
    )
    if state in {"TX", "FL"}:
        stmt = stmt.where(Opportunity.state == state)
    if category in CATEGORIES:
        stmt = stmt.where(Opportunity.category == category)
    if q.strip():
        like = f"%{q.strip()}%"
        stmt = stmt.where(or_(Opportunity.title_clean.ilike(like), Opportunity.summary_plain.ilike(like), Opportunity.city_or_agency.ilike(like)))
    seed_last = case((Opportunity.source_key == "seed", 1), else_=0)
    return db.scalars(stmt.order_by(seed_last.asc(), Opportunity.published_at.desc()).limit(20)).all()


def _render(request: Request, name: str, extra: dict):
    db = _db(request)
    user = _user(request, db)
    context = {
        "request": request,
        "user": user,
        "member": _member(db, user) if "member" not in extra else extra["member"],
        "flashes": request.session.pop("flashes", []),
        "price": _setting(db, "display_price", "29"),
    }
    context.update(extra)
    return templates.TemplateResponse(request, name, context)


app = create_app()


@app.middleware("http")
async def close_db(request: Request, call_next):
    try:
        response = await call_next(request)
    finally:
        db = getattr(request.state, "db", None)
        if db is not None:
            db.close()
    return response
