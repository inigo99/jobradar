"""The Spanish interface: every string the dashboard shows has a translation."""

from __future__ import annotations

import html
import json
import re
import subprocess
from pathlib import Path

import pytest

from jobradar.i18n import normalise_language, translate

WEB = Path(__file__).resolve().parents[1] / "src" / "jobradar" / "web"
STRING = r'"((?:[^"\\\n]|\\.)*)"'


def _unescape(literal: str) -> str:
    return json.loads(f'"{literal}"')


def interface_strings() -> set[str]:
    """Every English string passed to t() or tn() in the scripts, or marked in the page."""
    found: set[str] = set()
    for script in (WEB / "static").glob("dashboard-*.js"):
        if script.name.startswith("dashboard-i18n"):
            continue
        text = script.read_text(encoding="utf-8")
        found |= {_unescape(m) for m in re.findall(r"\bt\(\s*" + STRING, text)}
        for one, many in re.findall(r"\btn\([^,]+,\s*" + STRING + r",\s*" + STRING, text):
            found |= {_unescape(one), _unescape(many)}
    page = (WEB / "templates" / "dashboard.html").read_text(encoding="utf-8")
    found |= {html.unescape(m.strip()) for m in re.findall(r"data-i18n>([^<]+)<", page)}
    found |= {html.unescape(m) for m in re.findall(r'data-i18n-[\w-]+="([^"]+)"', page)}
    return found


def spanish_catalogue() -> dict[str, str]:
    """The Spanish catalogue, read by running the file in Node."""
    source = (WEB / "static" / "dashboard-i18n-es.js").read_text(encoding="utf-8")
    script = "const I18N = {};\n" + source + "\nprocess.stdout.write(JSON.stringify(I18N.es));"
    try:
        result = subprocess.run(["node", "-e", script], capture_output=True, text=True, check=True)
    except FileNotFoundError:
        pytest.skip("Node.js is needed to read the dashboard's catalogue")
    return json.loads(result.stdout)


def test_every_interface_string_has_a_spanish_translation():
    catalogue = spanish_catalogue()
    missing = sorted(s for s in interface_strings() if s not in catalogue)
    assert not missing, "Add these to dashboard-i18n-es.js:\n" + "\n".join(missing)


def test_the_catalogue_carries_no_dead_strings():
    unused = sorted(set(spanish_catalogue()) - interface_strings())
    assert not unused, "No longer used; remove from dashboard-i18n-es.js:\n" + "\n".join(unused)


def test_placeholders_survive_translation():
    for english, spanish in spanish_catalogue().items():
        assert set(re.findall(r"\{\w+\}", english)) == set(re.findall(r"\{\w+\}", spanish)), english


def test_server_text_follows_the_requested_language():
    assert normalise_language("es-ES,es;q=0.9") == "es"
    assert normalise_language("fr") == "en"
    reason = "asks for 5 years, you have 3 — just short by 2"
    assert translate(reason, "en") == reason
    assert translate(reason, "es") == "pide 5 años y tienes 3: te faltan 2"
    assert translate("Nothing the catalogue knows.", "es") == "Nothing the catalogue knows."


# ---------------------------------------------------------------------------
# Through the dashboard API
# ---------------------------------------------------------------------------


@pytest.fixture
def client(paths, database):
    pytest.importorskip("fastapi.testclient")
    from fastapi.testclient import TestClient

    from jobradar.demo import load_demo
    from jobradar.web import create_app

    load_demo(database, paths, "nurse")
    with TestClient(create_app(paths, allowed_hosts={"testserver"})) as test_client:
        yield test_client


SPANISH = {"x-jobradar-language": "es"}


def test_the_board_comes_back_in_spanish(client, database):
    from tests.conftest import make_job

    database.save_filtered([(make_job(native_id="far", min_years_experience=12),
                             "asks for 12 years, you have 7.2 (short by 4.8)", "experience")])
    english = client.get("/api/state").json()
    spanish = client.get("/api/state", headers=SPANISH).json()

    job = next(j for j in spanish["jobs"] if j["salary_origin"] == "estimated")
    assert "El salario es una estimación, no una cifra publicada." in job["alerts"]
    assert job["family_label"] == "Sanidad"
    assert spanish["filtered"][0]["reason"] == "pide 12 años y tienes 7.2 (te faltan 4.8)"
    assert "por corregir" in spanish["profile"]["lint"]["summary"]
    labels = {s["key"]: s["label"] for s in spanish["profile"]["skills"]}
    assert labels["critical_care"] == "Cuidados intensivos / UCI"
    # English is untouched without the header.
    assert next(j for j in english["jobs"] if j["id"] == job["id"])["family_label"] == "Healthcare"


def test_errors_come_back_in_spanish(client):
    response = client.get("/api/jobs/nope/answers", headers=SPANISH)
    assert response.status_code == 404
    assert response.json()["detail"] == "Esa oferta ya no está en el tablero; recarga la página."


def test_family_names_are_not_saved_as_renames(client):
    """The Settings editor gets translated names; saving them must not store overrides."""
    state = client.get("/api/state", headers=SPANISH).json()
    row = next(f for f in state["families"] if f["key"] == "healthcare")
    assert row["label"] == row["default"]["label"] == "Sanidad"
