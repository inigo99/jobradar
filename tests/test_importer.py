"""Importing a CV without a language model."""

from jobradar.profile import import_profile
from tests.conftest import SAMPLE_CV


def test_reads_contact_details():
    profile, _ = import_profile(SAMPLE_CV)
    assert profile.contact.full_name == "Alex Morgan"
    assert profile.contact.email == "alex.morgan@example.com"
    assert "linkedin.com/in/alexmorgan" in profile.contact.linkedin


def test_groups_multi_line_position_headers():
    """Title, employer and dates spread over two lines is one position."""
    profile, _ = import_profile(SAMPLE_CV)
    assert [e.organization for e in profile.experience] == ["Northwind Retail", "Cortado Analytics"]
    assert all(e.bullets for e in profile.experience)


def test_does_not_swallow_the_skills_section():
    """'Languages: Python, SQL' is a skills line, not a LANGUAGES heading."""
    profile, _ = import_profile(SAMPLE_CV)
    items = [item for group in profile.skills for item in group.items]
    assert "Python" in items and "Docker" in items


def test_reads_the_location_from_the_contact_line():
    from jobradar.models import localized

    profile, _ = import_profile(SAMPLE_CV)
    assert "Valencia" in localized(profile.contact.city, profile.default_language)


def test_evidence_distinguishes_demonstrated_from_listed():
    profile, _ = import_profile(SAMPLE_CV)
    assert profile.evidence["rest_apis"] == 1.0  # inside an achievement
    assert profile.evidence["docker"] == 0.5     # only in the skills list


def test_ceilings_never_appear_for_absent_skills():
    profile, _ = import_profile(SAMPLE_CV)
    assert "kubernetes" not in profile.ceiling


def test_years_of_experience_merges_overlaps():
    profile, _ = import_profile(SAMPLE_CV)
    assert profile.years_of_experience() > 4
