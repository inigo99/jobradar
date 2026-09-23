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

from ..models import Profile, localized
from ..taxonomy import find_skills, label_for

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
    profile.skill_labels = {key: label_for(key) for key in evidence}
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