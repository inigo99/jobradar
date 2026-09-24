"""Every failure a user can cause is reported with a message and a way out.

These tests pin the contract of ``jobradar.errors``: the right exception type
for each situation, a message that names the thing that failed, and — at the
edges — a clean exit code on the command line and a JSON body (never a
traceback) from the dashboard.
"""

from __future__ import annotations

import json
import logging
import sqlite3
import threading

import httpx
import pytest
import respx

from jobradar.cli import main
from jobradar.config import LLMSettings, Paths, Settings
from jobradar.documents.tailor import clean_title
from jobradar.errors import (
    ConfigError,
    ExportError,
    JobRadarError,
    ProfileError,
    StorageError,
)
from jobradar.exporters import export_csv
from jobradar.llm.client import LLMClient, build_client
from jobradar.models import Job, Salary
from jobradar.pipeline.dedupe import deduplicate
from jobradar.profile import import_profile
from jobradar.profile.importer import extract_text
from jobradar.storage import Database
from tests.conftest import make_job

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------


def test_missing_settings_file(tmp_path):
    with pytest.raises(ConfigError, match="does not exist"):
        Settings.from_yaml(tmp_path / "nope.yaml")


def test_settings_file_that_is_not_yaml(tmp_path):
    file = tmp_path / "settings.yaml"
    file.write_text("search:\n  titles: [unclosed\n", encoding="utf-8")
    with pytest.raises(ConfigError, match="not valid YAML .*line"):
        Settings.from_yaml(file)


def test_settings_file_that_is_not_a_mapping(tmp_path):
    file = tmp_path / "settings.yaml"
    file.write_text("- just\n- a list\n", encoding="utf-8")
    with pytest.raises(ConfigError, match="mapping"):
        Settings.from_yaml(file)


def test_settings_file_with_a_bad_value_names_the_field(tmp_path):
    file = tmp_path / "settings.yaml"
    file.write_text("filters:\n  max_age_days: soon\n", encoding="utf-8")
    with pytest.raises(ConfigError, match="filters.max_age_days"):
        Settings.from_yaml(file)


def test_unwritable_data_directory(tmp_path):
    blocker = tmp_path / "file"
    blocker.write_text("not a directory", encoding="utf-8")
    with pytest.raises(StorageError, match="Cannot create the data directory") as caught:
        Paths(home=blocker / "data").ensure()
    assert "JOBRADAR_HOME" in caught.value.hint


# ---------------------------------------------------------------------------
# Importing a CV
# ---------------------------------------------------------------------------


def test_missing_cv_file(tmp_path):
    with pytest.raises(ProfileError, match="does not exist"):
        extract_text(tmp_path / "cv.pdf")


def test_a_cv_path_that_does_not_exist_is_not_read_as_cv_text():
    with pytest.raises(ProfileError, match="does not exist"):
        import_profile("my-cv.pdf")


def test_old_word_format_says_what_to_do(tmp_path):
    file = tmp_path / "cv.doc"
    file.write_bytes(b"\xd0\xcf\x11\xe0 binary")
    with pytest.raises(ProfileError) as caught:
        extract_text(file)
    assert ".docx" in caught.value.hint


def test_binary_file_is_not_read_as_text(tmp_path):
    file = tmp_path / "cv.bin"
    file.write_bytes(b"\x00\x01\x02" * 50)
    with pytest.raises(ProfileError, match="not a text file"):
        extract_text(file)


def test_corrupt_pdf(tmp_path):
    pytest.importorskip("pypdf")
    file = tmp_path / "cv.pdf"
    file.write_bytes(b"this is not a pdf at all")
    with pytest.raises(ProfileError, match="could not be read as a PDF"):
        extract_text(file)


def test_corrupt_docx(tmp_path):
    pytest.importorskip("docx")
    file = tmp_path / "cv.docx"
    file.write_bytes(b"not a zip archive")
    with pytest.raises(ProfileError, match="Word document"):
        extract_text(file)


def test_empty_cv(tmp_path):
    file = tmp_path / "cv.txt"
    file.write_text("   \n", encoding="utf-8")
    with pytest.raises(ProfileError, match="No text"):
        import_profile(file)


# ---------------------------------------------------------------------------
# Storage
# ---------------------------------------------------------------------------


def test_database_path_that_is_a_directory(paths):
    with pytest.raises(StorageError, match="is a directory"):
        Database(paths, path=paths.home)


def test_a_file_that_is_not_a_database(paths):
    bogus = paths.home / "bogus.sqlite3"
    bogus.write_bytes(b"definitely not sqlite" * 100)
    with pytest.raises(StorageError, match="damaged"):
        Database(paths, path=bogus)


def test_corrupt_settings_are_reported_not_crashed_on(database):
    with database.transaction() as cursor:
        cursor.execute("INSERT INTO documents_kv(key, value) VALUES ('settings', '{broken')")
    with pytest.raises(StorageError, match="settings is corrupt"):
        database.load_settings()


def test_invalid_stored_settings_name_the_field(database):
    database._put_doc("settings", {"filters": {"max_age_days": "soon"}})
    with pytest.raises(ConfigError, match="filters.max_age_days") as caught:
        database.load_settings()
    assert "jobradar init" in caught.value.hint


def test_one_corrupt_job_does_not_hide_the_board(database):
    database.upsert_jobs([make_job(native_id="good")])
    with database.transaction() as cursor:
        cursor.execute(
            "INSERT INTO jobs(id, source, native_id, fingerprint, first_seen, last_seen, payload) "
            "VALUES ('test:bad', 'test', 'bad', 'x', '2026-01-01', '2026-01-01', '{oops')"
        )
    assert [job.id for job in database.list_jobs()] == ["test:good"]


def test_close_releases_connections_opened_by_other_threads(database):
    opened: list[sqlite3.Connection] = []
    worker = threading.Thread(target=lambda: opened.append(database._get_conn()))
    worker.start()
    worker.join()
    database.close()
    with pytest.raises(sqlite3.ProgrammingError):
        opened[0].execute("SELECT 1")
    # And the object is still usable afterwards.
    assert database.list_jobs() == []


# ---------------------------------------------------------------------------
# Export
# ---------------------------------------------------------------------------


def test_export_to_a_folder(database, tmp_path):
    with pytest.raises(ExportError, match="is a folder"):
        export_csv(database, tmp_path)


# ---------------------------------------------------------------------------
# Language model
# ---------------------------------------------------------------------------


def test_unknown_provider_is_explained(caplog):
    with caplog.at_level(logging.WARNING):
        assert build_client(LLMSettings(provider="claude", model="x")) is None
    assert "unknown provider 'claude'" in caplog.text


def test_missing_key_names_the_variable(monkeypatch, caplog):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with caplog.at_level(logging.WARNING):
        assert build_client(LLMSettings(provider="anthropic")) is None
    assert "ANTHROPIC_API_KEY is not set" in caplog.text


@respx.mock
def test_a_rejected_key_stops_the_run_from_asking_again(monkeypatch, caplog):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-wrong")
    route = respx.post("https://api.openai.com/v1/chat/completions").mock(
        return_value=httpx.Response(401, json={"error": "bad key"})
    )
    client = LLMClient(LLMSettings(provider="openai"))
    with caplog.at_level(logging.WARNING):
        assert client.complete("system", "user") is None
        assert client.complete("system", "user") is None
    client.close()
    assert route.call_count == 1
    assert "rejected the API key" in caplog.text
    assert not client.usable()


# ---------------------------------------------------------------------------
# Data normalisation (regressions from making fields optional)
# ---------------------------------------------------------------------------


def test_job_turns_missing_fields_into_empty_values():
    job = Job.model_validate({"source": "x", "native_id": 7, "title": None, "company": None,
                              "salary": None, "alerts": None, "requirements": None})
    assert (job.title, job.company, job.native_id) == ("", "", "7")
    assert job.alerts == [] and job.requirements == []
    assert isinstance(job.salary, Salary)


def test_job_normalises_none_on_assignment():
    job = make_job()
    job.description = None  # type: ignore[assignment]
    job.salary = None  # type: ignore[assignment]
    assert job.description == ""
    assert isinstance(job.salary, Salary)


def test_anonymous_ads_with_the_same_title_are_not_merged():
    first = make_job(native_id="1", company="", url="")
    second = make_job(native_id="2", company="", url="")
    assert len(deduplicate([first, second])) == 2


def test_named_duplicates_are_still_merged():
    first = make_job(native_id="1", url="")
    second = make_job(native_id="2", url="")
    assert len(deduplicate([first, second])) == 1


@pytest.mark.parametrize(
    ("title", "expected"),
    [
        ("Data Engineer (Remote)", "Data Engineer"),
        ("Backend Developer (80% remote)", "Backend Developer"),
        ("Engineer (m/f/d)", "Engineer"),
        ("Engineer (f/m/x)", "Engineer"),
        ("Senior Developer - Madrid", "Senior Developer"),
    ],
)
def test_clean_title_strips_board_noise(title, expected):
    assert clean_title(title) == expected


# ---------------------------------------------------------------------------
# The command line
# ---------------------------------------------------------------------------


def test_cli_reports_setup_needed_without_a_traceback(tmp_path, capsys):
    assert main(["--home", str(tmp_path), "tailor"]) == 2
    err = capsys.readouterr().err
    assert "Not set up yet" in err and "jobradar init" in err
    assert "Traceback" not in err


def test_cli_missing_config_file(tmp_path, capsys):
    assert main(["--home", str(tmp_path), "init", "--config", str(tmp_path / "x.yaml")]) == 2
    assert "does not exist" in capsys.readouterr().err


def test_cli_unknown_filtered_id(tmp_path, capsys):
    assert main(["--home", str(tmp_path), "filtered", "--restore", "nope"]) == 2
    assert "not in the filtered list" in capsys.readouterr().err


def test_cli_rejects_a_negative_limit(tmp_path, capsys):
    with pytest.raises(SystemExit) as caught:
        main(["--home", str(tmp_path), "jobs", "--limit", "-3"])
    assert caught.value.code == 2
    assert "must be at least 1" in capsys.readouterr().err


def test_cli_reports_a_bug_as_a_bug(tmp_path, capsys, monkeypatch):
    def explode(_args):
        raise TypeError("boom")

    monkeypatch.setattr("jobradar.cli.cmd_jobs", explode)
    assert main(["--home", str(tmp_path), "jobs"]) == 1
    err = capsys.readouterr().err
    assert "Unexpected error (TypeError): boom" in err
    assert "Traceback" not in err


def test_every_error_carries_a_status_and_exit_code():
    for cls in JobRadarError.__subclasses__():
        error = cls("message", hint="hint")
        assert 400 <= error.status_code < 600
        assert error.exit_code >= 1
        assert error.to_dict() == {"detail": "message", "error": cls.__name__, "hint": "hint"}


# ---------------------------------------------------------------------------
# The dashboard
# ---------------------------------------------------------------------------


@pytest.fixture
def client(paths):
    from fastapi.testclient import TestClient

    from jobradar.web import create_app

    with TestClient(create_app(paths, allowed_hosts={"testserver"}),
                    raise_server_exceptions=False) as test_client:
        yield test_client


def test_upload_cannot_escape_the_uploads_folder(client, paths):
    response = client.post(
        "/api/onboarding",
        data={"payload": json.dumps({"full_name": "Alex", "titles": ["Engineer"]})},
        files={"cv_file": ("../../escaped.txt", b"ALEX MORGAN\nBackend engineer.\n" * 20)},
    )
    assert response.status_code == 200, response.text
    assert (paths.uploads_dir / "escaped.txt").exists()
    assert not (paths.home.parent / "escaped.txt").exists()


def test_unsupported_upload_is_a_400_with_a_hint(client):
    response = client.post(
        "/api/onboarding",
        data={"payload": json.dumps({"full_name": "Alex"})},
        files={"cv_file": ("cv.doc", b"\xd0\xcf\x11\xe0")},
    )
    assert response.status_code == 400
    body = response.json()
    assert body["error"] == "ProfileError" and ".docx" in body["hint"]


def test_malformed_onboarding_payload_is_a_422_sentence(client):
    response = client.post("/api/onboarding", data={"payload": "{not json"})
    assert response.status_code == 422
    assert isinstance(response.json()["detail"], str)


def test_invalid_query_is_a_422_sentence(client):
    response = client.get("/api/state", params={"limit": 0})
    assert response.status_code == 422
    assert response.json()["detail"].startswith("Invalid request")


def test_unexpected_errors_do_not_leak_details(client, monkeypatch):
    def explode(*_args, **_kwargs):
        raise RuntimeError("secret internal path /home/alex/.env")

    monkeypatch.setattr(Database, "all_scores", explode)
    response = client.get("/api/state")
    assert response.status_code == 500
    assert "secret" not in response.text
    assert response.json()["error"] == "InternalError"
