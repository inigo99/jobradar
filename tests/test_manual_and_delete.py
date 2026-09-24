"""Adding jobs by hand, deleting jobs with undo, and ads just short on years."""

from __future__ import annotations

import json

import pytest

from jobradar.models import Application, ApplicationStatus, MatchScore
from jobradar.pipeline.filters import check_experience, experience_ceiling
from tests.conftest import SAMPLE_CV, make_job

# ---------------------------------------------------------------------------
# Deleting, in storage
# ---------------------------------------------------------------------------


def test_delete_and_undo_bring_everything_back(database):
    job = make_job(native_id="1", company="Acme Foods")
    database.upsert_jobs([job])
    database.save_application(Application(job_id=job.id, status=ApplicationStatus.APPLIED,
                                          notes="Called on Monday"))
    database.save_score(job.id, MatchScore(tailored=81))

    assert database.delete_jobs([job.id, "no-such-job"]) == 1
    assert database.get_job(job.id) is None
    assert job.id not in database.all_applications()
    assert job.id in database.deleted_job_ids()

    assert database.restore_deleted([job.id]) == 1
    assert database.get_job(job.id) is not None
    assert database.get_application(job.id).notes == "Called on Monday"
    assert database.get_score(job.id).tailored == 81
    assert job.id not in database.deleted_job_ids()


def test_a_deleted_ad_is_not_added_back_by_a_search(database, settings, monkeypatch):
    from jobradar.pipeline.search import SearchPipeline

    job = make_job(native_id="1")
    database.upsert_jobs([job])
    database.delete_jobs([job.id])
    runner = SearchPipeline.__new__(SearchPipeline)
    runner.database, runner.settings = database, settings
    runner.today = job.posted_at
    survivors, rejected, _filtered = runner._prefilter([make_job(native_id="1")])
    assert survivors == [] and rejected[job.id] == "deleted by you"


# ---------------------------------------------------------------------------
# Years: just short versus far off
# ---------------------------------------------------------------------------


def test_just_short_and_far_off_are_told_apart(settings):
    filters = settings.filters
    filters.years_margin = 1
    assert experience_ceiling(filters, 3.0) == 3.0
    assert "just short by 1" in check_experience(make_job(min_years_experience=4), filters, 3.0).reason
    assert "just short" not in check_experience(make_job(min_years_experience=7), filters, 3.0).reason
    assert check_experience(make_job(min_years_experience=3), filters, 3.0) is None


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
                   "default_language": "en", "cv_text": SAMPLE_CV, "titles": ["Data Engineer"],
                   "keywords": [], "filters": {"work_modes": ["remote"], "home_country": "ES"},
                   "company_domains": [], "enabled_sources": [], "cv_template": "classic"}
        assert test_client.post("/api/onboarding",
                                data={"payload": json.dumps(payload)}).status_code == 200
        yield test_client


def test_a_job_added_by_hand_is_read_scored_and_tracked(client):
    response = client.post("/api/jobs", json={
        "title": "Data Analyst", "company": "Local Bakery", "url": "https://bakery.example/jobs/1",
        "description": "We need 2 years of SQL and Python for sales dashboards. ETL a plus.",
        "salary_min": 30000, "salary_max": 34000, "status": "applied", "notes": "Referral from Ana"})
    assert response.status_code == 200, response.text
    job_id = response.json()["id"]
    assert job_id.startswith("manual:") and response.json()["family"] == "data_analytics"

    job = next(j for j in client.get("/api/state").json()["jobs"] if j["id"] == job_id)
    assert job["status"] == "applied" and job["notes"] == "Referral from Ana"
    assert job["applied_on"]  # applying today, unless said otherwise
    assert job["salary_min"] == 30000 and job["salary_origin"] == "published"
    assert job["score_tailored"] > 0


def test_a_forced_family_must_exist(client):
    response = client.post("/api/jobs", json={"title": "Chef", "family": "astronaut"})
    assert response.status_code == 400 and "astronaut" in response.json()["detail"]


def test_bulk_delete_and_undo(client, database):
    jobs = [make_job(native_id=str(i), company=f"Co {i}") for i in range(3)]
    database.upsert_jobs(jobs)
    ids = [j.id for j in jobs[:2]]
    assert client.post("/api/jobs/delete", json={"ids": ids}).json()["deleted"] == 2
    left = {j["id"] for j in client.get("/api/state").json()["jobs"]}
    assert left == {jobs[2].id}
    assert client.post("/api/jobs/undelete", json={"ids": ids}).json()["restored"] == 2
    assert client.post("/api/jobs/delete", json={"ids": []}).status_code == 422


def test_raising_the_years_puts_set_aside_ads_back(client, database):
    job = make_job(native_id="senior", min_years_experience=9)
    database.save_filtered([(job, "asks for 9 years, you have 5 (short by 4)", "experience")])
    state = client.get("/api/state").json()
    entry = next(e for e in state["filtered"] if e["id"] == job.id)
    assert entry["min_years"] == 9 and state["experience"]["held"] is not None

    settings = state["settings"]
    settings["filters"]["max_years_experience"] = 10
    saved = client.put("/api/settings", json={"settings": settings}).json()
    assert saved["restored"] == 1
    assert database.get_job(job.id) is not None
