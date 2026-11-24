import smtplib
from email.message import EmailMessage

from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

from app.config import get_settings

settings = get_settings()


def signer() -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(settings.secret_key, salt="vac2008-unsub")


def unsub_token(user_id: int) -> str:
    return signer().dumps({"uid": user_id})


def read_unsub_token(token: str) -> int | None:
    try:
        data = signer().loads(token, max_age=60 * 60 * 24 * 180)
    except (BadSignature, SignatureExpired):
        return None
    try:
        return int(data["uid"])
    except (KeyError, TypeError, ValueError):
        return None


def send_mail(to: str, subject: str, body: str) -> str:
    if not settings.smtp_host:
        return "smtp-not-configured"
    message = EmailMessage()
    message["From"] = settings.smtp_from
    message["To"] = to
    message["Subject"] = subject
    message.set_content(body)
    with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=20) as smtp:
        smtp.starttls()
        if settings.configured(settings.smtp_user):
            smtp.login(settings.smtp_user, settings.smtp_password)
        smtp.send_message(message)
    return "sent"
