"""Job families (any sector) and the salary estimate built on them."""

from __future__ import annotations

from datetime import date

import pytest

from jobradar.config import FamilyOverride, Filters, Settings
from jobradar.families import GENERAL, catalogue_view, classify, families_for
from jobradar.models import MatchScore, RemoteScope, Salary, SalaryOrigin, WorkMode
from jobradar.pipeline.filters import apply_filters
from jobradar.pipeline.focus import focus_for
from jobradar.pipeline.salary import (
    ExchangeRates,
    adjustments_for,
    company_type,
    estimate_salary,
    hiring_country,
)
from tests.conftest import make_job

TODAY = date(2026, 9, 24)


@pytest.mark.parametrize(
    ("title", "family"),
    [
        ("Enfermera de quirófano", "healthcare"),
        ("Camarero/a para restaurante", "hospitality_tourism"),
        ("Mozo de almacén con carretilla", "logistics_transport"),
        ("Profesor de matemáticas", "education"),
        ("Abogado laboralista", "legal"),
        ("Electricista de mantenimiento", "manufacturing_trades"),
        ("Contable senior", "finance_accounting"),
        ("Trabajadora social", "care_social"),
        ("Backend Developer", "software_it"),
        ("Data Analyst", "data_analytics"),
        ("Something nobody has a word for", GENERAL),
    ],
)
def test_jobs_from_any_sector_find_their_family(title, family):
    assert classify(make_job(title=title, description=""), families_for(None)) == family


def test_the_title_outweighs_the_description():
    job = make_job(title="Nurse", description="You will use our IT systems and a software portal.")
    assert classify(job, families_for(None)) == "healthcare"


def test_user_changes_are_merged_over_the_catalogue():
    settings = Settings(families={
        "healthcare": FamilyOverride(label="Salud", priority=1.4),
        "retail": FamilyOverride(enabled=False),
        "pet_care": FamilyOverride(label="Pet care", keywords=["dog groomer"]),
        GENERAL: FamilyOverride(enabled=False),
    })
    families = families_for(settings)
    assert families["healthcare"].label == "Salud"
    assert families["healthcare"].priority == 1.4
    assert families["healthcare"].keywords  # untouched keywords still come from the catalogue
    assert "retail" not in families
    assert families["pet_care"].custom
    assert list(families)[-1] == GENERAL  # the fallback cannot be switched off
    assert classify(make_job(title="Dog groomer", description=""), families) == "pet_care"


def test_catalogue_view_shows_switched_off_families_and_defaults():
    rows = {row["key"]: row for row in catalogue_view(Settings(families={
        "retail": FamilyOverride(enabled=False)}))}
    assert rows["retail"]["enabled"] is False
    assert rows["healthcare"]["default"]["label"] == "Healthcare"


def test_priority_moves_the_board_but_not_the_score():
    job = make_job(title="Nurse", posted_at=TODAY)
    job.family = "healthcare"
    score = MatchScore(tailored=80.0)
    families = families_for(Settings(families={"healthcare": FamilyOverride(priority=1.5)}))
    plain, _ = focus_for(job, score, TODAY)
    boosted, reason = focus_for(job, score, TODAY, families=families)
    assert boosted == pytest.approx(plain * 1.5)
    assert "prioritise Healthcare" in reason
    assert score.tailored == 80.0


# ---------------------------------------------------------------------------
# Salary
# ---------------------------------------------------------------------------


def _unpublished(**fields):
    fields.setdefault("salary", Salary())
    return make_job(**fields)


def test_company_type_is_read_from_the_wording():
    assert company_type(_unpublished(description="Somos una ONG que trabaja con familias."))[0] \
        == "non_profit"
    assert company_type(_unpublished(description="Para nuestro cliente, empresa del sector."))[0] \
        == "staffing_consultancy"
    assert company_type(_unpublished(description="We make great bread."))[0] == "unknown"


def test_a_remote_job_open_to_your_country_pays_your_country_band():
    job = _unpublished(country="DE", work_mode=WorkMode.REMOTE,
                       remote_scope=RemoteScope.WORLDWIDE)
    assert hiring_country(job, "ES") == "ES"
    on_site = _unpublished(country="DE", work_mode=WorkMode.ONSITE)
    assert hiring_country(on_site, "ES") == "DE"


def test_at_most_two_adjustments_apply():
    job = _unpublished(
        min_years_experience=6,
        description="Fluent English required. Banking client. Para nuestro cliente.",
    )
    applied = adjustments_for(job, "ES")
    assert len(applied) == 2
    assert applied[0][1] == pytest.approx(1.10)  # the largest effect goes first


def test_estimate_shows_every_step_and_rounds_to_thousands():
    job = _unpublished(title="Enfermera", country="ES", description="Hospital público de Madrid.")
    salary = estimate_salary(job, "EUR", families=families_for(None), home_country="ES")
    assert salary.origin == SalaryOrigin.ESTIMATED
    assert salary.minimum % 1000 == 0 and salary.maximum % 1000 == 0
    assert "Healthcare" in salary.basis and "public sector" in salary.basis
    assert "hired in ES" in salary.basis


def test_a_converted_salary_close_to_the_minimum_is_kept_with_a_warning():
    rates = ExchangeRates(rates={"EUR": 1.0, "USD": 1.10}, as_of=date(2026, 9, 1))
    job = make_job(salary=Salary(minimum=40000, maximum=42000, currency="USD",
                                 origin=SalaryOrigin.PUBLISHED))
    outcome = apply_filters(job, Filters(min_salary=40000, salary_currency="EUR"),
                            today=TODAY, rates=rates)
    assert outcome.keep
    assert any("check today's rate" in w for w in outcome.warnings)
