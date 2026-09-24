"""Per-family CV variants, the built-in PDF writer and letters as PDF."""

from __future__ import annotations

import json

import pytest

from jobradar.documents.pdfwriter import cv_pdf, letter_pdf, text_width, wrap
from jobradar.documents.render import build_context, format_period, render_cv
from jobradar.documents.tailor import apply_variant, auto_extra_skills, owned_skill, tailor
from jobradar.models import CvVariant, Requirement
from jobradar.pipeline.scoring import score_job
from jobradar.profile.importer import _parse_education
from tests.conftest import SAMPLE_CV, make_job


def data_job(**overrides):
    defaults = dict(title="Data Engineer", company="Acme Foods", family="data_analytics",
                    requirements=[Requirement(key="etl", label="ETL", weight=3),
                                  Requirement(key="docker", label="Docker", weight=1)])
    defaults.update(overrides)
    return make_job(**defaults)


# ---------------------------------------------------------------------------
# Variants
# ---------------------------------------------------------------------------


def test_a_variant_leads_hides_and_reorders(profile, settings):
    profile.family_variants["data_analytics"] = CvVariant(
        headline="Data engineer",
        lead_bullets=["backend_engineer-1-2"],
        hidden_bullets=["backend_engineer-1-1"],
        skill_groups=["infrastructure"],
        hidden_skill_groups=["languages"],
    )
    job = data_job()
    tailored = tailor(profile, job, score_job(job, profile), settings)
    assert tailored.headline == "Data engineer"
    assert tailored.bullet_order["backend_engineer-1"][0] == "backend_engineer-1-2"
    assert tailored.skill_order[0] == "infrastructure"

    context = build_context(profile, tailored, job)
    bullets = [b for e in context["experiences"] for b in e["bullets"]]
    assert not any("checkout errors" in b for b in bullets)
    assert not any("Python" in group["items"] for group in context["skill_groups"])


def test_a_variant_for_another_family_changes_nothing(profile, settings):
    profile.family_variants["healthcare"] = CvVariant(headline="Nurse")
    job = data_job()
    assert tailor(profile, job, score_job(job, profile), settings).headline != "Nurse"


def test_extra_skills_must_be_owned(profile):
    assert owned_skill(profile, "Docker")
    assert not owned_skill(profile, "Welding")
    profile.family_variants["data_analytics"] = CvVariant(
        hidden_skill_groups=["infrastructure"], extra_skills=["Welding", "Docker"])
    job = data_job(requirements=[])
    result = apply_variant(tailor_stub(job), profile, job)
    assert result.extra_skills == ["Docker"]


def test_skills_the_ad_asks_for_are_named_when_otherwise_missing(profile):
    job = data_job()
    shown = [item for group in profile.skills for item in group.items]
    extras = auto_extra_skills(profile, job, shown)
    assert "Docker" not in extras  # already in a group shown
    assert extras and extras[0] == profile.label_for("etl")  # heaviest requirement first


def tailor_stub(job):
    from jobradar.documents.tailor import TailoredCV

    return TailoredCV(job_id=job.id, language="en", headline="", summary="")


# ---------------------------------------------------------------------------
# Education and dates
# ---------------------------------------------------------------------------


def test_no_dates_at_all_is_not_present():
    assert format_period("", None, "en") == ""
    assert format_period("2022-03", None, "en") == "Mar 2022 – present"


def test_education_dates_and_notes_join_the_entry_above():
    lines = ["MSc in Data Science — Polytechnic University of Valencia", "2019-09 - 2020-07",
             "Master's thesis: demand forecasting for perishable inventory.",
             "BSc in Computer Engineering — University of Valencia", "2015-09 - 2019-06"]
    first, second = _parse_education(lines, "en")
    assert (first.start, first.end) == ("2019-09", "2020-07")
    assert first.note == {"en": "Master's thesis: demand forecasting for perishable inventory."}
    assert second.institution == {"en": "University of Valencia"}


# ---------------------------------------------------------------------------
# The built-in PDF writer
# ---------------------------------------------------------------------------


def test_wrapping_respects_the_width():
    text = "Cut weekly reporting effort by twelve hours by automating the ETL feeding dashboards."
    lines = wrap(text, 10, False, 150)
    assert len(lines) > 1
    assert all(text_width(line, 10) <= 150 for line in lines)


def test_the_cv_pdf_fits_one_page(profile, settings):
    job = data_job()
    context = build_context(profile, tailor(profile, job, score_job(job, profile), settings), job)
    pdf, pages, _scale = cv_pdf(context, max_pages=1)
    assert pdf.startswith(b"%PDF-1.4") and pdf.rstrip().endswith(b"%%EOF")
    assert pages == 1


def test_the_builtin_engine_needs_no_browser(profile, settings, paths):
    settings.cv_pdf_engine = "builtin"
    job = data_job()
    tailored = tailor(profile, job, score_job(job, profile), settings)
    result = render_cv(profile, tailored, job, paths, settings)
    assert result.pdf_path is not None and result.pdf_path.read_bytes().startswith(b"%PDF")
    assert result.pages == 1


def test_letters_keep_accents_and_the_euro_sign():
    pdf = letter_pdf("Ana Núñez", "ana@example.com", "Acme Foods", "cover_letter", "es",
                     "2026-09-24", "Estimado equipo:\n\nPido 30.000 € brutos.")
    assert pdf.startswith(b"%PDF")
    assert b"\x80" in pdf  # the euro sign in WinAnsi


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


def test_variants_are_saved_and_empty_ones_dropped(client):
    variants = {"data_analytics": {"headline": "Data engineer"}, "healthcare": {}}
    response = client.put("/api/profile", json={"family_variants": variants})
    assert response.status_code == 200, response.text
    saved = client.get("/api/state").json()["profile"]["family_variants"]
    assert list(saved) == ["data_analytics"]
    assert saved["data_analytics"]["headline"] == "Data engineer"


def test_an_edited_letter_downloads_as_pdf(client, database):
    job = data_job()
    database.upsert_jobs([job])
    url = f"/api/jobs/{job.id}/documents/cover_letter"
    assert client.get(url + "/pdf").status_code == 404
    assert client.post(url).status_code == 200
    assert client.put(url, json={"text": "My own words."}).json()["document"]["text"] == \
        "My own words."
    response = client.get(url + "/pdf")
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/pdf"
    assert response.content.startswith(b"%PDF")
    assert "cover-letter-acme_foods" in response.headers["content-disposition"]


def test_a_certification_year_is_printed_once():
    from jobradar.profile import import_profile

    cv = SAMPLE_CV + "\nADDITIONAL TRAINING\n• Certificate in Food Safety — Coursera (2021)\n"
    profile, _notes = import_profile(cv)
    certification = profile.certifications[-1]
    assert (certification.name["en"], certification.issuer, certification.year) == \
        ("Certificate in Food Safety", "Coursera", "2021")
