"""Reading replies to applications: classification, matching, storage."""

from __future__ import annotations

from datetime import date, datetime, timezone
from email.message import EmailMessage

import pytest

from jobradar.errors import ConfigError, MailError
from jobradar.mail import check_mail, interview_ics
from jobradar.mail.classify import classify, find_interview
from jobradar.mail.imap import ImapConfig, MailMessage, fetch_since, parse_message
from jobradar.mail.sync import match_job, process
from jobradar.models import Application, ApplicationStage, ApplicationStatus, MailKind
from tests.conftest import make_job

RECEIVED = datetime(2026, 9, 20, 9, 30, tzinfo=timezone.utc)


def message(subject: str, body: str, sender: str = "Talent Team <jobs@acme-foods.com>",
            name: str = "") -> MailMessage:
    display, _, address = sender.partition("<")
    return MailMessage(message_id=f"<{subject}@x>", received_at=RECEIVED,
                       sender_name=name or display.strip(), sender_address=address.strip(">"),
                       subject=subject, body=body)


# ---------------------------------------------------------------------------
# Classification
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("subject", "body", "kind"),
    [
        ("Your application", "Unfortunately we have decided to move forward with other candidates.",
         MailKind.REJECTION),
        ("Tu candidatura", "Lamentablemente no has sido seleccionada para el puesto.",
         MailKind.REJECTION),
        ("Next steps", "We would like to invite you to an interview next week.", MailKind.ADVANCE),
        ("Proceso de selección", "Nos gustaría conocerte en una entrevista por videollamada.",
         MailKind.ADVANCE),
        ("Application received", "Thank you for applying. We have received your application.",
         MailKind.ACKNOWLEDGEMENT),
        ("Candidatura", "Hemos recibido tu candidatura y la revisaremos.", MailKind.ACKNOWLEDGEMENT),
    ],
)
def test_replies_are_classified_in_english_and_spanish(subject, body, kind):
    assert classify(subject, body)[0] == kind


def test_a_rejection_that_thanks_you_is_still_a_rejection():
    kind, excerpt = classify("Update", "Thank you for applying. Unfortunately, the position has "
                                       "been filled. We wish you luck.")
    assert kind == MailKind.REJECTION
    assert excerpt == "Unfortunately, the position has been filled."


def test_job_alerts_are_noise():
    assert classify("5 new jobs for you", "Job alert: apply to these roles now.")[0] is None


def test_the_excerpt_is_a_literal_sentence():
    body = "Hi Ana.\nWe would like to invite you to an interview on Monday. Best, Tom"
    _kind, excerpt = classify("Hello", body)
    assert excerpt in body


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Could you do an interview on 3 October at 10:30?", datetime(2026, 10, 3, 10, 30)),
        ("Te proponemos el 14 de octubre a las 16:00 por videollamada.", datetime(2026, 10, 14, 16, 0)),
        ("Interview slot: 07/10 at 9.15", datetime(2026, 10, 7, 9, 15)),
        ("How about October 2nd at 3pm?", datetime(2026, 10, 2, 15, 0)),
        ("We will be in touch next week.", None),
        ("Your interview is on 3 October.", None),  # a date without a time is not an event
    ],
)
def test_interview_times_are_found(text, expected):
    when, _ = find_interview(text, date(2026, 9, 20))
    assert when == expected


def test_a_date_already_past_this_year_means_next_year():
    when, _ = find_interview("Interview on 5 January at 10:00", date(2026, 12, 1))
    assert when == datetime(2027, 1, 5, 10, 0)


# ---------------------------------------------------------------------------
# Matching
# ---------------------------------------------------------------------------


def test_the_company_is_found_in_the_sender_domain():
    jobs = [make_job(native_id="1", company="Acme Foods SL", title="Warehouse Operative"),
            make_job(native_id="2", company="Other Co", title="Warehouse Operative")]
    msg = message("Your application", "We have received your application.",
                  sender="Talent <no-reply@acmefoods.com>")
    assert match_job(msg, jobs).native_id == "1"


def test_mail_from_a_shared_ats_domain_needs_the_company_in_the_text():
    jobs = [make_job(native_id="1", company="Acme Foods", title="Chef")]
    anonymous = message("Update", "Thank you for applying.", sender="<noreply@greenhouse.io>")
    named = message("Your application to Acme Foods", "Thank you for applying.",
                    sender="<noreply@greenhouse.io>")
    assert match_job(anonymous, jobs) is None
    assert match_job(named, jobs).native_id == "1"


def test_the_title_breaks_a_tie_between_jobs_at_one_company():
    jobs = [make_job(native_id="1", company="Acme Foods", title="Chef de partie"),
            make_job(native_id="2", company="Acme Foods", title="Warehouse Operative")]
    msg = message("Warehouse Operative at Acme Foods", "Unfortunately we will not proceed.")
    assert match_job(msg, jobs).native_id == "2"


def test_replies_to_jobs_not_marked_applied_are_orphans():
    job = make_job(native_id="1", company="Acme Foods")
    stranger = message("Your application", "We have received your application.",
                       sender="Hiring <jobs@unknown-bakery.com>")
    ours = message("Interview", "We would like to invite you to an interview.")
    news, orphans = process([stranger, ours], [job], applied_ids=set())
    assert set(news) == {job.id}
    assert len(orphans) == 2  # one unmatched, one matched but not marked applied
    news, orphans = process([stranger, ours], [job], applied_ids={job.id})
    assert [o.company_hint for o in orphans] == ["Hiring"]


# ---------------------------------------------------------------------------
# The whole check, with the mail server replaced
# ---------------------------------------------------------------------------


def test_check_mail_stores_news_and_never_touches_the_application(database, settings, monkeypatch):
    job = make_job(native_id="1", company="Acme Foods", title="Warehouse Operative")
    database.upsert_jobs([job])
    database.save_application(Application(job_id=job.id, status=ApplicationStatus.APPLIED,
                                          stage=ApplicationStage.APPLIED))
    replies = [message("Warehouse Operative", "Unfortunately we have decided not to proceed."),
               message("Interview", "Can you come in on 1 October at 11:00 for an interview?")]
    replies[1].received_at = RECEIVED.replace(day=21)
    seen = {}

    def fake_fetch(config, since, limit=400):
        seen["since"] = since
        return replies

    monkeypatch.setattr("jobradar.mail.sync.fetch_since", fake_fetch)
    config = ImapConfig(host="imap.test", user="me@test", password="x")
    report = check_mail(database, settings, today=date(2026, 9, 24), config=config)

    assert seen["since"] == date(2026, 9, 24).fromordinal(date(2026, 9, 24).toordinal() - 30)
    news = database.mail_news()[job.id]
    assert news.kind == MailKind.ADVANCE  # the newest reply wins
    assert news.interview_at == datetime(2026, 10, 1, 11, 0)
    assert database.get_application(job.id).stage == ApplicationStage.APPLIED
    assert report.news and not report.orphans

    check_mail(database, settings, today=date(2026, 9, 26), config=config)
    assert seen["since"] == date(2026, 9, 24)  # starts where the last check ended

    ics = interview_ics(news, job)
    assert "DTSTART:20261001T110000" in ics and "Warehouse Operative" in ics


def test_missing_configuration_is_explained(monkeypatch):
    for name in ("JOBRADAR_IMAP_HOST", "JOBRADAR_IMAP_USER", "JOBRADAR_IMAP_PASSWORD"):
        monkeypatch.delenv(name, raising=False)
    with pytest.raises(ConfigError, match="JOBRADAR_IMAP_HOST") as caught:
        ImapConfig.from_environment()
    assert "app password" in caught.value.hint


def test_an_unreachable_server_is_a_mail_error():
    config = ImapConfig(host="127.0.0.1", user="me", password="x", port=1)
    with pytest.raises(MailError, match="Cannot connect"):
        fetch_since(config, date(2026, 9, 1))


def test_parse_message_prefers_the_plain_part_and_decodes_headers():
    raw = EmailMessage()
    raw["From"] = "=?utf-8?q?Recursos_Humanos?= <rrhh@panaderia.es>"
    raw["Subject"] = "=?utf-8?q?Tu_candidatura?="
    raw["Date"] = "Sun, 20 Sep 2026 09:30:00 +0200"
    raw["Message-ID"] = "<1@panaderia.es>"
    raw.set_content("Hola. Hemos recibido tu candidatura.")
    raw.add_alternative("<p>Hola. <b>Hemos recibido</b> tu candidatura.</p>", subtype="html")
    parsed = parse_message(raw.as_bytes())
    assert parsed.sender_name == "Recursos Humanos"
    assert parsed.subject == "Tu candidatura"
    assert parsed.body.strip() == "Hola. Hemos recibido tu candidatura."
