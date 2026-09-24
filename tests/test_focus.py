"""Focus: the triage order, and the reason attached to it."""

from __future__ import annotations

from datetime import date, timedelta

from jobradar.models import MatchScore, Salary, SalaryOrigin
from jobradar.pipeline.focus import focus_for, is_senior_title, rank
from tests.conftest import make_job

TODAY = date(2026, 9, 11)
SCORE = MatchScore(base=70.0, tailored=80.0)


def _job(**overrides):
    overrides.setdefault("posted_at", TODAY)
    return make_job(**overrides)


def test_a_fresh_job_keeps_its_whole_score():
    focus, reason = focus_for(_job(salary=Salary()), SCORE, TODAY)
    assert focus == 80.0
    assert reason == ""


def test_an_old_ad_is_demoted_and_says_so():
    job = _job(posted_at=TODAY - timedelta(days=25), salary=Salary())
    focus, reason = focus_for(job, SCORE, TODAY)
    assert focus < 30
    assert "three weeks" in reason


def test_a_missing_date_is_not_treated_as_stale():
    """Silence is not evidence. Most aggregators omit the date entirely."""
    focus, _reason = focus_for(_job(posted_at=None, salary=Salary()), SCORE, TODAY)
    assert focus == 80.0


def test_a_senior_title_is_demoted_when_the_years_are_out_of_reach():
    job = _job(title="Senior Machine Learning Engineer", salary=Salary())
    focus, reason = focus_for(job, SCORE, TODAY, max_years=3.0)
    assert focus < 50
    assert "senior" in reason


def test_a_senior_title_that_asks_for_few_years_is_left_alone():
    """A title is a label; the years are the actual filter."""
    job = _job(title="Senior Engineer", min_years_experience=2, salary=Salary())
    focus, reason = focus_for(job, SCORE, TODAY, max_years=3.0)
    assert focus == 80.0
    assert "senior" not in reason


def test_publishing_a_band_is_worth_a_small_bonus():
    published = _job(salary=Salary(minimum=50000, maximum=60000, origin=SalaryOrigin.PUBLISHED))
    silent = _job(salary=Salary())
    assert focus_for(published, SCORE, TODAY)[0] > focus_for(silent, SCORE, TODAY)[0]


def test_the_match_score_is_never_modified():
    job = _job(posted_at=TODAY - timedelta(days=30), title="Lead Architect")
    focus_for(job, SCORE, TODAY)
    assert SCORE.tailored == 80.0


def test_rank_orders_by_focus_not_by_match():
    strong_but_old = (_job(native_id="a", posted_at=TODAY - timedelta(days=30), salary=Salary()),
                      MatchScore(tailored=95.0))
    weaker_but_fresh = (_job(native_id="b", posted_at=TODAY, salary=Salary()),
                        MatchScore(tailored=70.0))
    ordered = rank([strong_but_old, weaker_but_fresh], TODAY)
    assert ordered[0][0].native_id == "b"


def test_is_senior_title_matches_other_languages():
    assert is_senior_title("Arquitecto de Software")
    assert is_senior_title("Head of Data")
    assert not is_senior_title("Data Engineer")


def test_focus_survives_null_fields():
    job = _job()
    job.title = None
    job.salary = None
    focus, reason = focus_for(job, SCORE, TODAY)
    assert focus is not None
