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
        (job for job in jobs if (scores.get(job.id).tailored if scores.get(job.id) else 0) >= min_score),
        key=lambda job: -(scores.get(job.id).tailored if scores.get(job.id) else 0),
    )[:limit]

    subject = f"JobRadar: {len(ranked)} new job{'s' if len(ranked) != 1 else ''}"
    lines: list[str] = []
    for job in ranked:
        score = scores.get(job.id)
        salary = ""
        if job.salary.minimum:
            salary = f" · {job.salary.minimum:,}–{job.salary.maximum:,} {job.salary.currency}"
            if job.salary.origin.value == "estimated":
                salary += " (est.)"
        lines.append(
            f"{score.tailored:.0f}%  {job.company or 'unnamed'} — {job.title}\n"
            f"        {job.location or 'unspecified'}{salary}\n"
            f"        {job.link}"
            + (f"\n        ⚠ {job.alerts[0]}" if job.alerts else "")
        )
    body = "\n\n".join(lines) or "Nothing new today."
    return subject, body


def _send_email(subject: str, body: str) -> bool:
    host = os.environ.get("JOBRADAR_SMTP_HOST")
    recipient = os.environ.get("JOBRADAR_SMTP_TO")
    if not host or not recipient:
        log.info("Email digest skipped: JOBRADAR_SMTP_HOST / JOBRADAR_SMTP_TO are not set")
        return False
    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = os.environ.get("JOBRADAR_SMTP_FROM", recipient)
    message["To"] = recipient
    message.set_content(body)
    try:
        port = int(os.environ.get("JOBRADAR_SMTP_PORT", "587"))
        with smtplib.SMTP(host, port, timeout=30) as server:
            server.starttls()
            user = os.environ.get("JOBRADAR_SMTP_USER")
            password = os.environ.get("JOBRADAR_SMTP_PASSWORD")
            if user and password:
                server.login(user, password)
            server.send_message(message)
        return True
    except (OSError, smtplib.SMTPException) as exc:
        log.warning("Could not send the email digest: %s", exc)
        return False


def _send_telegram(subject: str, body: str) -> bool:
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        log.info("Telegram digest skipped: TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID are not set")
        return False
    try:
        response = httpx.post(
            TELEGRAM_API.format(token=token),
            json={"chat_id": chat_id, "text": f"*{subject}*\n\n{body}"[:4000],
                  "parse_mode": "Markdown", "disable_web_page_preview": True},
            timeout=30,
        )
        return response.status_code == 200
    except httpx.HTTPError as exc:
        log.warning("Could not send the Telegram digest: %s", exc)
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
