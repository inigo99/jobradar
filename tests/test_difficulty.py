"""Learning difficulty: a plan for the gaps, never a licence to claim them."""

from __future__ import annotations

from jobradar.models import Requirement
from jobradar.pipeline.scoring import score_job
from jobradar.taxonomy import DIFFICULTIES, difficulty_for, difficulty_note, taxonomy
from tests.conftest import make_job


def test_every_skill_has_a_usable_difficulty():
    assert all(skill.difficulty in DIFFICULTIES for skill in taxonomy().values())


def test_a_library_on_top_of_a_known_base_is_fast():
    assert difficulty_for("fastapi") == "fast"
    assert difficulty_for("docker") == "fast"


def test_a_discipline_or_a_language_is_slow():
    assert difficulty_for("deep_learning") == "slow"
    assert difficulty_for("german") == "slow"


def test_an_unknown_key_falls_back_instead_of_raising():
    assert difficulty_for("nonexistent_skill_key") in DIFFICULTIES
    assert difficulty_note("nonexistent_skill_key")


def test_the_configuration_block_is_not_loaded_as_a_skill():
    assert "_learning_difficulty" not in taxonomy()


def test_gaps_carry_their_difficulty(profile):
    job = make_job(requirements=[
        Requirement(key="python", label="Python", weight=10),
        Requirement(key="deep_learning", label="Deep learning", weight=8),
        Requirement(key="fastapi", label="FastAPI", weight=5),
    ])
    score = score_job(job, profile)
    by_key = {g["key"]: g for g in score.gap_details}
    assert "deep_learning" in by_key
    assert by_key["deep_learning"]["difficulty"] == "slow"
    assert by_key["deep_learning"]["note"]


def test_difficulty_never_changes_what_counts_as_a_gap(profile):
    """The evidence model decides gaps. This only sorts the ones that exist."""
    job = make_job(requirements=[Requirement(key="deep_learning", label="Deep learning", weight=9)])
    score = score_job(job, profile)
    assert score.tailored == 0.0
    assert [g["key"] for g in score.gap_details] == ["deep_learning"]
