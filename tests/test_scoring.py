"""Scoring, and the lock that stops tailoring from inventing experience."""

from jobradar.models import MatchScore, Profile, Requirement
from jobradar.pipeline.scoring import promoted_prominence, score_job
from tests.conftest import make_job


def build_profile() -> Profile:
    profile = Profile()
    profile.evidence = {"python": 1.0, "docker": 0.5, "aws": 0.5}
    profile.ceiling = {"python": 1.0, "docker": 0.9, "aws": 0.9}
    profile.skill_labels = {"python": "Python", "docker": "Docker", "aws": "AWS"}
    return profile


def test_missing_skill_can_never_be_promoted():
    """The anti-fabrication lock: zero evidence stays zero, whatever we surface."""
    profile = build_profile()
    assert promoted_prominence("kubernetes", profile, {"kubernetes"}) == 0.0


def test_surfacing_lifts_a_listed_skill_to_its_ceiling():
    profile = build_profile()
    assert promoted_prominence("docker", profile, set()) == 0.5
    assert promoted_prominence("docker", profile, {"docker"}) == 0.9


def test_tailored_score_beats_base_but_gaps_remain():
    profile = build_profile()
    job = make_job(requirements=[
        Requirement(key="python", label="Python", weight=10),
        Requirement(key="docker", label="Docker", weight=8),
        Requirement(key="kubernetes", label="Kubernetes", weight=8),
    ])
    score = score_job(job, profile)
    assert score.tailored > score.base
    assert score.tailored < 100  # the Kubernetes gap cannot be tailored away
    assert "Kubernetes" in score.gaps
    assert "docker" in score.surfaced and "kubernetes" not in score.surfaced


def test_job_without_requirements_is_not_scored_rather_than_zero():
    score = score_job(make_job(requirements=[]), build_profile())
    assert score == MatchScore(scored=False) and score.label() == "—"


def test_an_unscored_ad_sits_mid_board_not_at_the_bottom():
    from jobradar.pipeline.focus import UNSCORED_BASE, focus_for

    focus, reason = focus_for(make_job(requirements=[]), MatchScore(scored=False))
    assert focus >= UNSCORED_BASE * 0.25 and "not scored" in reason
    assert focus_for(make_job(requirements=[]), MatchScore())[0] == 0  # a real 0% stays 0


def test_the_digest_reports_unscored_ads_instead_of_dropping_them():
    from jobradar.notify.digest import build_digest

    job = make_job(requirements=[])
    _subject, body = build_digest([job], {job.id: MatchScore(scored=False)}, min_score=60)
    assert job.title in body and "—" in body


def test_scoring_survives_null_evidence():
    profile = Profile()
    # Bypass Pydantic validation
    object.__setattr__(profile, "evidence", None)
    object.__setattr__(profile, "ceiling", None)
    job = make_job()
    score = score_job(job, profile)
    assert score.base == 0.0
