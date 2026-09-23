"""The filter chain, including the cases that quietly lose good jobs."""

from datetime import date, timedelta

from jobradar.config import Filters
from jobradar.models import RemoteScope, Salary, SalaryOrigin, WorkMode
from jobradar.pipeline.filters import ExchangeRates, apply_filters, explain
from tests.conftest import make_job

TODAY = date(2026, 9, 8)


def test_drops_stale_ads():
    job = make_job(posted_at=TODAY - timedelta(days=20))
    outcome = apply_filters(job, Filters(max_age_days=7), today=TODAY)
    assert not outcome.keep and "days ago" in outcome.reason


def test_keeps_undated_ads_by_default():
    assert apply_filters(make_job(posted_at=None), Filters(), today=TODAY).keep


def test_remote_only_drops_onsite():
    job = make_job(work_mode=WorkMode.ONSITE, location="Madrid, Spain")
    filters = Filters(work_modes=[WorkMode.REMOTE])
    assert not apply_filters(job, filters, today=TODAY).keep


def test_local_area_is_the_exception_to_remote_only():
    """'Remote anywhere, plus an office job in my own city' has to work."""
    job = make_job(work_mode=WorkMode.ONSITE, location="Valencia, Spain")
    filters = Filters(work_modes=[WorkMode.REMOTE], local_areas=["Valencia"])
    assert apply_filters(job, filters, today=TODAY).keep


def test_us_only_remote_is_dropped_for_a_spanish_candidate():
    job = make_job(remote_scope=RemoteScope.COUNTRY, country="US", location="Remote — US only")
    outcome = apply_filters(job, Filters(home_country="ES"), today=TODAY)
    assert not outcome.keep and "restricted" in outcome.reason


def test_emea_remote_is_kept_for_a_spanish_candidate():
    job = make_job(remote_scope=RemoteScope.REGION, remote_regions=["EMEA"], country="")
    assert apply_filters(job, Filters(home_country="ES"), today=TODAY).keep


def test_unknown_remote_scope_is_kept_but_warns():
    job = make_job(remote_scope=RemoteScope.UNKNOWN)
    outcome = apply_filters(job, Filters(home_country="ES"), today=TODAY)
    assert outcome.keep and outcome.warnings


def test_salary_floor_uses_converted_currency():
    job = make_job(salary=Salary(minimum=30000, maximum=30000, currency="USD",
                                 origin=SalaryOrigin.PUBLISHED))
    rates = ExchangeRates(rates={"EUR": 1.0, "USD": 2.0})  # 30k USD == 15k EUR
    filters = Filters(min_salary=25000, salary_currency="EUR")
    assert not apply_filters(job, filters, rates, today=TODAY).keep


def test_missing_salary_is_not_dropped_by_the_floor():
    job = make_job(salary=Salary(origin=SalaryOrigin.UNKNOWN))
    outcome = apply_filters(job, Filters(min_salary=40000), today=TODAY)
    assert outcome.keep and outcome.warnings


def test_experience_ceiling():
    job = make_job(min_years_experience=9)
    outcome = apply_filters(job, Filters(max_years_experience=5), today=TODAY)
    assert not outcome.keep


def test_excluded_keyword():
    job = make_job(description="This is an unpaid internship.")
    outcome = apply_filters(job, Filters(excluded_keywords=["unpaid"]), today=TODAY)
    assert not outcome.keep and "unpaid" in outcome.reason


def test_explain_groups_reasons():
    assert explain({"a": "published 9 days ago", "b": "published 12 days ago"})[0][1] == 2


def test_filters_survive_null_fields():
    job = make_job()
    setattr(job, "title", None)
    setattr(job, "company", None)
    setattr(job, "description", None)
    setattr(job, "location", None)
    setattr(job, "salary", None)
    outcome = apply_filters(job, Filters(), today=TODAY)
    assert outcome is not None