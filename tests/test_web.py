"""The dashboard API."""

import json

import pytest

from jobradar.web import create_app

fastapi_testclient = pytest.importorskip("fastapi.testclient")


@pytest.fixture
def client(paths):
    from fastapi.testclient import TestClient

    with TestClient(create_app(paths, allowed_hosts={"testserver"})) as test_client:
        yield test_client


def test_serves_the_page(client):
    response = client.get("/")
    assert response.status_code == 200
    assert "JobRadar" in response.text


def test_state_on_a_blank_install(client):
    payload = client.get("/api/state").json()
    assert payload["onboarded"] is False
    assert payload["jobs"] == []
    assert any(source["id"] == "remoteok" for source in payload["sources"])


def test_restricted_sources_are_off_by_default(client):
    sources = {s["id"]: s for s in client.get("/api/state").json()["sources"]}
    assert sources["linkedin"]["default_enabled"] is False
    assert sources["linkedin"]["tos_note"]
    assert sources["remoteok"]["default_enabled"] is True
    # The page ticks what the search runs by default: credentials sources too
    # (skipped until their key is set), so saving Settings does not turn them off.
    assert sources["jooble"]["default_enabled"] is True


def test_onboarding_creates_a_profile(client):
    from tests.conftest import SAMPLE_CV

    payload = {
        "full_name": "Alex Morgan",
        "email": "alex.morgan@example.com",
        "country": "ES",
        "default_language": "en",
        "cv_text": SAMPLE_CV,
        "titles": ["Backend Engineer"],
        "keywords": [],
        "filters": {"work_modes": ["remote"], "home_country": "ES", "min_salary": 30000},
        "company_domains": [],
        "enabled_sources": [],
        "cv_template": "classic",
    }
    response = client.post("/api/onboarding", data={"payload": json.dumps(payload)})
    assert response.status_code == 200, response.text
    assert response.json()["profile"]["full_name"] == "Alex Morgan"

    state = client.get("/api/state").json()
    assert state["onboarded"] is True
    assert state["settings"]["search"]["titles"] == ["Backend Engineer"]


def test_search_requires_setup(client):
    assert client.post("/api/search").status_code == 409


def test_application_tracking_round_trip(client, database):
    from tests.conftest import make_job

    job = make_job()
    database.upsert_jobs([job])
    response = client.put(
        f"/api/jobs/{job.id}/application",
        json={"status": "applied", "stage": "interview", "applied_on": "2026-09-01", "notes": "call on Friday"},
    )
    assert response.status_code == 200
    row = next(item for item in client.get("/api/state").json()["jobs"] if item["id"] == job.id)
    assert row["status"] == "applied" and row["stage"] == "interview"


def test_where_groups_jobs_from_the_users_point_of_view():
    from jobradar.config import Filters
    from jobradar.web.app import where_for
    from tests.conftest import make_job

    filters = Filters(home_country="ES", local_areas=["Valencia"])
    assert where_for(make_job(location="Valencia, Spain", country="ES"), filters) == "local"
    assert where_for(make_job(location="Madrid", country="ES"), filters) == "home"
    assert where_for(make_job(location="Berlin", country="DE"), filters) == "abroad"
    assert where_for(make_job(location="Remote", country=""), filters) == "unknown"


def test_a_search_runs_in_the_background_and_can_be_stopped(paths, monkeypatch):
    import threading
    from datetime import datetime, timezone

    from fastapi.testclient import TestClient

    from jobradar.config import Settings
    from jobradar.models import SearchRun
    from jobradar.pipeline.search import SearchProgress, SearchResult
    from jobradar.storage import Database
    from jobradar.web import app as web_app

    database = Database(paths)
    database.save_settings(Settings(onboarded=True))
    database.close()
    reading = threading.Event()

    def fake_search(*, progress, cancel, **_kwargs):
        progress(SearchProgress(sources_total=2, source="Fake board", stage="reading", kept=1))
        reading.set()
        assert cancel.wait(5), "the page's cancel never arrived"
        return SearchResult(run=SearchRun(started_at=datetime.now(timezone.utc), kept=1,
                                          cancelled=True))

    monkeypatch.setattr(web_app, "run_search", fake_search)
    with TestClient(create_app(paths, allowed_hosts={"testserver"})) as client:
        assert client.post("/api/search").json() == {"ok": True, "started": True}
        assert reading.wait(5)
        status = client.get("/api/search").json()
        assert status["running"] is True and status["progress"]["kept"] == 1
        assert client.post("/api/search").status_code == 409  # one search at a time
        assert client.post("/api/search/cancel").json()["ok"] is True
        client.app.state.search["thread"].join(5)
        status = client.get("/api/search").json()
        assert status["running"] is False
        assert status["outcome"]["ok"] is True and status["outcome"]["run"]["cancelled"] is True
        assert client.post("/api/search/cancel").json()["ok"] is False  # nothing to stop


def test_national_boards_follow_the_users_countries(paths):
    from fastapi.testclient import TestClient

    from jobradar.config import Settings
    from jobradar.sources import build_sources
    from jobradar.storage import Database

    database = Database(paths)
    settings = Settings(onboarded=True)
    settings.filters.home_country = "ES"
    database.save_settings(settings)
    database.close()
    with TestClient(create_app(paths, allowed_hosts={"testserver"})) as client:
        sources = {s["id"]: s for s in client.get("/api/state").json()["sources"]}
    assert sources["manfred"]["default_enabled"] and sources["manfred"]["countries"] == ["ES"]
    assert not sources["arbeitsagentur"]["default_enabled"]
    assert not sources["arbeitnow"]["default_enabled"]
    assert not sources["infojobs"]["default_enabled"]  # restricted stays off, Spanish or not
    assert sources["eures"]["default_enabled"] and sources["eures"]["countries"] == []

    settings.filters.home_country = "DE"
    running, fetcher = build_sources(settings, paths.cache_dir)
    fetcher.close()
    ids = {source.id for source in running}
    assert {"arbeitsagentur", "arbeitnow"} <= ids and "manfred" not in ids
