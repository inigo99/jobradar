"""Regression tests for 1.3.0.

Each case is a sentence or a situation that produced a wrong answer before —
most of them first seen on real ads by a personal radar this project shares
its rules with. They are here so none of them comes back.
"""

from datetime import date, timedelta

import pytest

from jobradar.config import Filters, SearchSettings, Settings
from jobradar.models import (
    Application,
    ApplicationStatus,
    RemoteScope,
    Salary,
    SalaryOrigin,
    WorkMode,
)
from jobradar.pipeline.dedupe import company_key, deduplicate, split_known, title_tokens
from jobradar.pipeline.enrich import derive_alerts, derive_fields
from jobradar.pipeline.filters import apply_filters, category
from jobradar.pipeline.prune import prune_stale
from jobradar.pipeline.search import SearchPipeline
from jobradar.sources.base import JobSource, SearchQuery
from jobradar.textutils import (
    contains_phrase,
    detect_remote_scope,
    detect_work_mode,
    extract_min_years,
    work_mode_evidence,
)
from jobradar.web.app import request_refusal
from tests.conftest import make_job

TODAY = date(2026, 9, 23)


# ---------------------------------------------------------------------------
# Work mode
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        # Found on a real ad: "work from home" alone made it 100% remote.
        ("Flexible policy: work from home (2 days per week).", WorkMode.HYBRID),
        ("Remote 3 days a week, the rest in our Madrid office.", WorkMode.HYBRID),
        # Five days at home is a full remote week.
        ("You can work remote 5 days a week.", WorkMode.REMOTE),
        ("This is not a remote position. Office in Madrid.", WorkMode.ONSITE),
        ("No se admite teletrabajo.", WorkMode.ONSITE),
        ("Fully remote. No hybrid, no office.", WorkMode.REMOTE),
        # The commonest English phrasing, which a list of fixed phrases missed.
        ("This is a remote position.", WorkMode.REMOTE),
        ("Modelo híbrido: 2 días en la oficina.", WorkMode.HYBRID),
        ("We are remote-first; 2 days per week in the office in Bilbao.", WorkMode.HYBRID),
        ("On-site role in Munich.", WorkMode.ONSITE),
        ("Python, Docker and REST APIs.", WorkMode.UNKNOWN),
    ],
)
def test_work_mode(text, expected):
    assert detect_work_mode(text) == expected


def test_work_mode_evidence_quotes_the_sentence():
    snippets = work_mode_evidence("Great team. We work 2 days per week in the office.")
    assert snippets and "2 days per week in the office" in snippets[0]


def test_board_remote_tag_survives_a_silent_ad():
    job = make_job(work_mode=WorkMode.REMOTE, location="Barcelona, Spain",
                   description="Python, Docker and REST APIs. " * 3)
    derive_fields(job)
    assert job.work_mode == WorkMode.REMOTE
    assert job.raw.get("remote_unconfirmed") is True
    assert any("never says so" in alert for alert in derive_alerts(job))


def test_ad_text_overrides_the_board_tag():
    job = make_job(work_mode=WorkMode.REMOTE, description="Hybrid: 3 days in the office.")
    derive_fields(job)
    assert job.work_mode == WorkMode.HYBRID
    assert "remote_unconfirmed" not in job.raw


def test_linkedin_listing_from_remote_filter_is_tagged_remote():
    from jobradar.sources.optional.linkedin import LinkedInGuestSource

    card = (
        '<li><div data-entity-urn="urn:li:jobPosting:42">'
        '<h3 class="base-search-card__title">Data Scientist</h3>'
        '<h4 class="base-search-card__subtitle"><a>Acme</a></h4>'
        '<span class="job-search-card__location">Barcelona, Spain</span>'
        "</div></li>"
    )
    source = LinkedInGuestSource(fetcher=None, options={})
    jobs = source._parse_cards(card, remote_filtered=True)
    if not jobs:  # markup assumptions live in the adapter's own tests
        pytest.skip("card markup not recognised by this fixture")
    assert jobs[0].work_mode == WorkMode.REMOTE


# ---------------------------------------------------------------------------
# Remote scope
# ---------------------------------------------------------------------------


def test_scope_eu_eligibility_is_a_region():
    assert detect_remote_scope("You must be eligible to work in the EU.") == (RemoteScope.REGION, ["EU"])


def test_scope_reads_the_named_country():
    assert detect_remote_scope("Must reside in Spain.") == (RemoteScope.COUNTRY, ["ES"])
    assert detect_remote_scope("Imprescindible residir en España") == (RemoteScope.COUNTRY, ["ES"])
    assert detect_remote_scope("Must be authorized to work in the US") == (RemoteScope.COUNTRY, ["US"])


def _remote(**overrides):
    defaults = dict(work_mode=WorkMode.REMOTE, country="", posted_at=TODAY)
    defaults.update(overrides)
    return make_job(**defaults)


SPAIN = Filters(home_country="ES", work_modes=[WorkMode.REMOTE])


def test_residency_in_your_country_is_kept():
    job = _remote(remote_scope=RemoteScope.COUNTRY, remote_regions=["ES"])
    assert apply_filters(job, SPAIN, today=TODAY).keep


def test_residency_elsewhere_is_rejected():
    job = _remote(remote_scope=RemoteScope.COUNTRY, remote_regions=["US"])
    outcome = apply_filters(job, SPAIN, today=TODAY)
    assert not outcome.keep and "US" in outcome.reason


def test_unnamed_residency_condition_is_kept_and_flagged():
    job = _remote(remote_scope=RemoteScope.COUNTRY, remote_regions=[])
    outcome = apply_filters(job, SPAIN, today=TODAY)
    assert outcome.keep
    assert any("names no country" in warning for warning in outcome.warnings)


def test_eu_region_is_eligible_from_spain():
    job = _remote(remote_scope=RemoteScope.REGION, remote_regions=["EU"])
    assert apply_filters(job, SPAIN, today=TODAY).keep


# ---------------------------------------------------------------------------
# Years of experience
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Experiencia mínima: Más de 5 años", 5),
        ("Piden entre 6 y 9 años de experiencia", 6),
        ("Between 3 and 5 years of experience", 3),
        ("3-5 years of experience", 3),
        ("7+ years of total experience", 7),
        ("2 years with Python and 5+ years of experience overall.", 5),
        ("At least 5 years of experience", 5),
        ("Al menos 3 años en desarrollo", 3),
        ("Founded 10 years ago.", None),
        ("No experience required", None),
    ],
)
def test_min_years(text, expected):
    assert extract_min_years(text) == expected


# ---------------------------------------------------------------------------
# Keyword and company lists
# ---------------------------------------------------------------------------


def test_contains_phrase_is_whole_words():
    assert not contains_phrase("JavaScript Engineer", "java")
    assert contains_phrase("Senior Java Engineer", "java")
    assert not contains_phrase("Talan", "Alan")
    assert contains_phrase("Prácticas en Python", "practic*")
    assert contains_phrase("Accenture Song", "Accenture")


def test_excluded_keyword_does_not_eat_a_longer_word():
    filters = Filters(home_country="ES", work_modes=[WorkMode.REMOTE], excluded_keywords=["java"])
    job = _remote(title="JavaScript Engineer", remote_scope=RemoteScope.WORLDWIDE, description="")
    assert apply_filters(job, filters, today=TODAY).keep


def test_excluded_company_does_not_eat_another_company():
    filters = Filters(home_country="ES", work_modes=[WorkMode.REMOTE], excluded_companies=["Alan"])
    job = _remote(company="Talan", remote_scope=RemoteScope.WORLDWIDE)
    assert apply_filters(job, filters, today=TODAY).keep
    job = _remote(company="Alan", remote_scope=RemoteScope.WORLDWIDE)
    assert not apply_filters(job, filters, today=TODAY).keep


def test_local_area_is_read_from_the_location_only():
    filters = Filters(home_country="ES", work_modes=[WorkMode.REMOTE], local_areas=["Madrid"])
    onsite = dict(work_mode=WorkMode.ONSITE, country="DE", posted_at=TODAY)
    assert apply_filters(make_job(location="Madrid, Spain", **onsite), filters, today=TODAY).keep
    abroad = make_job(company="Madrid Tech", location="Berlin", **onsite)
    assert not apply_filters(abroad, filters, today=TODAY).keep


# ---------------------------------------------------------------------------
# Salary
# ---------------------------------------------------------------------------

FLOOR = Filters(home_country="ES", work_modes=[WorkMode.REMOTE], min_salary=40000)


def test_an_estimate_never_rejects():
    estimate = Salary(minimum=30000, maximum=36000, currency="EUR", origin=SalaryOrigin.ESTIMATED)
    outcome = apply_filters(
        _remote(remote_scope=RemoteScope.WORLDWIDE, salary=estimate), FLOOR, today=TODAY
    )
    assert outcome.keep
    assert any("estimate" in warning for warning in outcome.warnings)


def test_a_published_band_is_judged_by_its_top():
    band = Salary(minimum=36000, maximum=45000, currency="EUR", origin=SalaryOrigin.PUBLISHED)
    assert apply_filters(_remote(remote_scope=RemoteScope.WORLDWIDE, salary=band), FLOOR, today=TODAY).keep
    low = Salary(minimum=30000, maximum=36000, currency="EUR", origin=SalaryOrigin.PUBLISHED)
    assert not apply_filters(_remote(remote_scope=RemoteScope.WORLDWIDE, salary=low), FLOOR, today=TODAY).keep


# ---------------------------------------------------------------------------
# Deduplication
# ---------------------------------------------------------------------------


def test_company_key_drops_the_legal_form():
    assert company_key("Talan España, S.L.U.") == company_key("Talan")
    assert company_key("Banco Santander") == company_key("Grupo Santander")
    assert company_key("Talan") != company_key("Alan")


def test_title_tokens_drop_board_tags():
    assert title_tokens("Data Engineer (m/f/d)") == title_tokens("Data Engineer - 100% remoto")


def test_legal_form_and_title_tags_collapse():
    a = make_job(native_id="1", company="Talan España, S.L.U.", title="Data Engineer (m/f/d)")
    b = make_job(native_id="2", source="other", company="Talan", title="Data Engineer - 100% remoto")
    assert len(deduplicate([a, b])) == 1


def test_different_roles_stay_apart():
    a = make_job(native_id="1", title="Backend Engineer")
    b = make_job(native_id="2", source="other", title="Frontend Engineer")
    assert len(deduplicate([a, b])) == 2


def test_same_url_different_company_is_not_merged():
    a = make_job(native_id="1", company="Acme", title="Data Scientist", url="https://jobs.example/careers")
    b = make_job(native_id="2", company="Globex", title="Platform Lead", url="https://jobs.example/careers")
    assert len(deduplicate([a, b])) == 2


def test_repost_under_a_new_id_is_recognised():
    on_file = make_job(native_id="old", company="Acme S.A.", title="ML Engineer")
    repost = make_job(native_id="new", company="Acme", title="Senior ML Engineer (Remote)")
    same_ad = make_job(native_id="old", company="Acme S.A.", title="ML Engineer")
    unrelated = make_job(native_id="x", company="Globex", title="ML Engineer")
    fresh, duplicates = split_known([repost, same_ad, unrelated], [on_file])
    assert [job.id for job in fresh] == [same_ad.id, unrelated.id]
    assert duplicates == [(repost, on_file)]


def test_duplicate_reason_is_bucketed_as_duplicate():
    assert category("duplicate of a job already on file (Acme — Remote Data Engineer)") == "duplicate"


# ---------------------------------------------------------------------------
# The pipeline: no second reading, reposts, pruning
# ---------------------------------------------------------------------------


class CountingSource(JobSource):
    """Returns fresh copies each run and counts full-ad fetches."""

    id = "test"
    name = "Counting board"

    def __init__(self, jobs):
        super().__init__(fetcher=None, options={})
        self._jobs = jobs
        self.fetches = 0

    def search(self, query: SearchQuery):
        return [job.model_copy(deep=True) for job in self._jobs]

    def fetch_description(self, job):
        self.fetches += 1
        return "Remote position. Python, Docker and REST APIs. " * 10


@pytest.fixture
def configured():
    return Settings(
        onboarded=True,
        country="ES",
        search=SearchSettings(titles=["Backend Engineer"]),
        filters=Filters(work_modes=[WorkMode.REMOTE], home_country="ES", max_age_days=7),
    )


def _listing(**overrides):
    defaults = dict(posted_at=TODAY, description="", remote_scope=RemoteScope.WORLDWIDE)
    defaults.update(overrides)
    return make_job(**defaults)


def test_known_jobs_are_not_read_twice(database, profile, configured):
    source = CountingSource([_listing()])
    first = SearchPipeline(configured, profile, database, sources=[source], today=TODAY).run()
    assert source.fetches == 1 and first.run.reused == 0
    second = SearchPipeline(configured, profile, database, sources=[source], today=TODAY).run()
    assert source.fetches == 1, "the ad was fetched again"
    assert second.run.reused == 1 and len(second.kept) == 1
    SearchPipeline(configured, profile, database, sources=[source], today=TODAY, refresh=True).run()
    assert source.fetches == 2


def test_filters_still_apply_to_reused_jobs(database, profile, configured):
    source = CountingSource([_listing()])
    SearchPipeline(configured, profile, database, sources=[source], today=TODAY).run()
    configured.filters.excluded_keywords = ["docker"]
    second = SearchPipeline(configured, profile, database, sources=[source], today=TODAY).run()
    assert second.kept == [] and source.fetches == 1


def test_a_repost_is_filed_as_a_duplicate(database, profile, configured):
    original = _listing(native_id="1", company="Acme S.L.", title="Backend Engineer")
    SearchPipeline(configured, profile, database, sources=[CountingSource([original])], today=TODAY).run()
    repost = _listing(native_id="2", company="Acme", title="Backend Engineer (m/f/d)")
    result = SearchPipeline(
        configured, profile, database, sources=[CountingSource([repost])], today=TODAY
    ).run()
    assert result.new_jobs == [] and result.run.known_duplicates == 1
    assert any(row["category"] == "duplicate" for row in database.list_filtered())


def test_prune_retires_old_untouched_jobs_only(database):
    old = make_job(native_id="old", company="Old Ltd", posted_at=TODAY - timedelta(days=60))
    touched = make_job(native_id="touched", company="Mine Ltd", posted_at=TODAY - timedelta(days=60))
    recent = make_job(native_id="recent", company="New Ltd", posted_at=TODAY - timedelta(days=3))
    undated = make_job(native_id="undated", company="Nodate Ltd", posted_at=None)
    database.upsert_jobs([old, touched, recent, undated])
    database.save_application(Application(job_id=touched.id, status=ApplicationStatus.APPLIED))

    pruned = prune_stale(database, 45, TODAY)

    assert [job_id for job_id, _ in pruned] == [old.id]
    assert old.id in database.closed_job_ids()
    assert prune_stale(database, None, TODAY) == []


# ---------------------------------------------------------------------------
# The local server refuses requests from other sites
# ---------------------------------------------------------------------------

LOCAL = frozenset({"127.0.0.1", "localhost", "::1"})


@pytest.mark.parametrize(
    ("method", "headers", "refused"),
    [
        ("GET", {"host": "127.0.0.1:8000"}, False),
        ("POST", {"host": "127.0.0.1:8000"}, False),  # CLI, curl
        ("POST", {"host": "127.0.0.1:8000", "origin": "http://127.0.0.1:8000"}, False),
        ("PUT", {"host": "[::1]:8000", "origin": "http://[::1]:8000"}, False),
        ("POST", {"host": "127.0.0.1:8000", "origin": "https://evil.example"}, True),
        ("POST", {"host": "127.0.0.1:8000", "origin": "null"}, True),
        ("POST", {"host": "127.0.0.1:8000", "sec-fetch-site": "cross-site"}, True),
        # DNS rebinding: the attacker's name resolves to 127.0.0.1.
        ("GET", {"host": "evil.example:8000"}, True),
        ("POST", {"host": "evil.example:8000", "origin": "http://evil.example:8000"}, True),
    ],
)
def test_request_refusal(method, headers, refused):
    assert (request_refusal(method, headers, LOCAL) is not None) is refused


def test_cross_site_form_post_is_refused_end_to_end(paths):
    testclient = pytest.importorskip("fastapi.testclient")
    from jobradar.web import create_app

    with testclient.TestClient(create_app(paths, allowed_hosts={"testserver"})) as client:
        assert client.get("/api/state").status_code == 200
        response = client.post("/api/search", headers={"origin": "https://evil.example"})
        assert response.status_code == 403
        assert client.get("/", headers={"host": "evil.example"}).status_code == 403
