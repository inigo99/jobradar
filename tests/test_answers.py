"""Form answers, the answer bank, and the warnings on letters, emails and answers."""

from __future__ import annotations

import json
from datetime import date, datetime, timezone

import pytest

from jobradar.documents.answers import answer, bank_id, similar_answers, similarity
from jobradar.documents.review import measure, review_text
from jobradar.models import AnswerThread, BankEntry, LimitUnit, Salary, SalaryOrigin
from tests.conftest import SAMPLE_CV, make_job

TODAY = date(2026, 9, 24)


def rules(findings):
    return {finding.rule for finding in findings}


# ---------------------------------------------------------------------------
# Review warnings
# ---------------------------------------------------------------------------


def test_figures_from_the_profile_or_the_ad_are_fine(profile):
    job = make_job(company="Acme Foods", description="A team of 250 people. Salary 30,000 EUR.",
                   salary=Salary(minimum=30000, maximum=36000, origin=SalaryOrigin.PUBLISHED))
    text = "At Acme Foods, with 250 people, I cut errors by 47% and I would expect 36,000."
    assert "unsupported-figure" not in rules(review_text(text, profile, job, "answer", today=TODAY))
    invented = review_text("I cut errors by 52%.", profile, job, "answer", today=TODAY)
    assert "52%" in next(f for f in invented if f.rule == "unsupported-figure").message


def test_years_the_ad_asks_for_are_not_a_claim(profile):
    job = make_job()
    assert "inflated-seniority" not in rules(
        review_text("You ask for 10 years of experience; I have fewer.", profile, job, "answer"))
    assert "inflated-seniority" in rules(
        review_text("I bring 10 years of experience.", profile, job, "answer"))


def test_a_skill_named_as_a_gap_is_fine_a_claimed_one_is_not(profile):
    job = make_job()
    assert "unsupported-skill" not in rules(
        review_text("I have not worked with Kubernetes yet.", profile, job, "answer"))
    assert "unsupported-skill" in rules(
        review_text("I run Kubernetes clusters daily.", profile, job, "answer"))


def test_boilerplate_including_the_users_own_phrases(profile):
    job = make_job()
    found = review_text("I am a team player and a real rockstar.", profile, job, "answer",
                        extra_phrases=["rockstar"])
    message = next(f for f in found if f.rule == "boilerplate").message
    assert "team player" in message and "rockstar" in message


def test_email_format_checks(profile):
    job = make_job(company="Acme Foods")
    bare = rules(review_text("Hello,\nI would like to apply.", profile, job, "email"))
    assert {"no-subject", "no-greeting-name", "company-not-named"} <= bare
    good = "Subject: Chef — Ana\n\nHello [name],\nI am applying to Acme Foods."
    assert not {"no-subject", "no-greeting-name", "company-not-named"} & rules(
        review_text(good, profile, job, "email"))


def test_answers_need_not_name_the_company_but_must_fit(profile):
    job = make_job(company="Acme Foods")
    text = "Expected salary: [pending: your figure]."
    found = review_text(text, profile, job, "answer", limit=10, unit=LimitUnit.CHARACTERS)
    assert "company-not-named" not in rules(found)
    assert {"still-to-fill", "over-limit"} <= rules(found)


def test_measure_counts_like_a_form():
    assert measure("two words", LimitUnit.WORDS) == 2
    assert measure("two words", "characters") == 9


# ---------------------------------------------------------------------------
# The bank
# ---------------------------------------------------------------------------


def entry(question: str, answer_text: str = "An answer.", job_id: str = "other") -> BankEntry:
    return BankEntry(id=bank_id(question), question=question, answer=answer_text,
                     company="Other Co", job_id=job_id, saved_at=datetime.now(timezone.utc))


def test_filler_words_do_not_make_questions_similar():
    assert similarity("Why do you want to work here?", "Why did you leave your last job?") == 0
    assert similarity("Why do you want to work at our company?",
                      "Why do you want to work for this company?") >= 0.34
    assert similarity("¿Por qué quieres trabajar con nosotros?",
                      "Por que quieres trabajar aqui") >= 0.34  # accents do not matter


def test_the_jobs_own_answers_are_not_precedents():
    bank = [entry("Why do you want to work at our company?", job_id="this"),
            entry("Why do you want to work for this company?")]
    found = similar_answers("Why do you want to work with our company?", bank, exclude_job="this")
    assert [p.entry.job_id for p in found] == ["other"]


# ---------------------------------------------------------------------------
# Answering
# ---------------------------------------------------------------------------


class ScriptedModel:
    """A language model that returns prepared replies and records the prompts."""

    def __init__(self, *replies: str):
        self.replies = list(replies)
        self.prompts: list[str] = []

    def usable(self) -> bool:
        return True

    def complete(self, system: str, user: str, **_kwargs) -> str:
        self.prompts.append(system + "\n" + user)
        return self.replies.pop(0)


def test_without_a_model_a_precedent_or_a_pending_skeleton(profile, settings):
    job = make_job()
    thread = AnswerThread(job_id=job.id)
    text, by_model, _ = answer(profile, job, thread, "What is your expected salary?", [], settings)
    assert not by_model and "[pending:" in text
    bank = [entry("What is your expected salary range?", "Around the band you publish.")]
    text, _, precedents = answer(profile, job, thread, "What is your expected salary?", bank, settings)
    assert text == "Around the band you publish." and precedents


def test_precedents_and_the_thread_reach_the_prompt(profile, settings):
    job = make_job()
    thread = AnswerThread(job_id=job.id, limit=40)
    model = ScriptedModel("x" * 80, "Short answer that fits.")
    bank = [entry("Why do you want to work at our company?", "Because of the product.")]
    text, by_model, _ = answer(profile, job, thread, "Why do you want to work for this company?",
                               bank, settings, model)  # type: ignore[arg-type]
    assert by_model and text == "Short answer that fits."  # the first try ran over; asked again
    assert "Because of the product." in model.prompts[0]
    assert "the limit is 40" in model.prompts[1]


# ---------------------------------------------------------------------------
# Through the dashboard API
# ---------------------------------------------------------------------------


@pytest.fixture
def client(paths):
    pytest.importorskip("fastapi.testclient")
    from fastapi.testclient import TestClient

    from jobradar.web import create_app

    with TestClient(create_app(paths, allowed_hosts={"testserver"})) as test_client:
        payload = {"full_name": "Alex Morgan", "email": "alex@example.com", "country": "ES",
                   "default_language": "en", "cv_text": SAMPLE_CV, "titles": ["Chef"],
                   "keywords": [], "filters": {"work_modes": ["remote"], "home_country": "ES"},
                   "company_domains": [], "enabled_sources": [], "cv_template": "classic"}
        assert test_client.post("/api/onboarding",
                                data={"payload": json.dumps(payload)}).status_code == 200
        yield test_client


def test_a_thread_from_question_to_bank(client, database):
    job = make_job(company="Acme Foods")
    database.upsert_jobs([job])
    url = f"/api/jobs/{job.id}/answers"

    assert client.put(url + "/limit", json={"limit": 300, "unit": "characters"}).status_code == 200
    thread = client.post(url, json={"question": "What is your expected salary?"}).json()
    assert [m["role"] for m in thread["messages"]] == ["question", "answer"]
    reply = thread["messages"][1]
    assert reply["length"] == len(reply["text"]) and "still-to-fill" in {
        w["rule"] for w in reply["warnings"]}

    edited = client.put(url + "/1", json={"text": "Within your published band."}).json()
    assert edited["messages"][1]["edited_at"]
    assert client.put(url + "/0", json={"text": "x"}).status_code == 404  # a question, not an answer

    saved = client.post(url + "/1/bank").json()["entry"]
    assert saved["question"] == "What is your expected salary?"
    assert client.get(url).json()["messages"][1]["in_bank"] is True

    entry_url = f"/api/answer-bank/{saved['id']}"
    assert client.put(entry_url, json={"question": "Expected salary?",
                                       "answer": "Negotiable."}).status_code == 200
    assert client.get("/api/answer-bank").json()["entries"][0]["answer"] == "Negotiable."
    assert client.delete(entry_url).status_code == 200
    assert client.delete(entry_url).status_code == 404

    assert client.delete(url).status_code == 200
    assert client.get(url).json()["messages"] == []


def test_saved_letters_come_back_with_warnings(client, database):
    job = make_job(company="Acme Foods")
    database.upsert_jobs([job])
    url = f"/api/jobs/{job.id}/documents/email"
    assert client.post(url).status_code == 200
    saved = client.put(url, json={"text": "Hi,\nI am a team player."}).json()["document"]
    assert {"no-subject", "boilerplate", "company-not-named"} <= {w["rule"] for w in saved["warnings"]}
    listed = client.get(f"/api/jobs/{job.id}/documents").json()
    assert listed["email"]["warnings"] == saved["warnings"]
