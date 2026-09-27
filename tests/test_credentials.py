"""Keys for the credentials sources, saved from Settings.

They go to ``<home>/.env`` — owner-readable only, never the database — and the
page is only told whether a source is configured, never the key.
"""

from __future__ import annotations

import os
import stat
import sys

import pytest

from jobradar.config import save_env_values
from jobradar.errors import ConfigError
from jobradar.web import create_app

pytest.importorskip("fastapi.testclient")

KEYS = ("JOOBLE_API_KEY", "ADZUNA_APP_ID", "ADZUNA_APP_KEY")


@pytest.fixture(autouse=True)
def no_keys(monkeypatch):
    for name in KEYS:
        monkeypatch.delenv(name, raising=False)
    yield
    for name in KEYS:  # set by the code under test, not by monkeypatch
        os.environ.pop(name, None)


@pytest.fixture
def client(paths):
    from fastapi.testclient import TestClient

    with TestClient(create_app(paths, allowed_hosts={"testserver"})) as test_client:
        yield test_client


def _sources(client) -> dict:
    return {s["id"]: s for s in client.get("/api/state").json()["sources"]}


def test_save_env_values_keeps_other_lines_and_removes_on_empty(tmp_path):
    env = tmp_path / ".env"
    env.write_text("# my keys\nOTHER=1\nJOOBLE_API_KEY=old\n", encoding="utf-8")
    save_env_values(env, {"JOOBLE_API_KEY": "new", "ADZUNA_APP_ID": "abc"})
    assert env.read_text(encoding="utf-8").splitlines() == [
        "# my keys", "OTHER=1", "JOOBLE_API_KEY=new", "ADZUNA_APP_ID=abc"]
    assert os.environ["JOOBLE_API_KEY"] == "new"
    save_env_values(env, {"JOOBLE_API_KEY": ""})
    assert "JOOBLE_API_KEY" not in env.read_text(encoding="utf-8")
    assert "JOOBLE_API_KEY" not in os.environ
    if sys.platform != "win32":
        assert stat.S_IMODE(env.stat().st_mode) == 0o600


@pytest.mark.parametrize("values", [
    {"JOOBLE_API_KEY": "abc\nEVIL=1"},
    {"JOOBLE_API_KEY": 'abc"'},
    {"lower-case": "abc"},
])
def test_save_env_values_refuses_what_is_not_a_key(tmp_path, values):
    with pytest.raises(ConfigError):
        save_env_values(tmp_path / ".env", values)
    assert not (tmp_path / ".env").exists()


def test_a_source_without_its_key_says_so_and_where_to_get_one(client):
    jooble = _sources(client)["jooble"]
    assert jooble["configured"] is False
    assert jooble["key_url"].startswith("https://")


def test_saving_a_key_turns_the_source_on_without_sending_it_back(client, paths):
    response = client.put("/api/credentials/jooble", json={"values": {"JOOBLE_API_KEY": "s3cret"}})
    assert response.status_code == 200 and response.json()["configured"] is True
    assert "JOOBLE_API_KEY=s3cret" in paths.env_file.read_text(encoding="utf-8")
    state = client.get("/api/state")
    assert _sources(client)["jooble"]["configured"] is True
    assert "s3cret" not in state.text


def test_adzuna_needs_both_values(client):
    first = client.put("/api/credentials/adzuna", json={"values": {"ADZUNA_APP_ID": "id"}})
    assert first.json()["configured"] is False
    second = client.put("/api/credentials/adzuna", json={"values": {"ADZUNA_APP_KEY": "key"}})
    assert second.json()["configured"] is True


def test_only_the_sources_own_names_are_accepted(client, paths):
    wrong = client.put("/api/credentials/jooble", json={"values": {"ADZUNA_APP_ID": "x"}})
    assert wrong.status_code == 400
    missing = client.put("/api/credentials/remoteok", json={"values": {"X": "y"}})
    assert missing.status_code == 404
    assert not paths.env_file.exists()


def test_saved_keys_are_loaded_on_the_next_start(paths):
    from fastapi.testclient import TestClient

    paths.ensure()
    paths.env_file.write_text("JOOBLE_API_KEY=from-file\n", encoding="utf-8")
    with TestClient(create_app(paths, allowed_hosts={"testserver"})) as client:
        assert _sources(client)["jooble"]["configured"] is True
