"""Nineteen graduate profiles, from law to electrician: what JobRadar reads
from each CV, and how a typical junior ad for that profession comes out.

The CVs and ads are in ``fixtures/graduates/``; ``benchmark.py`` runs the same
profiles against real boards. Here everything is offline: these tests catch a
change that leaves one profession behind — a heading not recognised, a skill
the vocabulary does not know, a family an ad is not sorted into.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest
import yaml

from jobradar.config import Filters, Settings
from jobradar.lint import lint_profile
from jobradar.lint.rules import Severity
from jobradar.models import Job
from jobradar.pipeline.enrich import enrich_job
from jobradar.pipeline.filters import apply_filters
from jobradar.pipeline.scoring import score_job
from jobradar.profile import import_profile
from jobradar.textutils import title_matches

ROOT = Path(__file__).resolve().parent.parent
BENCHMARKS = ROOT / "tests" / "fixtures" / "graduates"
PROFILES = yaml.safe_load((BENCHMARKS / "profiles.yaml").read_text(encoding="utf-8"))


@pytest.fixture(scope="module", params=sorted(PROFILES))
def graduate(request):
    key = request.param
    cv = BENCHMARKS / "profiles" / f"{key}.txt"
    profile, _notes = import_profile(cv)
    return key, PROFILES[key], profile, cv.read_text(encoding="utf-8")


def _ad(spec: dict, key: str) -> Job:
    job = Job(source="benchmark", native_id=key, title=spec["ad"]["title"],
              description=spec["ad"]["description"], location="Madrid, Spain", country="ES",
              posted_at=date.today()).ensure_id()
    enrich_job(job, Settings())
    return job


def test_the_cv_is_read_whole(graduate):
    key, spec, profile, text = graduate
    assert profile.default_language == "es", key
    assert profile.contact.email and profile.education, key
    assert profile.languages, key
    if "PRÁCTICAS" in text:  # an internship is a position, not a line of education
        assert profile.experience and profile.experience[0].bullets, key
        assert all(e.title.get("es") for e in profile.experience), key


def test_the_skills_of_the_field_are_recognised(graduate):
    key, spec, profile, _ = graduate
    missing = [skill for skill in spec["skills"] if profile.evidence.get(skill, 0) < 0.5]
    assert not missing, f"{key}: the CV proves {missing} but they were not read"


def test_a_graduate_cv_has_no_red_flag_for_being_new(graduate):
    key, _, profile, _ = graduate
    errors = [f.rule for f in lint_profile(profile).findings if f.severity == Severity.ERROR]
    assert not errors, f"{key}: {errors}"


def test_a_typical_junior_ad_is_sorted_scored_and_kept(graduate):
    key, spec, profile, _ = graduate
    job = _ad(spec, key)
    assert job.family == spec["family"], f"{key}: sorted as {job.family}"
    score = score_job(job, profile)
    assert score.tailored >= spec["min_score"], f"{key}: {score.tailored} (gaps {score.gaps})"
    years = profile.years_of_experience() if hasattr(profile, "years_of_experience") else 0
    assert apply_filters(job, Filters(), profile_years=years).keep, key


@pytest.mark.parametrize("key", sorted(PROFILES))
def test_the_titles_find_real_ads_and_not_their_lookalikes(key):
    """The titles a profile searches must find the real ads of its profession.

    This is what made a search find nothing: "abogado junior" and "asesor
    jurídico" did not find "Técnico/a jurídico/a Junior".
    """
    spec = PROFILES[key]
    missed = [title for title in spec["real_titles"] if not title_matches(title, spec["titles"])]
    assert not missed, f"{key}: {spec['titles']} do not find {missed}"
    wrong = [title for title in spec["not_titles"] if title_matches(title, spec["titles"])]
    assert not wrong, f"{key}: {spec['titles']} also find {wrong}"


@pytest.mark.parametrize("key", sorted(PROFILES))
def test_the_english_titles_find_real_european_ads(key):
    """The same for the English titles, with ads seen on EURES across Europe.

    Europe's run showed "CAD technician" bringing mechanical CAD jobs to the
    architect and "support worker" bringing care jobs to the social worker.
    """
    spec = PROFILES[key]
    missed = [title for title in spec["real_titles_en"] if not title_matches(title, spec["titles_en"])]
    assert not missed, f"{key}: {spec['titles_en']} do not find {missed}"
    wrong = [title for title in spec["not_titles_en"] if title_matches(title, spec["titles_en"])]
    assert not wrong, f"{key}: {spec['titles_en']} also find {wrong}"


@pytest.mark.parametrize("guide", ["STARTER_CONFIGS.md", "STARTER_CONFIGS.es.md"])
def test_the_starter_guide_suggests_what_the_profiles_test(guide):
    # Lines wrap inside the backticks; compare with single spaces.
    text = " ".join((ROOT / "docs" / guide).read_text(encoding="utf-8").split())
    for key, spec in PROFILES.items():
        assert f"`{', '.join(spec['titles'])}`" in text, f"{guide}: titles of {key}"
        if guide == "STARTER_CONFIGS.md":  # the English guide gives English titles first
            assert f"`{', '.join(spec['titles_en'])}`" in text, f"{guide}: English titles of {key}"
        for area in spec["areas"]:
            assert f"`{area}`" in text, f"{guide}: area {area} of {key}"
