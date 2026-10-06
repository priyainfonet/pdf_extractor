"""
Sends real emails via SMTP (stdlib smtplib — no extra dependency). If
SMTP isn't configured (no SMTP_HOST in .env), falls back to just logging
the email content instead of failing outright — useful for local dev
where you don't want to stand up a mail server just to test the
password-reset flow. You'll see the reset link directly in the server
logs in that case.
"""

import logging
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

from app.core.config import settings

logger = logging.getLogger("email_service")


def send_email(to_email: str, subject: str, body_text: str) -> None:
    if not settings.SMTP_HOST:
        logger.info(
            "SMTP not configured — email NOT actually sent. Would have sent to=%s subject=%r\n%s",
            to_email,
            subject,
            body_text,
        )
        return

    msg = MIMEMultipart()
    msg["From"] = settings.SMTP_FROM_EMAIL or settings.SMTP_USERNAME
    msg["To"] = to_email
    msg["Subject"] = subject
    msg.attach(MIMEText(body_text, "plain"))

    try:
        with smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT, timeout=10) as server:
            if settings.SMTP_USE_TLS:
                server.starttls()
            if settings.SMTP_USERNAME:
                server.login(settings.SMTP_USERNAME, settings.SMTP_PASSWORD)
            server.sendmail(msg["From"], [to_email], msg.as_string())
        logger.info("Email sent to=%s subject=%r", to_email, subject)
    except Exception:
        # Log the failure but don't crash the request — password-reset
        # endpoints should still return their generic "if this email
        # exists..." response either way (see app/api/auth.py).
        logger.exception("Failed to send email to=%s", to_email)


def send_password_reset_email(to_email: str, reset_link: str) -> None:
    subject = "Reset your PDFKit password"
    body = (
        f"We received a request to reset your PDFKit password.\n\n"
        f"Click this link to choose a new password (expires in "
        f"{settings.RESET_TOKEN_EXPIRE_MINUTES} minutes):\n\n"
        f"{reset_link}\n\n"
        f"If you didn't request this, you can safely ignore this email."
    )
    send_email(to_email, subject, body)
