"""The anti-fabrication check.

Instructing a language model not to invent things works most of the time. This
module is what covers the rest of the time, and it is the reason JobRadar can
claim its output is defensible: no generated text reaches a PDF without being
compared, mechanically, against the profile it is supposed to be drawn from.

Three classes of fabrication are caught:

**Invented skills.** A technology named in the document that the profile has no
evidence for at all. This is the one that ends interviews.

**Invented figures.** A number in the document that appears nowhere in the
profile. Models are fond of rounding "38%" up to "40%" and of adding a
plausible-looking metric to a bullet that had none.

**Inflated seniority.** A claim of more years than the profile's own dates
support.

A finding is not a bug in the model — it is the system working. The caller
falls back to the deterministic text and records what was rejected.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from ..models import LintFinding, Profile, Severity, localized
from ..profile.vocabulary import allowed_terms, profile_text
from ..taxonomy import find_skills, label_for
from ..textutils import normalise

#: Numbers this small are ordinal noise ("2 days", "3 areas") rather than
#: claimed results, and flagging them would drown the real findings.
TRIVIAL_NUMBER_LIMIT = 3

NUMBER = re.compile(r"\b(\d[\d.,]*)\s*(%|percent|k\b|m\b|€|\$|£)?", re.IGNORECASE)
YEARS_CLAIM = re.compile(
    r"(\d{1,2})\s*\+?\s*(?:years|yrs|años|ans|jahre|anni|anos)", re.IGNORECASE
)


@dataclass
class ValidationReport:
    """The outcome of checking one generated document against the profile."""

    findings: list[LintFinding] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        """True when nothing was invented. Warnings alone do not fail a document."""
        return not any(finding.severity == Severity.ERROR for finding in self.findings)

    def messages(self) -> list[str]:
        return [finding.message for finding in self.findings]


def profile_numbers(profile: Profile) -> set[str]:
    """Every number the profile itself contains, plus its derived totals."""
    numbers = {
        canonical_number(match.group(1))
        for match in NUMBER.finditer(profile_text(profile))
        if match.group(1)
    }
    years = profile.years_of_experience()
    for value in {years, int(years), round(years), int(years) + 1}:
        numbers.add(canonical_number(str(value)))
    for experience in profile.experience:
        for part in (experience.start or "", experience.end or ""):
            for chunk in re.findall(r"\d+", part):
                numbers.add(canonical_number(chunk))
    return numbers


def canonical_number(raw: str) -> str:
    """Compare numbers by value, not by formatting: 3.500 == 3,500 == 3500."""
    digits = re.sub(r"[.,](?=\d{3}\b)", "", raw.strip())
    digits = digits.rstrip(".,")
    try:
        value = float(digits.replace(",", "."))
    except ValueError:
        return digits
    return str(int(value)) if value.is_integer() else str(value)


#: Words that turn a sentence naming a skill into an admission of not having
#: it ("I have not worked with Terraform"), in the languages letters are
#: written in. "not only" is a claim, so it is excluded first.
_NEGATION = re.compile(
    r"\b(?:not|no|never|without|lack(?:ing|s)?|haven't|hasn't|don't|doesn't|didn't|yet to|"
    r"new to|sin|nunca|todav[ií]a no|a[uú]n no|kein(?:e|en)?|nicht|ohne|noch nie|"
    r"pas|sans|jamais)\b",
    re.IGNORECASE,
)
_NOT_ONLY = re.compile(r"\b(?:not only|no s[oó]lo|nicht nur|non seulement)\b", re.IGNORECASE)
#: Clause boundaries: a negation covers its own clause, not the whole
#: sentence ("Although I lack Rust, I have years of Kubernetes" claims Kubernetes).
_CLAUSE = re.compile(r"[.!?;:,\n]+|\s[–—-]\s|\b(?:but|however|pero|sin embargo|aber|mais)\b",
                     re.IGNORECASE)


def claimed_skills(text: str) -> set[str]:
    """Skill keys the text claims, leaving out the ones it only says it lacks.

    A letter is asked to be honest about the gaps, and "I have not worked with
    MLOps yet" names MLOps without claiming it. A skill counts as claimed when
    at least one clause names it without a negation.
    """
    claimed: set[str] = set()
    for clause in _CLAUSE.split(text):
        keys = set(find_skills(clause))
        if keys and not _NEGATION.search(_NOT_ONLY.sub(" ", clause)):
            claimed |= keys
    return claimed


def check_invented_skills(text: str, profile: Profile) -> list[LintFinding]:
    """Technologies claimed in the document that the profile cannot support."""
    permitted = allowed_terms(profile)
    findings: list[LintFinding] = []
    for key in sorted(claimed_skills(text)):
        if key in permitted:
            continue
        findings.append(
            LintFinding(
                rule="invented-skill",
                severity=Severity.ERROR,
                message=f"The document claims '{label_for(key)}', which your profile has no evidence for.",
                hint="Either remove it, or add real evidence for it to your profile and re-generate.",
            )
        )
    return findings


def check_invented_numbers(text: str, profile: Profile) -> list[LintFinding]:
    """Figures that appear in the document but nowhere in the profile."""
    known = profile_numbers(profile)
    findings: list[LintFinding] = []
    seen: set[str] = set()
    for match in NUMBER.finditer(text):
        canonical = canonical_number(match.group(1))
        if canonical in seen or canonical in known:
            continue
        try:
            if float(canonical) <= TRIVIAL_NUMBER_LIMIT:
                continue
        except ValueError:
            continue
        seen.add(canonical)
        findings.append(
            LintFinding(
                rule="invented-figure",
                severity=Severity.ERROR,
                message=f"The figure '{match.group(0).strip()}' does not appear anywhere in your profile.",
                hint="Numbers on a CV get asked about. Use the real one or drop the claim.",
            )
        )
    return findings


def check_seniority(text: str, profile: Profile) -> list[LintFinding]:
    """Years-of-experience claims the profile's own dates do not support."""
    actual = profile.years_of_experience()
    findings: list[LintFinding] = []
    for match in YEARS_CLAIM.finditer(text):
        claimed = int(match.group(1))
        if claimed > actual + 0.5:
            findings.append(
                LintFinding(
                    rule="inflated-seniority",
                    severity=Severity.ERROR,
                    message=f"The document claims {claimed} years of experience; your profile supports {actual:g}.",
                    hint="Count only what your dated positions add up to.",
                )
            )
    return findings


def check_employers(text: str, profile: Profile) -> list[LintFinding]:
    """Organisations named in the document that are not in the profile.

    A warning rather than an error: a cover letter legitimately names the
    company it is addressed to, so this flags for review instead of rejecting.
    """
    known = normalise(profile_text(profile))
    findings: list[LintFinding] = []
    for candidate in set(re.findall(r"\b(?:at|en|bei|chez)\s+([A-Z][\w&.-]+(?:\s+[A-Z][\w&.-]+){0,2})", text)):
        if normalise(candidate) and normalise(candidate) not in known:
            findings.append(
                LintFinding(
                    rule="unknown-organisation",
                    severity=Severity.WARNING,
                    message=f"'{candidate}' is named but is not in your profile.",
                    hint="Fine if it is the company you are applying to; otherwise remove it.",
                )
            )
    return findings


def validate_document(
    text: str,
    profile: Profile,
    language: str = "en",
    strict_numbers: bool = True,
) -> ValidationReport:
    """Check one generated document against the profile.

    ``strict_numbers`` is on for CVs and off for cover letters, where a number
    quoted from the job advertisement is legitimate.
    """
    if not text.strip():
        return ValidationReport()
    findings = check_invented_skills(text, profile)
    findings += check_seniority(text, profile)
    findings += check_employers(text, profile)
    if strict_numbers:
        findings += check_invented_numbers(text, profile)
    return ValidationReport(findings)


def validate_rendered_cv(sections: dict[str, str], profile: Profile, language: str) -> ValidationReport:
    """Validate a whole rendered CV, section by section.

    Only the generated sections are checked. The achievement bullets are copied
    verbatim from the profile, so checking them would only ever report the
    profile against itself.
    """
    report = ValidationReport()
    for name in ("headline", "summary"):
        text = sections.get(name, "")
        if not text:
            continue
        for finding in validate_document(text, profile, language).findings:
            finding.location = name
            report.findings.append(finding)
    _ = localized  # keep the import meaningful for future localized sections
    return report
