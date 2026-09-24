"""The application funnel and the run history."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from jobradar.families import families_for
from jobradar.insights import MIN_SAMPLE, funnel, history, score_band
from jobradar.models import (
    Application,
    ApplicationStage,
    ApplicationStatus,
    MailKind,
    MailNews,
    MatchScore,
    SearchRun,
)
from tests.conftest import make_job

TODAY = date(2026, 9, 24)


def applied(job_id: str, stage=ApplicationStage.APPLIED, days_ago: int = 10) -> Application:
    return Application(job_id=job_id, status=ApplicationStatus.APPLIED, stage=stage,
                       applied_on=TODAY - timedelta(days=days_ago))


def reply(job_id: str, kind: MailKind, days_ago: int) -> MailNews:
    return MailNews(job_id=job_id, kind=kind,
                    received_at=datetime.combine(TODAY - timedelta(days=days_ago),
                                                 datetime.min.time(), tzinfo=timezone.utc))


def test_only_a_person_moving_counts_as_a_reply():
    jobs = [make_job(native_id=str(i), source="boardA", company=f"Co {i}") for i in range(4)]
    applications = {jobs[0].id: applied(jobs[0].id),
                    jobs[1].id: applied(jobs[1].id),
                    jobs[2].id: applied(jobs[2].id, stage=ApplicationStage.INTERVIEW),
                    jobs[3].id: Application(job_id=jobs[3].id)}  # not applied
    mail = {jobs[0].id: reply(jobs[0].id, MailKind.ACKNOWLEDGEMENT, 9),
            jobs[1].id: reply(jobs[1].id, MailKind.REJECTION, 4)}
    report = funnel(jobs, applications, {}, mail, families_for(None), TODAY)
    total = report.total
    assert (total.applications, total.replies, total.rejections, total.advances) == (3, 2, 1, 1)
    assert total.acknowledged == 1 and total.alive == 2
    assert total.response_rate is None  # 3 applications are not a sample
    assert report.median_days_to_reply == 6.0
    assert [w["id"] for w in report.waiting] == [jobs[0].id]


def test_rates_appear_from_the_minimum_sample():
    jobs = [make_job(native_id=str(i), source="boardA", company=f"Co {i}") for i in range(MIN_SAMPLE)]
    applications = {job.id: applied(job.id) for job in jobs}
    mail = {jobs[0].id: reply(jobs[0].id, MailKind.ADVANCE, 2)}
    report = funnel(jobs, applications, {}, mail, families_for(None), TODAY)
    assert report.by_source["boardA"].response_rate == round(100 / MIN_SAMPLE, 1)


def test_score_bands_are_ordered_and_labelled():
    assert score_band(59.9) == "under 60 %" and score_band(95) == "90 % or more"
    jobs = [make_job(native_id="1"), make_job(native_id="2")]
    scores = {jobs[0].id: MatchScore(tailored=92), jobs[1].id: MatchScore(tailored=40)}
    report = funnel(jobs, {j.id: applied(j.id) for j in jobs}, scores, {}, families_for(None), TODAY)
    assert list(report.by_score) == ["under 60 %", "90 % or more"]


def test_companies_that_never_reply_are_flagged():
    jobs = [make_job(native_id=str(i), company="Big Consulting SL", title=f"Role {i}")
            for i in range(4)]
    applications = {job.id: applied(job.id) for job in jobs[:3]}
    report = funnel(jobs, applications, {}, {}, families_for(None), TODAY)
    assert report.saturated[0]["company"] == "Big Consulting SL"
    assert (report.saturated[0]["on_board"], report.saturated[0]["applied"]) == (4, 3)


def test_history_adds_up_sources_failures_and_filters():
    start = datetime(2026, 9, 20, 8, tzinfo=timezone.utc)
    runs = [
        SearchRun(started_at=start + timedelta(days=1), finished_at=start + timedelta(days=1, minutes=4),
                  fetched=30, after_dedupe=25, known_duplicates=5, kept=12, new=3,
                  by_source={"a": {"fetched": 20, "kept": 10}, "b": {"fetched": 10, "kept": 2}},
                  errors=["b: timed out"], skipped_sources=[{"source": "c", "reason": "weekly"}],
                  filtered_by_category={"salary": 4, "freshness": 2}),
        SearchRun(started_at=start, finished_at=start + timedelta(minutes=6), fetched=10,
                  after_dedupe=10, kept=5, new=5, by_source={"a": {"fetched": 10, "kept": 5}},
                  filtered_by_category={"salary": 1}),
    ]
    summary = history(runs)
    assert summary["runs"] == 2 and summary["since"] == "2026-09-20"
    assert summary["by_source"]["a"] == {"runs": 2, "fetched": 30, "kept": 15, "failed": 0,
                                         "skipped": 0, "kept_share": 50.0}
    assert summary["by_source"]["b"]["failed"] == 1
    assert summary["by_source"]["c"]["skipped"] == 1
    assert summary["filtered_by_category"] == {"salary": 5, "freshness": 2}
    assert summary["duplicate_share"] == 25.0  # (5 in-run + 5 on file) of 40 fetched
    assert summary["median_minutes"] == 5.0
