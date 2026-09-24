"""Editing skills by hand, and the linter rules on the evidence model."""

from __future__ import annotations

import json

import pytest

from jobradar.lint import lint_profile
from jobradar.models import Experience, SkillGroup
from jobradar.profile import import_profile
from jobradar.profile.vocabulary import (
    SkillEdit,
    activate_custom_skills,
    apply_skill_edits,
    carry_over,
)
from jobradar.taxonomy import find_skills, use_custom_skills
from tests.conftest import SAMPLE_CV


@pytest.fixture(autouse=True)
def no_custom_skills_leak():
    """The vocabulary is process-wide; each test starts and ends without custom skills."""
    use_custom_skills({})
    yield
    use_custom_skills({})


def rows_of(profile):
    return [SkillEdit(key=k, name=profile.label_for(k), evidence=v,
                      ceiling=profile.ceiling.get(k, v)) for k, v in profile.evidence.items()]


def rules(profile):
    return {f.rule: f for f in lint_profile(profile).findings}


# ---------------------------------------------------------------------------
# Editing
# ---------------------------------------------------------------------------


def test_a_new_skill_the_taxonomy_lacks_becomes_part_of_the_vocabulary(profile):
    rows = rows_of(profile) + [SkillEdit(name="Sourdough baking", evidence=1.0, ceiling=1.0,
                                         aliases=("masa madre",))]
    apply_skill_edits(profile, profile.skills, rows, [])
    key = "custom_sourdough_baking"
    assert profile.evidence[key] == 1.0 and profile.label_for(key) == "Sourdough baking"
    assert key in find_skills("Experience with masa madre breads is a plus.")


def test_a_known_name_maps_to_the_known_skill(profile):
    apply_skill_edits(profile, profile.skills, rows_of(profile) + [
        SkillEdit(name="Excel", evidence=0.5, ceiling=0.8)], [])
    assert profile.evidence["excel"] == 0.5 and profile.ceiling["excel"] == 0.8


def test_deleting_sticks_even_though_the_cv_mentions_it(profile):
    assert "docker" in profile.evidence
    apply_skill_edits(profile, profile.skills,
                      [r for r in rows_of(profile) if r.key != "docker"], ["docker"])
    assert "docker" not in profile.evidence and "docker" in profile.removed_skills
    apply_skill_edits(profile, profile.skills, rows_of(profile), [])  # a later, unrelated save
    assert "docker" not in profile.evidence


def test_evidence_zero_is_a_deletion(profile):
    rows = [SkillEdit(key=r.key, name=r.name, evidence=0.0 if r.key == "aws" else r.evidence,
                      ceiling=r.ceiling) for r in rows_of(profile)]
    apply_skill_edits(profile, profile.skills, rows, [])
    assert "aws" not in profile.evidence and "aws" not in profile.ceiling


def test_typing_a_skill_into_a_group_is_enough(profile):
    groups = [*profile.skills, SkillGroup(key="office", label={"en": "Office"}, items=["Excel"])]
    apply_skill_edits(profile, groups, rows_of(profile), [])
    assert profile.evidence["excel"] == 0.5  # listed, not demonstrated


def test_a_ceiling_is_never_below_the_evidence(profile):
    rows = [SkillEdit(key="python", name="Python", evidence=1.0, ceiling=0.2)]
    apply_skill_edits(profile, profile.skills, rows, [])
    assert profile.ceiling["python"] == 1.0


def test_a_new_cv_keeps_what_the_user_decided(profile):
    apply_skill_edits(profile, profile.skills,
                      [r for r in rows_of(profile) if r.key != "docker"]
                      + [SkillEdit(name="Sourdough baking", evidence=0.5, ceiling=0.9)],
                      ["docker"])
    profile.ceiling["python"] = 1.0
    new, _notes = import_profile(SAMPLE_CV)
    carry_over(profile, new)
    assert "docker" not in new.evidence
    assert new.evidence["custom_sourdough_baking"] == 0.5
    assert new.ceiling["python"] == 1.0


def test_custom_skills_come_back_with_the_profile(database, profile):
    profile.custom_skills = {"custom_latte_art": ["latte art"]}
    profile.skill_labels["custom_latte_art"] = "Latte art"
    database.save_profile(profile)
    use_custom_skills({})
    assert "custom_latte_art" not in find_skills("Latte art required")
    database.load_profile()
    assert "custom_latte_art" in find_skills("Latte art required")


# ---------------------------------------------------------------------------
# Linter rules on the evidence model
# ---------------------------------------------------------------------------


def test_a_position_without_achievements(profile):
    profile.experience.append(Experience(id="x", title={"en": "Waiter"}, organization="Bar Sol",
                                         start="2019-01", end="2019-06"))
    found = rules(profile)["position-without-achievements"]
    assert "Waiter" in found.message and found.location == "x"


def test_demonstrated_evidence_must_be_shown(profile):
    profile.evidence["kubernetes"] = 1.0
    assert "Kubernetes" in rules(profile)["unproven-evidence"].message
    assert "unproven-evidence" not in rules(import_profile(SAMPLE_CV)[0])


def test_an_impossible_ceiling(profile):
    profile.ceiling["rust"] = 0.8
    assert rules(profile)["impossible-ceiling"].severity.value == "error"
    profile.ceiling.pop("rust")
    profile.ceiling["python"] = 0.1
    assert rules(profile)["impossible-ceiling"].severity.value == "warning"


def test_listed_skills_unknown_to_matching(profile):
    profile.skills.append(SkillGroup(key="x", label={"en": "Other"}, items=["Basket weaving"]))
    assert "Basket weaving" in rules(profile)["unknown-listed-skills"].message
    apply_skill_edits(profile, profile.skills, rows_of(profile) + [
        SkillEdit(name="Basket weaving", evidence=0.5, ceiling=0.5)], [])
    activate_custom_skills(profile)
    assert "unknown-listed-skills" not in rules(profile)


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


def test_the_settings_editor_round_trip(client):
    profile = client.get("/api/state").json()["profile"]
    skills = [s for s in profile["skills"] if s["key"] != "docker"]
    skills.append({"name": "Forklift", "evidence": 1.0, "ceiling": 1.0})
    groups = [*profile["skill_groups"], {"label": "Warehouse", "items": ["Forklift"]}]
    response = client.put("/api/profile/skills",
                          json={"groups": groups, "skills": skills, "deleted": ["docker"]})
    assert response.status_code == 200, response.text
    saved = response.json()["profile"]
    keys = {s["key"] for s in saved["skills"]}
    assert "docker" not in keys
    assert [g["label"] for g in saved["skill_groups"]][-1] == "Warehouse"
    added = next(s for s in saved["skills"] if s["label"].lower() == "forklift")
    assert added["evidence"] == 1.0
