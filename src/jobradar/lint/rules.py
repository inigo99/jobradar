"""The rules.

Each rule is a small function that takes the profile (and, where relevant, the
per-job tailoring) and yields :class:`~jobradar.models.LintFinding` objects.
They are registered in :data:`PROFILE_RULES` and :data:`TAILORED_RULES`, so
adding a rule is one function and one list entry.

Severity means something specific here:

``error``    A reader will hold this against the candidate. Fix before sending.
``warning``  Weakens the CV; fix if you can.
``info``     Worth knowing, often a matter of taste or of the target market.

Rules that would encode a cultural preference rather than a genuine signal are
deliberately absent. Whether to include a photo, a date of birth or a marital
status varies enormously by country, and a linter that flags a German CV for
following German convention is worse than no linter.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from datetime import date

from ..models import Bullet, LintFinding, Profile, Severity, _parse_month, localized
from ..taxonomy import find_skills, label_for

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Thresholds — all in one place so they are easy to argue with and to tune.
# ---------------------------------------------------------------------------

MAX_GAP_MONTHS = 5
MIN_BULLETS_WITH_METRICS = 0.5
MAX_BULLET_CHARS = 300
MAX_BULLETS_PER_ROLE = 6
MAX_SUMMARY_CHARS = 750
MAX_SKILL_ITEMS = 40
MAX_SKILL_REPEATS = 6
MAX_ACRONYM_SHARE = 0.25

#: Openings that describe duties instead of results. The single most common
#: weakness in real CVs, and the easiest to fix.
DUTY_OPENERS = (
    "responsible for", "in charge of", "worked on", "worked with", "participated in",
    "helped with", "assisted with", "involved in", "duties included", "tasked with",
    "responsable de", "encargado de", "participé en", "participe en", "colaboré en",
    "ayudé a", "trabajé en", "funciones", "chargé de", "verantwortlich für",
)

#: Phrases that say nothing and that every reader has seen ten thousand times.
EMPTY_PHRASES = (
    "results-driven", "results driven", "detail-oriented", "detail oriented",
    "team player", "hard-working", "hard working", "self-motivated", "go-getter",
    "think outside the box", "passionate about technology", "dynamic professional",
    "excellent communication skills", "proven track record", "synergy",
    "orientado a resultados", "trabajador incansable", "jugador de equipo",
    "capacidad de trabajo en equipo", "proactivo y dinámico", "gran comunicador",
    "acostumbrado a trabajar bajo presión",
)

MONTHS_IN_YEAR = 12


@dataclass
class LintResult:
    """Everything the linter found, plus a headline score."""

    findings: list[LintFinding] = field(default_factory=list)

    @property
    def errors(self) -> list[LintFinding]:
        return [f for f in self.findings if f.severity == Severity.ERROR]

    @property
    def warnings(self) -> list[LintFinding]:
        return [f for f in self.findings if f.severity == Severity.WARNING]

    def score(self) -> int:
        """A 0-100 summary. Errors cost 12, warnings 5, notes 1."""
        penalty = sum(
            {Severity.ERROR: 12, Severity.WARNING: 5, Severity.INFO: 1}[f.severity]
            for f in self.findings
        )
        return max(0, 100 - penalty)

    def summary(self) -> str:
        return (
            f"{self.score()}/100 — {len(self.errors)} to fix, "
            f"{len(self.warnings)} worth improving, {len(self.findings)} notes in total"
        )


Rule = Callable[[Profile, str], Iterator[LintFinding]]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def finding(
    rule: str,
    severity: Severity,
    message: str,
    hint: str = "",
    location: str = "",
) -> LintFinding:
    """Positional shorthand for building a finding, to keep the rules readable."""
    return LintFinding(rule=rule, severity=severity, message=message, hint=hint, location=location)



def _bullets(profile: Profile, language: str) -> list[tuple[str, Bullet, str]]:
    return [
        (experience.organization or experience.id, bullet, localized(bullet.text, language))
        for experience in profile.experience
        for bullet in experience.bullets
    ]


def _months_between(earlier: str, later: str) -> int | None:
    start, end = _parse_month(earlier), _parse_month(later)
    if not start or not end:
        return None
    return (end.year - start.year) * MONTHS_IN_YEAR + (end.month - start.month)


# ---------------------------------------------------------------------------
# Rules — structure and history
# ---------------------------------------------------------------------------


def rule_missing_contact(profile: Profile, language: str) -> Iterator[LintFinding]:
    """No way to reach the candidate is a hard stop, and it happens."""
    contact = profile.contact
    if not contact.full_name:
        yield finding("missing-name", Severity.ERROR, "The CV has no name on it.")
    if not contact.email:
        yield finding(
            "missing-email", Severity.ERROR, "No email address.",
            hint="Email is how almost every reply arrives. It has to be there.",
        )
    if contact.email and not (contact.phone or contact.linkedin):
        yield finding(
            "thin-contact", Severity.WARNING, "Only an email address — no phone or LinkedIn.",
            hint="Recruiters routinely call before they write.",
        )


def rule_dates(profile: Profile, language: str) -> Iterator[LintFinding]:
    """Missing dates read as something being hidden, whether or not it is."""
    for experience in profile.experience:
        if not experience.start:
            yield finding(
                "missing-dates", Severity.ERROR,
                f"'{experience.organization or localized(experience.title, language)}' has no start date.",
                hint="An undated position is assumed to be short or to be padding.",
                location=experience.id,
            )


def rule_chronology(profile: Profile, language: str) -> Iterator[LintFinding]:
    """Positions must run newest first; anything else looks like concealment."""
    dated = [
        (experience, start)
        for experience in profile.experience
        if (start := _parse_month(experience.start)) is not None
    ]
    for (first, first_start), (second, second_start) in zip(dated, dated[1:], strict=False):
        if first_start < second_start:
            yield finding(
                "chronology", Severity.ERROR,
                f"'{first.organization}' is listed before '{second.organization}' but started earlier.",
                hint="Reverse-chronological order is what every reader expects. "
                     "Reordering jobs to lead with the most relevant one is spotted immediately.",
                location=first.id,
            )


def rule_gaps(profile: Profile, language: str) -> Iterator[LintFinding]:
    """Unexplained gaps. Explained ones are fine — unexplained ones get asked about."""
    spans = [
        (experience, _parse_month(experience.start), _parse_month(experience.end) if experience.end else None)
        for experience in profile.experience
    ]
    spans = [item for item in spans if item[1]]
    spans.sort(key=lambda item: item[1] or date.min, reverse=True)
    for (newer, newer_start, _), (older, _, older_end) in zip(spans, spans[1:], strict=False):
        if not older_end:
            continue
        assert newer_start is not None
        assert older_end is not None
        gap = (newer_start.year - older_end.year) * MONTHS_IN_YEAR + (newer_start.month - older_end.month)
        if gap > MAX_GAP_MONTHS:
            yield finding(
                "employment-gap", Severity.WARNING,
                f"{gap} months between '{older.organization}' and '{newer.organization}'.",
                hint="Not a problem in itself — an unexplained one is. A one-line entry "
                     "(study, caring, contracting, a deliberate break) closes it.",
                location=newer.id,
            )


# ---------------------------------------------------------------------------
# Rules — how the achievements are written
# ---------------------------------------------------------------------------


def rule_metrics(profile: Profile, language: str) -> Iterator[LintFinding]:
    """XYZ bullets need the Y. A CV of duties without results is invisible."""
    bullets = _bullets(profile, language)
    if not bullets:
        yield finding(
            "no-achievements", Severity.ERROR, "No achievements are listed under any position.",
            hint="A CV without achievements gives a reader nothing to compare.",
        )
        return
    with_numbers = sum(1 for _, _, text in bullets if re.search(r"\d", text))
    share = with_numbers / len(bullets)
    if share < MIN_BULLETS_WITH_METRICS:
        yield finding(
            "few-metrics", Severity.WARNING,
            f"Only {with_numbers} of {len(bullets)} achievements contain a number ({share:.0%}).",
            hint="Aim for half or more. 'Cut processing time by 85%' lands; 'improved "
                 "processing time' does not. Estimates are fine if you can defend them.",
        )


def rule_duty_language(profile: Profile, language: str) -> Iterator[LintFinding]:
    """Duty openings describe the job description, not the person."""
    for organisation, bullet, text in _bullets(profile, language):
        lowered = text.strip().lower()
        opener = next((phrase for phrase in DUTY_OPENERS if lowered.startswith(phrase)), None)
        if opener:
            yield finding(
                "duty-language", Severity.WARNING,
                f"'{organisation}': an achievement starts with '{opener}'.",
                hint="Start with the result and the verb that produced it: "
                     "'Cut X by N% by doing Z'.",
                location=bullet.id,
            )


def rule_bullet_length(profile: Profile, language: str) -> Iterator[LintFinding]:
    for organisation, bullet, text in _bullets(profile, language):
        if len(text) > MAX_BULLET_CHARS:
            yield finding(
                "long-bullet", Severity.WARNING,
                f"'{organisation}': an achievement runs to {len(text)} characters.",
                hint="Two lines is the limit in a scan. Split it or cut the setup.",
                location=bullet.id,
            )


def rule_bullet_count(profile: Profile, language: str) -> Iterator[LintFinding]:
    for experience in profile.experience:
        if len(experience.bullets) > MAX_BULLETS_PER_ROLE:
            yield finding(
                "too-many-bullets", Severity.INFO,
                f"'{experience.organization}' has {len(experience.bullets)} achievements.",
                hint=f"Beyond about {MAX_BULLETS_PER_ROLE} the later ones are not read. "
                     "The tailoring step already orders them, so the weakest are last.",
                location=experience.id,
            )


def rule_tense_consistency(profile: Profile, language: str) -> Iterator[LintFinding]:
    """English CVs mixing '-ing' and past-tense openings inside one role."""
    if language != "en":
        return
    for experience in profile.experience:
        openers = [localized(b.text, language).strip().split(" ")[0].lower() for b in experience.bullets]
        gerunds = sum(1 for word in openers if word.endswith("ing"))
        past = sum(1 for word in openers if word.endswith("ed"))
        if gerunds and past and len(openers) > 2:
            yield finding(
                "mixed-tense", Severity.INFO,
                f"'{experience.organization}' mixes '-ing' and past-tense openings.",
                hint="Pick one and keep it across the whole CV.",
                location=experience.id,
            )


def rule_first_person(profile: Profile, language: str) -> Iterator[LintFinding]:
    if language != "en":
        return
    hits = sum(
        1 for _, _, text in _bullets(profile, language) if re.match(r"^\s*(i|my|me)\b", text, re.I)
    )
    if hits:
        yield finding(
            "first-person", Severity.INFO,
            f"{hits} achievements start with 'I' or 'My'.",
            hint="CV convention drops the pronoun: 'Cut errors by 50%…'.",
        )


# ---------------------------------------------------------------------------
# Rules — the summary and the skills block
# ---------------------------------------------------------------------------


def rule_summary(profile: Profile, language: str) -> Iterator[LintFinding]:
    summary = localized(profile.summary, language)
    if not summary:
        yield finding(
            "no-summary", Severity.WARNING, "There is no professional summary.",
            hint="The first three lines decide whether the rest is read.",
        )
        return
    if len(summary) > MAX_SUMMARY_CHARS:
        yield finding(
            "long-summary", Severity.WARNING,
            f"The summary is {len(summary)} characters.",
            hint="Three to five sentences. Anything longer is skipped.",
        )
    if not re.search(r"\d", summary):
        yield finding(
            "summary-without-evidence", Severity.INFO,
            "The summary contains no concrete figure.",
            hint="One real number in the opening paragraph does more than a paragraph of adjectives.",
        )


def rule_empty_phrases(profile: Profile, language: str) -> Iterator[LintFinding]:
    """Filler that signals a template rather than a person."""
    summary_text = localized(profile.summary, language) or ""
    haystack = " ".join(
        [summary_text] + [text for _, _, text in _bullets(profile, language)]
    ).lower()
    for phrase in EMPTY_PHRASES:
        if phrase in haystack:
            yield finding(
                "empty-phrase", Severity.WARNING,
                f"The CV contains '{phrase}'.",
                hint="Say the thing it is standing in for, or cut it. Everyone claims this; "
                     "nobody is asked to prove it, which is exactly why it carries no weight.",
            )


def rule_skill_stuffing(profile: Profile, language: str) -> Iterator[LintFinding]:
    """Keyword stuffing is obvious to a human and increasingly to an ATS."""
    total_items = sum(len(group.items) for group in profile.skills)
    if total_items > MAX_SKILL_ITEMS:
        yield finding(
            "skill-stuffing", Severity.WARNING,
            f"{total_items} separate skills are listed.",
            hint=f"Past roughly {MAX_SKILL_ITEMS} the list reads as keyword stuffing and "
                 "devalues the ones you are actually good at.",
        )
    text = " ".join(text for _, _, text in _bullets(profile, language))
    for key, count in find_skills(text).items():
        if count > MAX_SKILL_REPEATS:
            yield finding(
                "repeated-keyword", Severity.INFO,
                f"'{profile.label_for(key)}' appears {count} times in the achievements.",
                hint="Repetition does not improve ATS ranking on any modern system.",
            )


def rule_orphan_skills(profile: Profile, language: str) -> Iterator[LintFinding]:
    """Skills listed but never demonstrated anywhere in the CV."""
    demonstrated = set(find_skills(" ".join(text for _, _, text in _bullets(profile, language))))
    summary_text = localized(profile.summary, language) or ""
    demonstrated |= set(find_skills(summary_text))
    listed = {key for key, value in profile.evidence.items() if value > 0.0}
    orphans = sorted(listed - demonstrated)
    if len(orphans) > 8:
        yield finding(
            "orphan-skills", Severity.INFO,
            f"{len(orphans)} skills are listed but never appear in an achievement.",
            hint="Fine for tools you genuinely use; a long list of them invites the "
                 "interview question you least want. Consider trimming the weakest.",
        )


def rule_acronyms(profile: Profile, language: str) -> Iterator[LintFinding]:
    summary = localized(profile.summary, language) or ""
    tokens = [token for token in re.findall(r"[A-Za-z/+#.]{2,}", summary)]
    if len(tokens) < 15:
        return
    acronyms = [token for token in tokens if token.isupper() and len(token) <= 6]
    if len(acronyms) / len(tokens) > MAX_ACRONYM_SHARE:
        yield finding(
            "acronym-soup", Severity.WARNING,
            "The summary is mostly acronyms.",
            hint="The first reader is often not technical. Say what you did, then name the tools.",
        )


# ---------------------------------------------------------------------------
# Rules — the evidence model
#
# These are particular to JobRadar. The evidence and ceiling per skill are
# what stop a tailored CV from claiming more than the candidate can defend,
# so they have to keep telling the truth about the CV they describe.
# ---------------------------------------------------------------------------


def rule_position_without_achievements(profile: Profile, language: str) -> Iterator[LintFinding]:
    """A position with no achievements under it is a title and two dates."""
    for experience in profile.experience:
        if not experience.bullets:
            title = localized(experience.title, language) or experience.id
            yield finding(
                "position-without-achievements", Severity.WARNING,
                f"'{title}' at {experience.organization or 'an unnamed employer'} has no "
                "achievements.",
                hint="Add one or two results from that job. Without them it proves no skill, "
                     "so nothing from it can be used to match an ad.",
                location=experience.id,
            )


def _flat(text: str) -> str:
    return re.sub(r"[^a-z0-9]", "", text.lower())


def _label(profile: Profile, key: str) -> str:
    """The profile's name for a skill, else the taxonomy's (a key set by hand has none)."""
    return profile.skill_labels.get(key) or label_for(key)


def rule_unproven_evidence(profile: Profile, language: str) -> Iterator[LintFinding]:
    """A skill marked as demonstrated (1.0) must appear in an achievement.

    If the achievement that proved it was rewritten and the skill dropped out,
    the score keeps counting it as proven and nobody notices.
    """
    texts = [text for _, _, text in _bullets(profile, language)]
    texts.append(localized(profile.summary, language) or "")
    texts.extend(localized(e.title, language) or "" for e in profile.experience)
    texts.extend(localized(e.degree, language) or "" for e in profile.education)
    texts.extend(localized(e.note, language) or "" for e in profile.education)
    texts.extend(localized(language_skill.name, "en") or "" for language_skill in profile.languages)
    joined = "\n".join(texts)
    tagged = {key for bullet in profile.all_bullets() for key in (bullet.skills or [])}
    mentioned = set(find_skills(joined)) | tagged
    flat = _flat(joined)
    for key, value in sorted(profile.evidence.items()):
        if value < 1.0 or key in mentioned or _flat(_label(profile, key)) in flat:
            continue
        yield finding(
            "unproven-evidence", Severity.WARNING,
            f"'{_label(profile, key)}' is marked as demonstrated but no achievement mentions it.",
            hint="Either the achievement that proved it changed, or it is written differently "
                 "in the CV. Until then, matching counts it as proven: lower its evidence in "
                 "Settings, or name it in the achievement that shows it.",
        )


def rule_impossible_ceiling(profile: Profile, language: str) -> Iterator[LintFinding]:
    """A ceiling can never promise more than the evidence allows."""
    for key, cap in sorted(profile.ceiling.items()):
        base = profile.evidence.get(key, 0.0)
        if base == 0.0 and cap > 0.0:
            yield finding(
                "impossible-ceiling", Severity.ERROR,
                f"'{_label(profile, key)}' has a ceiling of {cap:g} and no evidence.",
                hint="A skill your CV does not show can never be raised, so this ceiling is "
                     "ignored — but it says you could claim something you do not have. "
                     "Remove it, or add the evidence first.",
            )
        elif cap < base:
            yield finding(
                "impossible-ceiling", Severity.WARNING,
                f"'{_label(profile, key)}' has a ceiling of {cap:g}, below its evidence "
                f"of {base:g}.",
                hint="A tailored CV never lowers what is already proven, so this ceiling "
                     "means nothing. Set it at least to the evidence.",
            )


def rule_unknown_listed_skills(profile: Profile, language: str) -> Iterator[LintFinding]:
    """Skills listed on the CV that the evidence model does not know.

    They do not count when matching, so an ad asking for one shows a gap that
    is not really there.
    """
    known = {_flat(_label(profile, key)) for key in profile.evidence} | {
        _flat(key) for key in profile.evidence}
    unknown: list[str] = []
    for group in profile.skills:
        for item in group.items:
            keys = set(find_skills(item))
            if keys & set(profile.evidence) or _flat(item) in known or not _flat(item):
                continue
            unknown.append(item)
    if unknown:
        shown = ", ".join(f"'{item}'" for item in unknown[:6])
        more = f" and {len(unknown) - 6} more" if len(unknown) > 6 else ""
        yield finding(
            "unknown-listed-skills", Severity.INFO,
            f"Listed but unknown to matching: {shown}{more}.",
            hint="Add them in Settings → Your skills with the evidence you have, so ads that "
                 "ask for them count them.",
        )


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

PROFILE_RULES: tuple[Rule, ...] = (
    rule_missing_contact,
    rule_dates,
    rule_chronology,
    rule_gaps,
    rule_metrics,
    rule_duty_language,
    rule_bullet_length,
    rule_bullet_count,
    rule_tense_consistency,
    rule_first_person,
    rule_summary,
    rule_empty_phrases,
    rule_skill_stuffing,
    rule_orphan_skills,
    rule_acronyms,
    rule_position_without_achievements,
    rule_unproven_evidence,
    rule_impossible_ceiling,
    rule_unknown_listed_skills,
)


def lint_profile(profile: Profile, language: str | None = None) -> LintResult:
    """Run every rule against the base profile."""
    language = language or profile.default_language
    findings: list[LintFinding] = []
    for rule in PROFILE_RULES:
        try:
            findings.extend(rule(profile, language))
        except Exception as exc:
            log.exception(f"Linter rule failed: {rule.__name__}")
            findings.append(
                finding(
                    "linter-crash",
                    Severity.WARNING,
                    f"The rule '{rule.__name__}' encountered an error and could not finish.",
                    hint=f"Error detail: {exc}",
                )
            )
    return LintResult(findings)


def lint_tailored(profile: Profile, tailored, pages: int | None = None,
                  max_pages: int = 1) -> LintResult:
    """Run the rules against one job's tailored CV, plus the page-count check.

    The tailored summary and headline replace the profile's own, so they are
    what gets linted; everything else is shared with the base profile.
    """
    working = profile.model_copy(deep=True)
    working.summary = {tailored.language: tailored.summary}
    result = lint_profile(working, tailored.language)

    if pages is not None and pages > max_pages:
        result.findings.insert(
            0,
            finding(
                "too-long", Severity.ERROR,
                f"The CV runs to {pages} pages (limit {max_pages}).",
                hint="Cut the oldest position's weakest achievement first; it is the "
                     "one a reader is least likely to reach.",
            ),
        )
    for note in getattr(tailored, "validation_notes", []):
        result.findings.append(
            finding("rejected-draft", Severity.INFO,
                        f"A generated draft was rejected: {note}",
                        hint="The deterministic version was used instead.")
        )
    return result
