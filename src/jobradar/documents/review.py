"""Warnings on the texts the user sends: cover letters, emails, form answers.

``validator`` guards what a language model may put into a CV: a draft that
invents a skill or a figure is rejected outright. Letters, emails and form
answers are different — the user edits them, sends them, and there are
legitimate reasons for most things a strict check would reject: naming a gap
is honest, quoting the ad's salary band is fine. So this module never blocks
anything. It points at the sentence and says why it might hurt, and the user
decides.

The checks, all mechanical:

* **figures** that appear neither in the profile nor in the job ad — models
  round 38 % up to 40 %, and that is the number asked about in an interview;
* **years of experience** claimed beyond what the profile's dates add up to,
  unless the sentence is about what the ad asks for;
* **skills** claimed that the profile has no evidence for (a skill the text
  only says is missing is fine);
* **boilerplate** phrases that make a letter read like a template;
* **format**: a letter or email that never names the company, an email
  without a subject line or a greeting placeholder, bracketed parts still to
  fill in, and a form answer over the form's limit.

Everything runs again whenever a saved text is shown, so drafts written before
a rule existed are checked too.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from datetime import date

from ..models import Job, LimitUnit, LintFinding, Profile, SalaryOrigin, Severity
from ..profile.vocabulary import allowed_terms
from ..taxonomy import label_for
from .validator import (
    NUMBER,
    TRIVIAL_NUMBER_LIMIT,
    YEARS_CLAIM,
    canonical_number,
    claimed_skills,
    profile_numbers,
)

#: Phrases that make an application read like a template, in the languages
#: documents are written in. Users add their own in Settings.
BOILERPLATE = (
    "to whom it may concern", "dear sir or madam", "i am writing to express my interest",
    "i believe i would be a great fit", "perfect fit", "results-driven", "team player",
    "think outside the box", "go-getter", "hard-working", "synergy", "passionate about",
    "do not hesitate to contact", "don't hesitate to contact", "look forward to hearing from you",
    "a quien corresponda", "muy señores míos", "sinergia", "valor añadido", "apasionado por",
    "apasionada por", "altamente motivad", "encaje perfecto", "no dude en", "no dudes en",
    "quedo a la espera de su respuesta", "madame, monsieur", "sehr geehrte damen und herren",
)

#: Words showing that a number of years is what the ad asks for, not a claim.
ASKED_FOR = re.compile(
    r"\b(?:ask(?:s|ing)? for|require[sd]?|requirement|you (?:want|need|ask)|looking for|"
    r"pide[ns]?|ped[ií]s|requiere[ns]?|busc[aá]is|solicit[aá]is|exig[eí]s|verlangt|exige)\b",
    re.IGNORECASE,
)
SUBJECT_LINE = re.compile(r"^\s*(?:subject|asunto|objet|betreff|oggetto|assunto)\s*:", re.IGNORECASE)
GREETING_PLACEHOLDER = re.compile(r"\[(?:name|nombre|nom|name des empfängers|nome)\]", re.IGNORECASE)
PENDING = re.compile(r"\[[^\]\n]{2,160}\]")
#: Placeholders the skeletons use for the greeting; they are reported by the
#: greeting check, not as "still to fill in".
_GREETING_ONLY = re.compile(r"^\[(?:name|nombre|nom|nome)\]$", re.IGNORECASE)


def measure(text: str, unit: LimitUnit | str) -> int:
    """The length of ``text`` the way an application form counts it."""
    if LimitUnit(unit) == LimitUnit.WORDS:
        return len(text.split())
    return len(text)


def _finding(rule: str, severity: Severity, message: str, hint: str = "") -> LintFinding:
    return LintFinding(rule=rule, severity=severity, message=message, hint=hint)


def _allowed_numbers(profile: Profile, job: Job | None, today: date) -> set[str]:
    """Figures the text may use: the profile's own, the ad's, and this year and next."""
    allowed = profile_numbers(profile)
    allowed |= {str(today.year), str(today.year + 1)}
    if job is not None:
        published = job.salary is not None and job.salary.origin == SalaryOrigin.PUBLISHED
        ad = " ".join(str(part) for part in (
            job.title, job.description, job.location, job.min_years_experience,
            job.salary.minimum if published and job.salary else None,
            job.salary.maximum if published and job.salary else None) if part)
        allowed |= {canonical_number(m.group(1)) for m in NUMBER.finditer(ad) if m.group(1)}
    return allowed


def check_figures(text: str, profile: Profile, job: Job | None, today: date) -> list[LintFinding]:
    allowed = _allowed_numbers(profile, job, today)
    unknown: list[str] = []
    for match in NUMBER.finditer(text):
        canonical = canonical_number(match.group(1))
        try:
            if float(canonical) <= TRIVIAL_NUMBER_LIMIT:
                continue
        except ValueError:
            continue
        if canonical not in allowed and match.group(0).strip() not in unknown:
            unknown.append(match.group(0).strip())
    if not unknown:
        return []
    return [_finding(
        "unsupported-figure", Severity.ERROR,
        f"Figures that are neither in your profile nor in the ad: {', '.join(unknown[:6])}.",
        "Models round numbers without saying so, and this is the figure you will be asked about. "
        "Use the real one or drop it.")]


def check_years(text: str, profile: Profile) -> list[LintFinding]:
    actual = profile.years_of_experience()
    findings: list[LintFinding] = []
    for match in YEARS_CLAIM.finditer(text):
        claimed = int(match.group(1))
        if claimed <= actual + 0.5:
            continue
        context = text[max(0, match.start() - 70): match.end() + 30]
        if ASKED_FOR.search(context):
            continue  # "you ask for 5 years" is about the job, not a claim
        findings.append(_finding(
            "inflated-seniority", Severity.ERROR,
            f"It says '{match.group(0)}' and your dated positions add up to {actual:g}.",
            "If that is what the ad asks for, make it clear the sentence is about them."))
    return findings


def check_skills(text: str, profile: Profile) -> list[LintFinding]:
    permitted = allowed_terms(profile)
    return [
        _finding("unsupported-skill", Severity.WARNING,
                 f"'{label_for(key)}' is not in your profile.",
                 "Naming it as a gap is honest; it must not read as if you had it.")
        for key in sorted(claimed_skills(text)) if key not in permitted
    ]


def check_boilerplate(text: str, extra: Iterable[str] = ()) -> list[LintFinding]:
    lowered = text.lower()
    phrases = [p for p in (*BOILERPLATE, *(e.strip().lower() for e in extra if e.strip()))
               if p in lowered]
    if not phrases:
        return []
    quoted = ", ".join(f"'{p}'" for p in phrases[:3])
    return [_finding("boilerplate", Severity.WARNING, f"Reads like a template: {quoted}.",
                     "Say the specific thing instead, in your own words.")]


def _names_company(text: str, company: str) -> bool:
    words = [w for w in re.findall(r"[\w&'-]+", company) if len(w) > 2 and w.lower() not in
             {"the", "sl", "sa", "slu", "ltd", "inc", "gmbh", "group", "grupo"}]
    return not words or any(re.search(rf"\b{re.escape(w)}\b", text, re.IGNORECASE)
                            for w in words[:2])


def check_format(text: str, kind: str, job: Job | None, limit: int | None = None,
                 unit: LimitUnit | str = LimitUnit.CHARACTERS) -> list[LintFinding]:
    findings: list[LintFinding] = []
    if kind in ("cover_letter", "email") and job is not None and job.company \
            and not _names_company(text, job.company):
        findings.append(_finding("company-not-named", Severity.WARNING,
                                 "It never names the company.",
                                 "A letter that fits any company reads as exactly that."))
    if kind == "email":
        first = next((line for line in text.splitlines() if line.strip()), "")
        if not SUBJECT_LINE.match(first):
            findings.append(_finding("no-subject", Severity.WARNING,
                                     "The email does not start with a subject line.",
                                     "Start with 'Subject: …' so it can be pasted as is."))
        if not GREETING_PLACEHOLDER.search(text):
            findings.append(_finding("no-greeting-name", Severity.INFO,
                                     "There is no [name] placeholder in the greeting.",
                                     "If you do not know who reads it, keep the greeting "
                                     "without a name."))
    pending = [m.group(0) for m in PENDING.finditer(text) if not _GREETING_ONLY.match(m.group(0))]
    if pending:
        findings.append(_finding("still-to-fill", Severity.INFO,
                                 f"{len(pending)} part{'s' if len(pending) > 1 else ''} in brackets "
                                 f"still to fill in, e.g. {pending[0]}.",
                                 "They are there because the fact is not in your profile."))
    if kind == "answer" and limit:
        length = measure(text, unit)
        if length > limit:
            findings.append(_finding("over-limit", Severity.ERROR,
                                     f"{length} {LimitUnit(unit).value} — the form cuts at {limit}.",
                                     "Ask for a shorter version in the thread, or trim it."))
    return findings


def review_text(
    text: str,
    profile: Profile,
    job: Job | None,
    kind: str,
    *,
    extra_phrases: Iterable[str] = (),
    limit: int | None = None,
    unit: LimitUnit | str = LimitUnit.CHARACTERS,
    today: date | None = None,
) -> list[LintFinding]:
    """Every warning for one text. ``kind`` is cover_letter, email or answer."""
    if not text.strip():
        return []
    today = today or date.today()
    return [
        *check_figures(text, profile, job, today),
        *check_years(text, profile),
        *check_skills(text, profile),
        *check_boilerplate(text, extra_phrases),
        *check_format(text, kind, job, limit, unit),
    ]
