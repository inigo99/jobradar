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
        demonstrated_text.append(localized(profile.summary, language))
        for experience in profile.experience:
            demonstrated_text.append(localized(experience.title, language))
            for bullet in experience.bullets:
                demonstrated_text.append(localized(bullet.text, language))
        for education in profile.education:
            demonstrated_text.append(localized(education.degree, language))
            demonstrated_text.append(localized(education.note, language))
        for certification in profile.certifications:
            listed_text.append(localized(certification.name, language))
        for group in profile.skills:
            listed_text.append(" , ".join(group.items))

    evidence: dict[str, float] = {}
    for key in find_skills("\n".join(listed_text)):
        evidence[key] = LISTED
    for key in find_skills("\n".join(demonstrated_text)):
        evidence[key] = DEMONSTRATED

    # Bullets may declare their skills explicitly; an explicit tag always wins
    # over keyword detection, because the candidate knows what a bullet proves.
    for bullet in profile.all_bullets():
        for key in bullet.skills:
            evidence[key] = DEMONSTRATED

    for language_skill in profile.languages:
        key = localized(language_skill.name, "en").strip().lower()
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
    for key, value in evidence.items():
        if value <= 0.0:
            continue
        ceilings[key] = round(min(1.0, value + (DEFAULT_CEILING_LIFT if value < 1.0 else 0.0)), 2)
    return ceilings


def refresh(profile: Profile) -> Profile:
    """Recompute evidence, keep any ceilings the user has hand-tuned."""
    evidence = derive_evidence(profile)
    suggested = suggest_ceilings(evidence)
    for key, value in profile.ceiling.items():
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
    return {key for key, value in profile.evidence.items() if value > 0.0}


def profile_text(profile: Profile, languages: tuple[str, ...] = ("en", "es")) -> str:
    """Everything the profile says, as one blob — the validator's haystack."""
    chunks: list[str] = []
    for language in languages:
        chunks.append(localized(profile.summary, language))
        chunks.append(profile.contact.name_for(language))
        for experience in profile.experience:
            chunks.append(localized(experience.title, language))
            chunks.append(experience.organization)
            chunks.append(localized(experience.location, language))
            chunks.append(f"{experience.start} {experience.end or ''}")
            chunks.extend(localized(bullet.text, language) for bullet in experience.bullets)
        for education in profile.education:
            chunks.append(localized(education.degree, language))
            chunks.append(localized(education.institution, language))
            chunks.append(localized(education.note, language))
            chunks.append(f"{education.start} {education.end}")
        for certification in profile.certifications:
            chunks.append(f"{localized(certification.name, language)} {certification.issuer} {certification.year}")
        for group in profile.skills:
            chunks.append(" ".join(group.items))
        for language_skill in profile.languages:
            chunks.append(f"{localized(language_skill.name, language)} {language_skill.level}")
    return "\n".join(chunk for chunk in chunks if chunk)
