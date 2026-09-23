"""Adapting a CV to one job.

What is adapted:

* the headline under the candidate's name;
* the professional summary;
* the order of achievements *within* each position;
* the order of the skill groups.

What is never adapted: the achievements themselves, the positions, the dates,
or their chronological order. Reordering positions to hide a gap or to put the
most relevant employer first is one of the fastest things for a recruiter to
spot, and rewriting an achievement per job is how people end up unable to
answer a question about their own CV.

Both a model-assisted and a deterministic path produce the same
:class:`TailoredCV`, so the renderer, the validator and the linter never need
to know which one ran.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from ..config import Settings
from ..llm import LLMClient
from ..llm.prompts import tailor_cv
from ..models import Job, MatchScore, Profile, localized
from ..taxonomy import find_skills
from .validator import validate_document

#: Seniority words a headline may only keep if the profile supports at least
#: this many years of experience.
SENIORITY_CLAIMS: tuple[tuple[str, float], ...] = (
    ("principal", 10.0),
    ("head of", 8.0),
    ("director", 10.0),
    ("staff", 8.0),
    ("lead", 6.0),
    ("senior", 4.0),
    ("sénior", 4.0),
    ("sr.", 4.0),
)

#: Words a headline must drop once the profile has more than this many years.
#: "Junior Data Scientist" above six years of experience reads as either a
#: mistake or an admission, and a reader treats it as both.
JUNIOR_CLAIMS: tuple[tuple[str, float], ...] = (
    ("junior", 3.0),
    ("jr.", 3.0),
    ("trainee", 2.0),
    ("intern", 2.0),
    ("becario", 2.0),
    ("graduate", 3.0),
    ("entry level", 3.0),
)

#: Noise that job titles carry and CVs should not.
TITLE_NOISE = re.compile(
    r"\((?:m/f/d\vert{}m/w/d\vert{}h/f\vert{}f/m/x\vert{}remote\vert{}hybrid\vert{}[^)]{0,25}\%[^)]*)\)|"
    r"\b(?:remote|100%\s*remote|teletrabajo|full[- ]time|part[- ]time)\b|"
    r"[–—-]\s*(?:remote|madrid|barcelona|berlin|london|spain|españa).*$",
    re.IGNORECASE,
)

#: Summary scaffolding for the deterministic path, per language. Only the
#: connective tissue is templated; every fact slotted in comes from the profile.
SUMMARY_TEMPLATES: dict[str, str] = {
    "en": "{role} with {years} years of professional experience{focus}. {achievement} "
          "Works with {skills}.",
    "es": "{role} con {years} años de experiencia profesional{focus}. {achievement} "
          "Trabaja con {skills}.",
    "fr": "{role} avec {years} ans d'expérience professionnelle{focus}. {achievement} "
          "Travaille avec {skills}.",
    "pt": "{role} com {years} anos de experiência profissional{focus}. {achievement} "
          "Trabalha com {skills}.",
    "de": "{role} mit {years} Jahren Berufserfahrung{focus}. {achievement} "
          "Arbeitet mit {skills}.",
    "it": "{role} con {years} anni di esperienza professionale{focus}. {achievement} "
          "Lavora con {skills}.",
}

FOCUS_TEMPLATES: dict[str, str] = {
    "en": " focused on {focus}",
    "es": " centrada en {focus}",
    "fr": " axée sur {focus}",
    "pt": " focada em {focus}",
    "de": " mit Schwerpunkt {focus}",
    "it": " focalizzata su {focus}",
}


@dataclass
class TailoredCV:
    """The per-job adaptation, ready to render."""

    job_id: str
    language: str
    headline: str
    summary: str
    #: experience id -> ordered bullet ids
    bullet_order: dict[str, list[str]] = field(default_factory=dict)
    #: skill group keys, most relevant first
    skill_order: list[str] = field(default_factory=list)
    surfaced: list[str] = field(default_factory=list)
    generated_by: str = "rules"
    #: Populated when the validator rejected a model draft.
    validation_notes: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Deterministic building blocks
# ---------------------------------------------------------------------------


def clean_title(title: str | None) -> str:
    """Strip the noise job boards add to titles."""
    title_no_tags = re.sub(r"(?i)\([mfdwx/]+\)", "", title or "")
    cleaned = TITLE_NOISE.sub(" ", title_no_tags)
    cleaned = re.sub(r"\s{2,}", " ", cleaned).strip(" -–—|,")
    return " ".join(cleaned.split()[:6])


def defensible_headline(job: Job, profile: Profile) -> str:
    """The job's own title, minus any seniority the profile cannot support.

    Claiming "Senior" with two years of experience is not tailoring, it is the
    first thing that gets the CV binned. So the claim is checked against the
    candidate's actual years and dropped when it does not hold.
    """
    headline = clean_title(job.title) or localized(profile.summary, profile.default_language)[:40]
    years = profile.years_of_experience()

    def drop(word: str) -> None:
        nonlocal headline
        headline = re.sub(rf"(?i)\b{re.escape(word)}\b\.?", "", headline).strip(" -–—")
        headline = re.sub(r"\s{2,}", " ", headline)

    for claim, required_years in SENIORITY_CLAIMS:
        if claim in headline.lower() and years < required_years:
            drop(claim)
    for claim, outgrown_after in JUNIOR_CLAIMS:
        if claim in headline.lower() and years > outgrown_after:
            drop(claim)
    return headline.strip() or clean_title(job.title)


def rank_bullets(profile: Profile, job: Job, surfaced: set[str]) -> dict[str, list[str]]:
    """Order each position's achievements by relevance to this job.

    An achievement earns points for every job requirement it evidences,
    weighted by how much the ad insists, with a bonus for the skills the tailored
    CV is deliberately surfacing. Ties keep the profile's own order, so a CV
    does not reshuffle randomly between two similar jobs.
    """
    weights = {
        requirement.key: requirement.weight
        for requirement in (job.requirements or [])
    }
    order: dict[str, list[str]] = {}
    for experience in profile.experience:
        scored: list[tuple[float, int, str]] = []
        for position, bullet in enumerate(experience.bullets):
            keys = set(bullet.skills)
            for language in {profile.default_language, job.language, "en"}:
                keys |= set(find_skills(localized(bullet.text, language)))
            score = sum(weights.get(key, 0) for key in keys)
            score += sum(2 for key in keys if key in surfaced)
            scored.append((-score, position, bullet.id))
        scored.sort()
        order[experience.id] = [bullet_id for _, _, bullet_id in scored]
    return order


def rank_skill_groups(profile: Profile, job: Job) -> list[str]:
    """Put the skill group that answers this ad first."""
    weights = {
        requirement.key: requirement.weight
        for requirement in (job.requirements or [])
    }
    scored: list[tuple[float, int, str]] = []
    for position, group in enumerate(profile.skills):
        keys = set(find_skills(" , ".join(group.items)))
        score = sum(weights.get(key, 0) for key in keys)
        scored.append((-score, position, group.key))
    scored.sort()
    return [key for _, _, key in scored]


def _best_achievement(profile: Profile, job: Job, language: str) -> str:
    """The single achievement that best answers this ad, verbatim."""
    weights = {
        requirement.key: requirement.weight
        for requirement in (job.requirements or [])
    }
    best_text, best_score = "", -1.0
    for bullet in profile.all_bullets():
        keys = set(bullet.skills) | set(find_skills(localized(bullet.text, language)))
        score = sum(weights.get(key, 0) for key in keys)
        if score > best_score:
            best_score, best_text = score, localized(bullet.text, language)
    return best_text


def template_summary(profile: Profile, job: Job, surfaced: list[str], language: str) -> str:
    """Assemble a summary without a model, from the profile's own material.

    Every substantive clause is either lifted verbatim from the profile or is
    an arithmetic fact about it (years of experience). The template supplies
    grammar, not content.
    """
    existing = localized(profile.summary, language, fallback="")
    achievement = _best_achievement(profile, job, language)
    years = profile.years_of_experience()
    role = defensible_headline(job, profile)

    # The focus clause and the skills clause draw from different slices of the
    # surfaced list, so the sentence does not repeat itself back to the reader.
    focus_keys, skill_keys = surfaced[:2], surfaced[2:7]
    skills = ", ".join(profile.label_for(key) for key in skill_keys)

    if existing and not achievement:
        return existing
    if not skills:
        skills = ", ".join(profile.label_for(key) for key in surfaced[:3])

    template = SUMMARY_TEMPLATES.get(language, SUMMARY_TEMPLATES["en"])
    focus_template = FOCUS_TEMPLATES.get(language, FOCUS_TEMPLATES["en"])
    focus_labels = ", ".join(profile.label_for(key) for key in focus_keys)
    # Nobody writes "6.2 years" on a CV; round once past the first year.
    stated_years = f"{years:g}" if years < 2 else f"{round(years)}"
    summary = template.format(
        role=role,
        years=stated_years,
        focus=focus_template.format(focus=focus_labels) if focus_labels else "",
        achievement=achievement,
        skills=skills or "—",
    )
    return re.sub(r"\s{2,}", " ", summary).strip()


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def _apply_model_draft(draft: dict, base: TailoredCV, profile: Profile) -> None:
    """Merge a model draft into the deterministic result, field by field.

    Each field is taken only if it is well-formed; a model that returns a
    bullet order missing half the achievements silently loses that field
    instead of losing the achievements.
    """
    headline = str(draft.get("headline", "")).strip()
    if 2 <= len(headline) <= 70:
        base.headline = headline

    summary = str(draft.get("summary", "")).strip()
    if 60 <= len(summary) <= 1200:
        base.summary = summary

    order = draft.get("bullet_order")
    if isinstance(order, dict):
        for experience in profile.experience:
            proposed = order.get(experience.id)
            existing = {bullet.id for bullet in experience.bullets}
            if isinstance(proposed, list) and set(map(str, proposed)) == existing:
                base.bullet_order[experience.id] = [str(item) for item in proposed]

    groups = draft.get("skill_group_order")
    if isinstance(groups, list):
        known = {group.key for group in profile.skills}
        proposed = [str(key) for key in groups if str(key) in known]
        if set(proposed) == known:
            base.skill_order = proposed


def tailor(
    profile: Profile,
    job: Job,
    score: MatchScore,
    settings: Settings,
    llm: LLMClient | None = None,
) -> TailoredCV:
    """Produce the per-job adaptation, verified before it is returned.

    The deterministic result is built first and always kept as the fallback. If
    a model is configured it drafts a better headline and summary, and that
    draft is only accepted once the validator confirms it introduces nothing
    the profile does not support.
    """
    language = job.language or settings.default_language
    surfaced = score.surfaced or []
    surfaced_set = set(surfaced)

    result = TailoredCV(
        job_id=job.id,
        language=language,
        headline=defensible_headline(job, profile),
        summary=template_summary(profile, job, surfaced, language),
        bullet_order=rank_bullets(profile, job, surfaced_set),
        skill_order=rank_skill_groups(profile, job),
        surfaced=surfaced,
        generated_by="rules",
    )

    if not (llm and settings.llm.tailor_cv):
        return result

    system, user = tailor_cv(profile, job, surfaced, language)
    draft = llm.complete_json(system, user)
    if not isinstance(draft, dict):
        return result

    candidate = TailoredCV(**{**result.__dict__, "bullet_order": dict(result.bullet_order),
                              "skill_order": list(result.skill_order)})
    _apply_model_draft(draft, candidate, profile)

    report = validate_document(f"{candidate.headline}\n{candidate.summary}", profile, language)
    if report.ok:
        candidate.generated_by = "llm"
        return candidate

    # The draft claimed something the profile does not support. Keep the
    # deterministic version and record why, so the user can see it happened.
    result.validation_notes = [finding.message for finding in report.findings]
    return result