"""The anti-fabrication check — the part that has to be right."""

from jobradar.documents.validator import validate_document
from jobradar.models import Profile


def build_profile() -> Profile:
    profile = Profile()
    profile.evidence = {"python": 1.0, "sql": 0.5}
    profile.ceiling = {"python": 1.0, "sql": 0.9}
    profile.summary = {"en": "Engineer who cut checkout errors by 47%."}
    return profile


def test_accepts_a_faithful_document():
    report = validate_document("Engineer who cut checkout errors by 47% using Python.", build_profile())
    assert report.ok


def test_rejects_an_invented_technology():
    report = validate_document("Kubernetes specialist.", build_profile())
    assert not report.ok
    assert any(f.rule == "invented-skill" for f in report.findings)


def test_rejects_an_invented_figure():
    """Rounding 47% up to 60% is the classic quiet fabrication."""
    report = validate_document("Cut checkout errors by 60%.", build_profile())
    assert not report.ok
    assert any(f.rule == "invented-figure" for f in report.findings)


def test_rejects_inflated_seniority():
    profile = build_profile()
    report = validate_document("Engineer with 15 years of experience.", profile)
    assert any(f.rule == "inflated-seniority" for f in report.findings)


def test_letters_may_quote_the_advertisement():
    """Numbers from the ad are legitimate in a cover letter, so they are allowed."""
    report = validate_document("Your ad mentions a team of 40 engineers.", build_profile(),
                               strict_numbers=False)
    assert report.ok
