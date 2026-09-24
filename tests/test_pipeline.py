"""The pipeline end to end, against a fake source and a temporary database."""

from datetime import date, timedelta
from typing import Any, cast

import pytest

from jobradar.config import Filters, SearchSettings, Settings
from jobradar.models import ApplicationStatus, RemoteScope, Salary, SalaryOrigin, WorkMode
from jobradar.pipeline.search import SearchPipeline
from jobradar.pipeline.sweep import sweep_closed
from jobradar.sources.base import JobSource, SearchQuery
from tests.conftest import make_job

TODAY = date(2026, 9, 8)


class FakeSource(JobSource):
    """A source with no network, so the suite is deterministic and offline."""

    id = "test"
    name = "Fake board"

    def __init__(self, jobs, closed=()):
        super().__init__(fetcher=cast(Any, None), options={})
        self._jobs = jobs
        self._closed = set(closed)

    def search(self, query: SearchQuery):
        return list(self._jobs)

    def fetch_description(self, job):
        return job.description or ""

    def check_open(self, job):
        return (job.id not in self._closed), "gone"


@pytest.fixture
def configured():
    return Settings(
        onboarded=True,
        country="ES",
        search=SearchSettings(titles=["Backend Engineer"]),
        filters=Filters(work_modes=[WorkMode.REMOTE], home_country="ES", max_age_days=7,
                        min_salary=30000, salary_currency="EUR"),
    )


def test_run_keeps_filters_and_scores(database, profile, configured):
    # Distinct company/title on purpose: identical ones would (correctly) be
    # collapsed by the deduplicator before any filter saw them.
    keep = make_job(native_id="keep", company="Keeper Ltd", title="Backend Engineer",
                    posted_at=TODAY - timedelta(days=1),
                    remote_scope=RemoteScope.COUNTRY, country="ES")
    stale = make_job(native_id="stale", company="Stale Ltd", title="Platform Engineer",
                     posted_at=TODAY - timedelta(days=40))
    poor = make_job(native_id="poor", company="Underpay Ltd", title="Junior Developer",
                    posted_at=TODAY, remote_scope=RemoteScope.COUNTRY, country="ES",
                    salary=Salary(minimum=12000, maximum=14000, currency="EUR",
                                  origin=SalaryOrigin.PUBLISHED))

    pipeline = SearchPipeline(configured, profile, database,
                              sources=[FakeSource([keep, stale, poor])], today=TODAY)
    result = pipeline.run(enrich=False)

    assert [job.id for job in result.kept] == [keep.id]
    assert result.run.new == 1
    assert result.scores[keep.id].tailored > 0
    assert "stale" in " ".join(result.rejected)
    assert database.get_job(keep.id) is not None


def test_second_run_reports_no_new_jobs(database, profile, configured):
    job = make_job(posted_at=TODAY, remote_scope=RemoteScope.COUNTRY, country="ES")
    source = FakeSource([job])
    first = SearchPipeline(configured, profile, database, sources=[source], today=TODAY).run(enrich=False)
    second = SearchPipeline(configured, profile, database, sources=[source], today=TODAY).run(enrich=False)
    assert first.run.new == 1
    assert second.run.new == 0


def test_a_broken_source_does_not_abort_the_run(database, profile, configured):
    class Broken(FakeSource):
        id = "broken"

        def search(self, query):
            raise RuntimeError("board is down")

    good = make_job(posted_at=TODAY, remote_scope=RemoteScope.COUNTRY, country="ES")
    result = SearchPipeline(configured, profile, database,
                            sources=[Broken([]), FakeSource([good])], today=TODAY).run(enrich=False)
    assert len(result.kept) == 1
    assert result.run.errors


def test_sweep_never_retires_a_job_the_user_has_touched(database, profile, configured, monkeypatch):
    from jobradar.models import Application

    applied = make_job(native_id="applied", posted_at=TODAY,
                       remote_scope=RemoteScope.COUNTRY, country="ES")
    untouched = make_job(native_id="untouched", posted_at=TODAY,
                         remote_scope=RemoteScope.COUNTRY, country="ES")
    database.upsert_jobs([applied, untouched])
    database.save_application(Application(job_id=applied.id, status=ApplicationStatus.APPLIED))
    database.save_settings(configured)

    source = FakeSource([], closed={applied.id, untouched.id})
    monkeypatch.setattr(
        "jobradar.pipeline.sweep.build_sources",
        lambda settings, cache, **_kwargs: ([source], type("F", (), {"close": lambda self: None})()),
    )
    report = sweep_closed(database)

    assert report.skipped_tracked == 1
    assert [job_id for job_id, _, _ in report.closed] == [untouched.id]
    assert database.get_job(applied.id).closed is False


def test_the_run_stores_what_it_rejected(database, profile, configured):
    """A rejection whose job is discarded is a number nobody can argue with."""
    kept = make_job(native_id="keep", company="Northwind", title="Backend Engineer",
                    posted_at=TODAY)
    dropped = make_job(
        native_id="drop", company="Cheapskate", title="Backend Engineer", posted_at=TODAY,
        salary=Salary(minimum=12000, maximum=15000, currency="EUR",
                      origin=SalaryOrigin.PUBLISHED, basis="Published."),
    )
    pipeline = SearchPipeline(configured, profile, database,
                             sources=[FakeSource([kept, dropped])], today=TODAY)
    result = pipeline.run(enrich=False)

    assert [job.id for job in result.kept] == [kept.id]
    stored = database.list_filtered()
    assert [entry["id"] for entry in stored] == [dropped.id]
    assert stored[0]["category"] == "salary"

    # And it can be put back, with the filter still in place.
    assert database.restore_filtered(dropped.id) is not None
    assert database.get_job(dropped.id) is not None


def test_a_job_that_passes_later_leaves_the_filtered_list(database, profile, configured):
    """Raise the ceiling and the ad is not still sitting in the rejected pile."""
    job = make_job(native_id="edge", company="Borderline", title="Backend Engineer",
                   posted_at=TODAY,
                   salary=Salary(minimum=25000, maximum=28000, currency="EUR",
                                 origin=SalaryOrigin.PUBLISHED, basis="Published."))
    strict = SearchPipeline(configured, profile, database,
                            sources=[FakeSource([job])], today=TODAY)
    strict.run(enrich=False)
    assert [e["id"] for e in database.list_filtered()] == [job.id]

    configured.filters.min_salary = 20000
    relaxed = SearchPipeline(configured, profile, database,
                             sources=[FakeSource([job])], today=TODAY)
    relaxed.run(enrich=False)
    assert database.list_filtered() == []
    assert database.get_job(job.id) is not None
