"""An ad's closing date, and the CV's PDF read back the way an ATS reads it."""

from __future__ import annotations

from datetime import date

import pytest

from jobradar.documents.atscheck import ats_warnings
from jobradar.pipeline.enrich import derive_fields
from jobradar.textutils import extract_deadline
from tests.conftest import make_job

POSTED = date(2026, 10, 1)


@pytest.mark.parametrize("text, expected", [
    ("Apply by 15 October 2026.", date(2026, 10, 15)),
    ("Closing date: 2026-10-20", date(2026, 10, 20)),
    ("Applications close on October 30th", date(2026, 10, 30)),
    ("Deadline: 31.12.2026", date(2026, 12, 31)),
    ("Apply before 1 January", date(2027, 1, 1)),
    ("Plazo de presentación hasta el 15 de octubre.", date(2026, 10, 15)),
    ("Fecha límite: 15/10/2026", date(2026, 10, 15)),
    ("Inscripciones hasta el 3 de noviembre de 2026", date(2026, 11, 3)),
])
def test_the_closing_date_is_read(text, expected):
    assert extract_deadline(text, POSTED) == expected


@pytest.mark.parametrize("text", [
    "Jornada de hasta el 50% en remoto.",
    "Founded on 15 October 2020, we have grown fast.",
    "Deadline: 15 October 2019",                 # before the ad was posted
    "Plazo hasta el 2 de septiembre",            # an old ad's text, not next year's date
    "Deadline-driven environment, fast pace.",
])
def test_dates_that_are_not_this_ads_deadline_are_ignored(text):
    assert extract_deadline(text, POSTED) is None


def test_enrichment_sets_the_deadline():
    job = make_job(description="Backend role. Apply by 20 October 2026.", posted_at=POSTED)
    assert derive_fields(job).deadline == date(2026, 10, 20)


def render(profile, tmp_path):
    pytest.importorskip("pypdf")
    from jobradar.config import Paths, Settings
    from jobradar.documents import render_cv, tailor
    from jobradar.documents.render import build_context
    from jobradar.pipeline.scoring import score_job

    settings = Settings(onboarded=True, cv_pdf_engine="builtin")
    job = make_job()
    tailored = tailor(profile, job, score_job(job, profile), settings, None)
    result = render_cv(profile, tailored, job, Paths(home=tmp_path).ensure(), settings)
    return result, build_context(profile, tailored, job)


def test_a_cv_printed_by_jobradar_reads_back_whole(profile, tmp_path):
    result, _context = render(profile, tmp_path)
    assert result.pdf_path is not None and result.warnings == []


def test_what_an_ats_would_miss_is_named(profile, tmp_path):
    result, context = render(profile, tmp_path)
    context = dict(context, name="Somebody Else", contact_line="x@nowhere.example")
    context["experiences"] = [{"title": "Astronaut", "bullets": [
        "Walked on the moon twice with a perfect landing record", "Another one never printed here",
    ]}] + list(context["experiences"])
    warnings = ats_warnings(result.pdf_path, context)
    assert any("does not find your name" in w for w in warnings)
    assert any("does not find your email" in w for w in warnings)
    assert any("“Astronaut”" in w for w in warnings)


def test_a_pdf_without_text_is_an_empty_cv_to_an_ats(tmp_path):
    pypdf = pytest.importorskip("pypdf")
    PdfWriter = pypdf.PdfWriter

    blank = tmp_path / "blank.pdf"
    writer = PdfWriter()
    writer.add_blank_page(width=595, height=842)
    with blank.open("wb") as handle:
        writer.write(handle)
    assert "empty CV" in ats_warnings(blank, {"name": "Alex Morgan"})[0]
