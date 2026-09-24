"""Building and sending the digest of newly found jobs."""

from __future__ import annotations

import logging
import os
import smtplib
from email.message import EmailMessage

import httpx

from ..config import NotificationSettings
from ..models import Job, MatchScore

log = logging.getLogger(__name__)

TELEGRAM_API = "https://api.telegram.org/bot{token}/sendMessage"


def build_digest(jobs: list[Job], scores: dict[str, MatchScore], limit: int = 15,
                 min_score: float = 0.0) -> tuple[str, str]:
    """Return ``(subject, body)`` for the new jobs worth telling the user about."""
    ranked = sorted(
        (job for job in jobs
         if (score := scores.get(job.id)) is not None and score.tailored >= min_score),
        key=lambda job: -scores[job.id].tailored,
    )[:limit]

    subject = f"JobRadar: {len(ranked)} new job{'s' if len(ranked) != 1 else ''}"
    lines: list[str] = []
    for job in ranked:
        score = scores.get(job.id)
        score_val = score.tailored if score else 0.0
        salary = ""
        job_salary = getattr(job, "salary", None)

        if job_salary is not None and job_salary.minimum:
            salary = f" · {job_salary.minimum:,}–{job_salary.maximum:,} {job_salary.currency}"
            if getattr(job_salary.origin, "value", "") == "estimated":
                salary += " (est.)"

        alerts = getattr(job, "alerts", None) or []
        alerts_text = f"\n        ⚠ {alerts[0]}" if alerts else ""

        lines.append(
            f"{score_val:.0f}%  {job.company or 'unnamed'} — {job.title}\n"
            f"        {job.location or 'unspecified'}{salary}\n"
            f"        {job.link}"
            f"{alerts_text}"
        )
    body = "\n\n".join(lines) or "Nothing new today."
    return subject, body


def _send_email(subject: str, body: str) -> bool:
    host = os.environ.get("JOBRADAR_SMTP_HOST")
    recipient = os.environ.get("JOBRADAR_SMTP_TO")
    if not host or not recipient:
        log.warning("Email digest is on but not sent: JOBRADAR_SMTP_HOST / JOBRADAR_SMTP_TO are not set.")
        return False
    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = os.environ.get("JOBRADAR_SMTP_FROM", recipient)
    message["To"] = recipient
    message.set_content(body)
    raw_port = os.environ.get("JOBRADAR_SMTP_PORT", "587")
    try:
        port = int(raw_port)
    except ValueError:
        log.warning("Email digest not sent: JOBRADAR_SMTP_PORT=%r is not a port number.", raw_port)
        return False
    try:
        with smtplib.SMTP(host, port, timeout=30) as server:
            server.starttls()
            user = os.environ.get("JOBRADAR_SMTP_USER")
            password = os.environ.get("JOBRADAR_SMTP_PASSWORD")
            if user and password:
                server.login(user, password)
            server.send_message(message)
        return True
    except smtplib.SMTPAuthenticationError:
        log.warning("Email digest not sent: %s rejected JOBRADAR_SMTP_USER / "
                    "JOBRADAR_SMTP_PASSWORD.", host)
        return False
    except smtplib.SMTPRecipientsRefused:
        log.warning("Email digest not sent: %s refused the recipient %s.", host, recipient)
        return False
    except (OSError, smtplib.SMTPException, ValueError) as exc:
        log.warning("Could not send the email digest through %s:%s: %s", host, port, exc)
        return False


def _send_telegram(subject: str, body: str) -> bool:
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        log.warning("Telegram digest is on but not sent: TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID are not set.")
        return False
    try:
        response = httpx.post(
            TELEGRAM_API.format(token=token),
            json={"chat_id": chat_id, "text": f"*{subject}*\n\n{body}"[:4000],
                  "parse_mode": "Markdown", "disable_web_page_preview": True},
            timeout=30,
        )
    except httpx.HTTPError as exc:
        log.warning("Could not send the Telegram digest: %s", exc)
        return False
    if response.status_code == 200:
        return True
    reasons = {
        401: "TELEGRAM_BOT_TOKEN was rejected",
        400: "Telegram refused the message; check TELEGRAM_CHAT_ID",
        403: "the bot cannot write to that chat; start a conversation with it first",
        404: "TELEGRAM_BOT_TOKEN is not a valid bot token",
        429: "Telegram is rate-limiting the bot; try again later",
    }
    log.warning("Telegram digest not sent: %s (HTTP %s).",
                reasons.get(response.status_code, "unexpected answer"), response.status_code)
    return False


def send_digest(jobs: list[Job], scores: dict[str, MatchScore],
                settings: NotificationSettings) -> dict[str, bool]:
    """Send the digest through whichever channels are switched on.

    Nothing is sent when the run found nothing: a notification that says
    "nothing happened" is one you stop reading, and then you miss the one that
    matters.
    """
    if not jobs:
        return {}
    subject, body = build_digest(jobs, scores, min_score=settings.min_score)
    sent: dict[str, bool] = {}
    if settings.email_enabled:
        sent["email"] = _send_email(subject, body)
    if settings.telegram_enabled:
        sent["telegram"] = _send_telegram(subject, body)
    return sent
