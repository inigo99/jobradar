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
