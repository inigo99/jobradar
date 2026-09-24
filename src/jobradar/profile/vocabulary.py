"""Deriving what a profile proves, and what a document may therefore claim.

Two related jobs live here.

**Evidence.** How strongly the CV already demonstrates each skill. A skill
argued for inside an achievement — with a result attached — is worth far more
to a reader than the same word sitting in a comma-separated list, and the
scoring model needs that distinction to mean anything.

**The allowed vocabulary.** The set of terms a generated document is permitted
to use. This is what turns "do not invent anything" from an instruction into a
check: :mod:`jobradar.documents.validator` compares what a document says
against this set and reports whatever is not in it.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from ..models import Profile, SkillGroup, localized
from ..taxonomy import CUSTOM_PREFIX, find_skills, label_for, skill_for_name, use_custom_skills

#: Evidence assigned to a skill demonstrated inside a bullet or the summary.
DEMONSTRATED = 1.0
#: Evidence assigned to a skill that only appears in a skills list.
LISTED = 0.5
#: How far a merely-listed skill may be promoted by tailoring, by default.
#: Deliberately below 1.0: a line item you have never written about is not
#: something you can defend for twenty minutes under questioning.
DEFAULT_CEILING_LIFT = 0.4


def derive_evidence(profile: Profile, languages: tuple[str, ...] = ("en", "es")) -> dict[str, float]:
    """Work out the evidence map from the profile's own contents.

    Called when a profile is imported and whenever the user edits their
    achievements, so the model of what they can prove never drifts away from
    what the CV actually says.
    """
    demonstrated_text: list[str] = []
    listed_text: list[str] = []

    for language in languages:
        demonstrated_text.append(str(localized(profile.summary, language) or ""))
        for experience in (profile.experience or []):
            demonstrated_text.append(str(localized(experience.title, language) or ""))
            for bullet in (experience.bullets or []):
                demonstrated_text.append(str(localized(bullet.text, language) or ""))
        for education in (profile.education or []):
            demonstrated_text.append(str(localized(education.degree, language) or ""))
            demonstrated_text.append(str(localized(education.note, language) or ""))
        for certification in (profile.certifications or []):
            listed_text.append(str(localized(certification.name, language) or ""))
        for group in (profile.skills or []):
            listed_text.append(" , ".join(group.items or []))

    evidence: dict[str, float] = {}
    for key in find_skills("\n".join(t for t in listed_text if t)):
        evidence[key] = LISTED
    for key in find_skills("\n".join(t for t in demonstrated_text if t)):
        evidence[key] = DEMONSTRATED

    # Bullets may declare their skills explicitly; an explicit tag always wins
    # over keyword detection, because the candidate knows what a bullet proves.
    for bullet in profile.all_bullets():
        for key in (bullet.skills or []):
            evidence[key] = DEMONSTRATED

    for language_skill in (profile.languages or []):
        label_val = localized(language_skill.name, "en") or ""
        key = label_val.strip().lower()
        for detected in find_skills(key):
            evidence[detected] = DEMONSTRATED

    for removed in profile.removed_skills:
        evidence.pop(removed, None)
    return evidence


def suggest_ceilings(evidence: dict[str, float]) -> dict[str, float]:
    """Propose a defensible ceiling for each skill.

    A suggestion, not a verdict: the user should review these in the dashboard,
    because only they know which of their listed tools they could survive a
    technical interview on. A ceiling is never below the evidence, and a skill
    with no evidence gets no ceiling at all — that is the lock.
    """
    ceilings: dict[str, float] = {}
    for key, value in (evidence or {}).items():
        if value <= 0.0:
            continue
        ceilings[key] = round(min(1.0, value + (DEFAULT_CEILING_LIFT if value < 1.0 else 0.0)), 2)
    return ceilings


def refresh(profile: Profile) -> Profile:
    """Recompute evidence, keep any ceilings the user has hand-tuned."""
    evidence = derive_evidence(profile)
    suggested = suggest_ceilings(evidence)
    for key, value in (profile.ceiling or {}).items():
        if key in evidence:  # keep the user's judgement where it still applies
            suggested[key] = max(evidence[key], min(1.0, value))
    profile.evidence = evidence
    profile.ceiling = suggested
    profile.skill_labels = {key: profile.skill_labels.get(key) or label_for(key)
                            if key in profile.custom_skills else label_for(key)
                            for key in evidence}
    return profile


def merge_model_judgement(profile: Profile, evidence: dict[str, float],
                          ceiling: dict[str, float]) -> Profile:
    """Derive the evidence from the text, then let a model's reading refine it.

    The derived map decides *which* skills exist: only taxonomy keys the CV
    actually mentions. A model's number replaces the derived one for those
    keys — it can tell a skill used in production from one named in passing —
    but a key the derivation does not know (a made-up or misspelled one) is
    dropped, because nothing downstream could ever match it.
    """
    refresh(profile)
    for key, value in evidence.items():
        if key in profile.evidence:
            profile.evidence[key] = max(0.0, min(1.0, float(value)))
    for key, value in ceiling.items():
        if key in profile.evidence:
            profile.ceiling[key] = max(profile.evidence[key], min(1.0, float(value)))
    for key, base in profile.evidence.items():
        profile.ceiling[key] = max(base, profile.ceiling.get(key, base))
    return profile


def allowed_terms(profile: Profile) -> set[str]:
    """Every skill key a generated document may legitimately mention.

    Anything outside this set in a generated CV is, by definition, something
    the candidate's profile does not support.
    """
    return {key for key, value in (profile.evidence or {}).items() if value > 0.0}


def profile_text(profile: Profile, languages: tuple[str, ...] = ("en", "es")) -> str:
    """Everything the profile says, as one blob — the validator's haystack."""
    chunks: list[str] = []
    for language in languages:
        chunks.append(str(localized(profile.summary, language) or ""))
        contact = profile.contact
        if contact:
            chunks.append(str(contact.name_for(language) or ""))
        for experience in (profile.experience or []):
            chunks.append(str(localized(experience.title, language) or ""))
            chunks.append(str(experience.organization or ""))
            chunks.append(str(localized(experience.location, language) or ""))
            chunks.append(f"{experience.start or ''} {experience.end or ''}")
            chunks.extend(str(localized(bullet.text, language) or "") for bullet in (experience.bullets or []))
        for education in (profile.education or []):
            chunks.append(str(localized(education.degree, language) or ""))
            chunks.append(str(localized(education.institution, language) or ""))
            chunks.append(str(localized(education.note, language) or ""))
            chunks.append(f"{education.start or ''} {education.end or ''}")
        for certification in (profile.certifications or []):
            chunks.append(f"{localized(certification.name, language) or ''} {certification.issuer or ''} {certification.year or ''}")
        for group in (profile.skills or []):
            chunks.append(" ".join(group.items or []))
        for language_skill in (profile.languages or []):
            chunks.append(f"{localized(language_skill.name, language) or ''} {language_skill.level or ''}")
    return "\n".join(chunk for chunk in chunks if chunk and chunk.strip())


# ---------------------------------------------------------------------------
# Editing the skills by hand (Settings)
# ---------------------------------------------------------------------------


def activate_custom_skills(profile: Profile) -> None:
    """Register the profile's own skills with the taxonomy (see ``Profile.custom_skills``)."""
    use_custom_skills(profile.custom_skills, profile.skill_labels)


def custom_key(name: str) -> str:
    """The key of a user-added skill: ``custom_`` plus a readable slug."""
    slug = re.sub(r"[^a-z0-9]+", "_", name.strip().lower()).strip("_")
    return f"{CUSTOM_PREFIX}{slug or 'skill'}"


@dataclass
class SkillEdit:
    """One row of the skills table in Settings.

    ``key`` is empty for a skill the user just added; it is resolved from
    ``name`` — to a known skill when the taxonomy has one by that name, to a
    new custom skill otherwise.
    """

    name: str
    evidence: float
    ceiling: float
    key: str = ""
    aliases: tuple[str, ...] = ()


def apply_skill_edits(
    profile: Profile,
    groups: list[SkillGroup],
    rows: list[SkillEdit],
    deleted: list[str],
) -> Profile:
    """Apply the Settings skills editor to the profile.

    * ``groups`` replace the listed skills (the CV's "Skills" block);
    * ``rows`` are authoritative for the evidence and ceiling of every skill
      they name, including new ones;
    * ``deleted`` keys, and rows set to evidence 0, are removed and
      remembered, so they are not derived again from the text on the next
      edit or re-import;
    * a skill the new groups mention that no row covers is added with the
      evidence the text gives it, so typing it into a group is enough.
    """
    profile.skills = groups
    for key in deleted:
        if key not in profile.removed_skills:
            profile.removed_skills.append(key)
        profile.custom_skills.pop(key, None)

    wanted: dict[str, tuple[float, float]] = {}
    for row in rows:
        name = row.name.strip()
        if not name and not row.key:
            continue
        key = row.key or skill_for_name(name) or custom_key(name)
        if key.startswith(CUSTOM_PREFIX):
            aliases = [a.strip().lower() for a in row.aliases if a.strip()]
            profile.custom_skills[key] = aliases or profile.custom_skills.get(key, [])
            profile.skill_labels[key] = name or profile.skill_labels.get(key, key)
        if row.evidence <= 0.0:  # "I do not have it" is a deletion
            if key not in profile.removed_skills:
                profile.removed_skills.append(key)
            profile.custom_skills.pop(key, None)
            continue
        if key in profile.removed_skills:  # added back by hand
            profile.removed_skills.remove(key)
        wanted[key] = (max(0.0, min(1.0, row.evidence)), max(0.0, min(1.0, row.ceiling)))
    activate_custom_skills(profile)

    derived = derive_evidence(profile)
    suggested = suggest_ceilings(derived)
    evidence: dict[str, float] = {}
    ceiling: dict[str, float] = {}
    for key, (value, cap) in wanted.items():
        evidence[key] = value
        ceiling[key] = max(value, cap)  # never below what is already proven
    for key, value in derived.items():
        if key not in evidence:
            evidence[key] = value
            if key in suggested:
                ceiling[key] = suggested[key]
    for key in profile.removed_skills:
        evidence.pop(key, None)
        ceiling.pop(key, None)
    profile.evidence = evidence
    profile.ceiling = ceiling
    profile.skill_labels = {
        key: (profile.skill_labels.get(key) if key in profile.custom_skills else None)
        or label_for(key) for key in profile.evidence}
    return profile


def carry_over(old: Profile, new: Profile) -> Profile:
    """Keep the user's own choices when a new CV replaces the profile.

    The CV's facts come from the new file; what the user decided about them
    — skills added or deleted by hand, tuned ceilings, CV variants per job
    family — carries over wherever it still applies.
    """
    new.custom_skills = dict(old.custom_skills)
    new.removed_skills = list(old.removed_skills)
    new.family_variants = dict(old.family_variants)
    for key in old.custom_skills:
        if key in old.skill_labels:
            new.skill_labels[key] = old.skill_labels[key]
    activate_custom_skills(new)
    refresh(new)
    for key, value in old.evidence.items():
        if key in old.custom_skills and key not in new.evidence:
            new.evidence[key] = value  # a skill only the user knew about
            new.skill_labels[key] = old.skill_labels.get(key, key)
    for key, value in old.ceiling.items():
        if key in new.evidence:
            new.ceiling[key] = max(new.evidence[key], value)
    return new
