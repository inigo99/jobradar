"""Per-job tailoring, without a language model."""

from jobradar.config import Settings
from jobradar.documents.tailor import clean_title, defensible_headline, tailor
from jobradar.models import Profile, Requirement
from jobradar.pipeline.scoring import score_job
from tests.conftest import make_job


def test_cleans_board_noise_from_the_title():
    assert clean_title("Senior Backend Engineer (m/f/d) - Remote") == "Senior Backend Engineer"


def test_drops_seniority_the_profile_cannot_support():
    profile = Profile()
    profile.experience = []
    job = make_job(title="Principal Engineer")
    assert "Principal" not in defensible_headline(job, profile)


def test_keeps_seniority_the_profile_supports(profile):
    job = make_job(title="Senior Backend Engineer")
    assert defensible_headline(job, profile).startswith("Senior")


def test_drops_junior_when_the_profile_has_outgrown_it(profile):
    """'Junior' above three years reads as a mistake or an admission."""
    job = make_job(title="Junior Data Scientist")
    assert "Junior" not in defensible_headline(job, profile)


def test_summary_does_not_repeat_the_same_skills_twice(profile, settings):
    from jobradar.documents.tailor import template_summary

    summary = template_summary(profile, make_job(), ["python", "sql", "docker", "aws"], "en")
    assert summary.count("Python") <= 1


def test_bullets_are_reordered_but_never_lost(profile, settings):
    job = make_job(requirements=[Requirement(key="etl", label="ETL", weight=10)])
    result = tailor(profile, job, score_job(job, profile), settings)
    for experience in profile.experience:
        assert sorted(result.bullet_order[experience.id]) == sorted(b.id for b in experience.bullets)


def test_summary_only_uses_material_from_the_profile(profile, settings):
    job = make_job()
    result = tailor(profile, job, score_job(job, profile), Settings())
    from jobradar.documents.validator import validate_document

    assert validate_document(result.summary, profile).ok


def test_positions_are_never_reordered(profile, settings):
    job = make_job()
    result = tailor(profile, job, score_job(job, profile), settings)
    assert list(result.bullet_order) == [e.id for e in profile.experience]
