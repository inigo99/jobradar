"""Checking the inbox: classify each reply and attach it to its job.

For every message about an application (:mod:`jobradar.mail.classify`), the
job it is about is found by the company — in the sender's name, the sender's
own domain, the subject and the opening of the body — and, to break ties, by
the job title. The newest message per job is kept as that job's news.

Nothing here changes an application's status: a rejection is *suggested* on
the dashboard and the user decides. Messages about an application that match
no job, or a job not marked as applied, are kept as "orphans" so the user can
spot applications made outside JobRadar.
"""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone

from ..config import Settings
from ..models import ApplicationStatus, Job, MailKind, MailNews
from ..pipeline.dedupe import company_key, title_tokens
from ..storage import Database
from ..textutils import contains_phrase, normalise
from .classify import classify, find_interview
from .imap import ImapConfig, MailMessage, fetch_since

log = logging.getLogger(__name__)

#: Domains that send mail on behalf of many employers: their name says
#: nothing about which company wrote.
SHARED_DOMAINS = (
    "gmail", "googlemail", "outlook", "hotmail", "yahoo", "icloud", "proton", "greenhouse",
    "lever", "workday", "myworkday", "myworkdayjobs", "smartrecruiters", "teamtailor",
    "bamboohr", "personio", "recruitee", "workable", "ashbyhq", "successfactors", "taleo",
    "icims", "jobvite", "infojobs", "linkedin", "indeed", "glassdoor", "manfred",
    "getmanfred", "tecnoempleo", "welcometothejungle", "breezy", "jazzhr", "join",
)
#: How much of the body is searched for the company name.
MATCH_WINDOW = 1500
#: Minimum company-key length worth matching: "AB" would match anything.
MIN_COMPANY_KEY = 3


@dataclass
class MailReport:
    """What one inbox check found."""

    checked: int = 0
    news: list[MailNews] = field(default_factory=list)
    orphans: list[MailNews] = field(default_factory=list)
    since: date | None = None

    def summary(self) -> str:
        return (f"{self.checked} messages read since {self.since}: {len(self.news)} replies "
                f"matched to jobs, {len(self.orphans)} about applications not on the board.")


def _sender_domain_name(address: str) -> str:
    """``jobs@careers.acme.co.uk`` -> ``acme``; "" for shared senders."""
    domain = address.rsplit("@", 1)[-1].lower()
    labels = [label for label in domain.split(".") if label]
    if len(labels) < 2:
        return ""
    # Skip common second-level suffixes: acme.co.uk -> acme.
    name = labels[-3] if len(labels) >= 3 and labels[-2] in ("co", "com", "org", "gov") \
        else labels[-2]
    # "acme-foods" and "acmefoods" are both Acme Foods.
    return "" if name in SHARED_DOMAINS else name.replace("-", "")


def match_job(message: MailMessage, jobs: list[Job]) -> Job | None:
    """The job ``message`` is about, or None.

    A company match is required: a title alone ("Data Analyst") is shared by
    too many employers to decide anything. Among company matches, the one
    whose title shares most words with the message wins.
    """
    haystack = f"{message.sender_name}\n{message.subject}\n{message.body[:MATCH_WINDOW]}"
    domain = _sender_domain_name(message.sender_address)
    words = set(normalise(haystack).split())
    best: tuple[int, Job] | None = None
    for job in jobs:
        key = company_key(job.company or "")
        if len(key) < MIN_COMPANY_KEY:
            continue
        compact = key.replace(" ", "")
        if not (contains_phrase(haystack, key) or (domain and domain in (compact, key))):
            continue
        overlap = len(title_tokens(job.title) & words)
        if best is None or overlap > best[0]:
            best = (overlap, job)
    return best[1] if best else None


def _company_hint(message: MailMessage) -> str:
    return message.sender_name or _sender_domain_name(message.sender_address) \
        or message.sender_address


def to_news(message: MailMessage, kind: MailKind, excerpt: str, job: Job | None) -> MailNews:
    interview_at, interview_text = (None, "")
    if kind == MailKind.ADVANCE:
        interview_at, interview_text = find_interview(
            f"{message.subject}\n{message.body}", message.received_at.date())
    return MailNews(
        job_id=job.id if job else "",
        kind=kind,
        received_at=message.received_at,
        subject=message.subject,
        sender=message.sender,
        excerpt=excerpt,
        message_id=message.message_id,
        link=message.link,
        company_hint=_company_hint(message),
        interview_at=interview_at,
        interview_text=interview_text,
    )


def process(messages: list[MailMessage], jobs: list[Job],
            applied_ids: set[str]) -> tuple[dict[str, MailNews], list[MailNews]]:
    """``(latest news per job id, orphans)`` from a batch of messages."""
    news: dict[str, MailNews] = {}
    orphans: list[MailNews] = []
    for message in messages:
        kind, excerpt = classify(message.subject, message.body)
        if kind is None:
            continue
        job = match_job(message, jobs)
        item = to_news(message, kind, excerpt, job)
        if job is None or job.id not in applied_ids:
            orphans.append(item)
        if job is not None:
            current = news.get(job.id)
            if current is None or item.received_at > current.received_at:
                news[job.id] = item
    return news, orphans


def check_mail(database: Database, settings: Settings, today: date | None = None,
               config: ImapConfig | None = None) -> MailReport:
    """Read new mail, store the news per job and the orphans. Read-only on the inbox.

    Raises :class:`~jobradar.errors.ConfigError` when the ``JOBRADAR_IMAP_*``
    variables are missing, and :class:`~jobradar.errors.MailError` when the
    server cannot be reached or refuses the login.
    """
    config = config or ImapConfig.from_environment()
    today = today or date.today()
    last = database.mail_checked_on()
    # Re-read the last day checked: mail can arrive late in a day already seen.
    since = min(today, last) if last else today - timedelta(days=settings.mail.days_back)
    messages = fetch_since(config, since)
    jobs = database.list_jobs(include_closed=True)
    applications = database.all_applications()
    applied = {job_id for job_id, app in applications.items()
               if app.status == ApplicationStatus.APPLIED}
    news, orphans = process(messages, jobs, applied)
    database.save_mail_news(news.values())
    database.save_mail_orphans(orphans)
    database.set_mail_checked_on(today)
    report = MailReport(checked=len(messages), news=list(news.values()), orphans=orphans,
                        since=since)
    log.info("Mail: %s", report.summary())
    return report


def interview_ics(news: MailNews, job: Job | None, duration_minutes: int = 60) -> str:
    """An iCalendar event for a proposed interview, to import by hand.

    JobRadar never writes to a calendar itself: the user downloads this and
    adds it after checking the time with the sender.
    """
    if news.interview_at is None:
        raise ValueError("this message proposes no interview time")
    start = news.interview_at
    end = start + timedelta(minutes=duration_minutes)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    title = f"Interview: {job.company} — {job.title}" if job else f"Interview ({news.company_hint})"

    def escape(text: str) -> str:
        return (text.replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,")
                .replace("\n", "\\n"))

    return "\r\n".join([
        "BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//JobRadar//EN", "BEGIN:VEVENT",
        f"UID:{hashlib.sha1((news.message_id + start.isoformat()).encode()).hexdigest()}@jobradar",
        f"DTSTAMP:{stamp}",
        f"DTSTART:{start.strftime('%Y%m%dT%H%M%S')}",
        f"DTEND:{end.strftime('%Y%m%dT%H%M%S')}",
        f"SUMMARY:{escape(title)}",
        f"DESCRIPTION:{escape(news.interview_text + (chr(10) + news.link if news.link else ''))}",
        "END:VEVENT", "END:VCALENDAR", "",
    ])
