"""Prompt construction.

Every prompt in JobRadar that touches the candidate's CV carries the same
constraint, stated the same way: **the profile is the only source of facts.**
That instruction is not trusted on its own — ``documents.validator`` checks the
output afterwards and rejects anything that introduces a claim the profile does
not support — but it does most of the work, and stating it precisely is
cheaper than repairing the result.

Prompts are plain functions returning ``(system, user)`` so they can be read,
diffed and unit-tested without a network call.
"""

from __future__ import annotations

import json

from ..models import Job, Profile, localized
from ..taxonomy import taxonomy

# ---------------------------------------------------------------------------
# Shared fragments
# ---------------------------------------------------------------------------

NO_FABRICATION = """\
Absolute rule, above every other instruction: you may only use facts that appear
in the candidate profile you are given. You may reorder, re-emphasise, translate
and rephrase what is there. You may not add a technology, a tool, a metric, an
employer, a responsibility, a certification or a year of experience that is not
in the profile — not even one the job asks for, not even hedged, not even as
"familiar with". If the job requires something the candidate lacks, leave it
out; a named gap is recoverable in an interview, an invented claim is not."""

XYZ_RULE = """\
Achievements follow the XYZ formula: accomplished X, as measured by Y, by doing Z.
Keep the numbers that are already in the profile; never invent or round new ones."""


def _profile_digest(profile: Profile, language: str) -> str:
    """Compact, faithful rendering of the profile for a prompt.

    Only fields a document may legitimately draw on are included, so the model
    is not tempted by data it must not use.
    """
    payload = {
        "name": profile.contact.name_for(language),
        "location": localized(profile.contact.city, language),
        "summary": localized(profile.summary, language),
        "experience": [
            {
                "id": experience.id,
                "title": localized(experience.title, language),
                "organization": experience.organization,
                "dates": f"{experience.start or ''} – {experience.end or 'present'}",
                "achievements": [
                    {"id": bullet.id, "text": localized(bullet.text, language)}
                    for bullet in (experience.bullets or [])
                ],
            }
            for experience in (profile.experience or [])
        ],
        "education": [
            {
                "degree": localized(education.degree, language),
                "institution": localized(education.institution, language),
                "dates": f"{education.start or ''} – {education.end or ''}",
                "note": localized(education.note, language),
            }
            for education in (profile.education or [])
        ],
        "certifications": [
            {"name": localized(c.name, language), "issuer": c.issuer, "year": c.year}
            for c in (profile.certifications or [])
        ],
        "skills": {
            group.key: {"label": localized(group.label, language), "items": group.items or []}
            for group in (profile.skills or [])
        },
        "languages": [
            {"language": localized(item.name, language), "level": item.level}
            for item in (profile.languages or [])
        ],
        "total_years_experience": profile.years_of_experience(),
    }
    return json.dumps(payload, ensure_ascii=False, indent=1)


def _job_digest(job: Job, description_limit: int = 6000) -> str:
    return json.dumps(
        {
            "title": job.title,
            "company": job.company,
            "location": job.location,
            "work_mode": job.work_mode.value if hasattr(job.work_mode, "value") else str(job.work_mode),
            "language": job.language,
            "description": (job.description or "")[:description_limit],
        },
        ensure_ascii=False,
        indent=1,
    )


# ---------------------------------------------------------------------------
# 1. Reading a job ad
# ---------------------------------------------------------------------------


def read_job_ad(job: Job) -> tuple[str, str]:
    """Ask the model to extract structured requirements and the fine print.

    The fine print is the valuable part: work mode and geographic restriction
    are routinely mis-tagged by the boards themselves, and reading the ad body
    is the only way to catch it.
    """
    keys = ", ".join(sorted(taxonomy()))
    system = f"""You extract structured data from job advertisements. You are precise and you
never guess: when the ad does not say something, you say so rather than inventing a value.

Return JSON with exactly these fields:
{{
  "requirements": [{{"key": "<taxonomy key or a new snake_case key>",
                     "label": "<short human label, in English>",
                     "weight": <1-10, how hard the ad insists on it>}}],
  "work_mode": "remote" | "hybrid" | "onsite" | "unknown",
  "remote_scope": "worldwide" | "region" | "country" | "unknown",
  "remote_regions": ["<region or country the ad restricts remote work to>"],
  "min_years_experience": <integer or null>,
  "salary": {{"minimum": <int or null>, "maximum": <int or null>,
              "currency": "<ISO code>", "published": <true|false>}},
  "language": "<ISO-639-1 code of the ad>",
  "alerts": ["<something the candidate must clarify before applying>"]
}}

Guidance:
- Prefer these existing keys when one fits: {keys}
- Weight 9-10 for things the ad calls essential or repeats; 4-6 for "nice to have".
- 12 to 20 requirements is a good number. Include the ones the candidate may lack:
  an honest gap is the most useful thing this analysis produces.
- work_mode: an ad that says "remote" but also "2 days in the office" is hybrid.
- remote_scope: "remote" in a city usually means remote *within that country*.
  Only answer "worldwide" when the ad actually says anywhere / any timezone.
- alerts: unnamed end client, salary quoted for a different country, contracting
  country unstated, agency posting, on-site days hidden in the small print."""
    return system, f"Job advertisement:\n{_job_digest(job)}"


# ---------------------------------------------------------------------------
# 2. Importing an existing CV
# ---------------------------------------------------------------------------


def parse_cv(text: str, language: str = "en") -> tuple[str, str]:
    """Turn the raw text of an uploaded CV into the structured profile."""
    system = """You convert a CV into structured JSON. Transcribe faithfully: keep every
number, date and proper noun exactly as written, and do not improve, summarise or invent
anything. If a field is not in the CV, leave it empty.

Return JSON:
{
  "contact": {"full_name": "", "city": "", "country": "<ISO-3166 alpha-2>",
              "phone": "", "email": "", "linkedin": "", "github": "", "website": ""},
  "summary": "<the professional summary, verbatim if present, else empty>",
  "experience": [{"id": "<short slug>", "title": "", "organization": "", "location": "",
                  "start": "YYYY-MM", "end": "YYYY-MM or null if current",
                  "bullets": [{"id": "<slug>", "text": "<verbatim>"}]}],
  "education": [{"id": "<slug>", "degree": "", "institution": "",
                 "start": "YYYY-MM", "end": "YYYY-MM", "note": "<thesis, honours>"}],
  "certifications": [{"name": "", "issuer": "", "year": ""}],
  "skills": [{"key": "<slug>", "label": "<section label as written>", "items": ["", ""]}],
  "languages": [{"name": "", "level": ""}],
  "evidence": {"<skill key>": <0.0-1.0>},
  "ceiling": {"<skill key>": <0.0-1.0>}
}

`evidence` is how strongly the CV *already* proves each skill:
  1.0 demonstrated inside an achievement bullet or the summary
  0.5 merely listed in a skills section
Never include a skill the CV does not mention at all.

`ceiling` is how far that skill could honestly be pushed if the CV were rewritten to
emphasise it — how well the person could defend it in an interview given what the CV
shows. It is never lower than the evidence, and for a skill only listed once with no
supporting work it should stay close to it."""
    return system, f"Language of the CV: {language}\n\nCV text:\n{(text or '')[:20000]}"


# ---------------------------------------------------------------------------
# 3. Tailoring the CV to one job
# ---------------------------------------------------------------------------


def tailor_cv(profile: Profile, job: Job, surfaced: list[str], language: str) -> tuple[str, str]:
    """Ask for a headline, a summary and a bullet order — nothing else.

    The model never writes the achievement bullets themselves. Those are the
    candidate's own words, written once and reused, which is what makes the
    output defensible in an interview: the CV that got them the call says
    exactly what their profile says.
    """
    labels = [profile.label_for(key) for key in (surfaced or [])]
    system = f"""You adapt an existing CV to one specific job advertisement.

{NO_FABRICATION}

{XYZ_RULE}

You produce three things and nothing else:

1. "headline" — the role line under the candidate's name. Two to six words, matching how
   this employer names the role, and only if the candidate's real background supports it.
   Never inflate seniority beyond what the profile shows.
2. "summary" — the professional summary, 3 to 5 sentences, written in the first person
   without "I" where the language allows it. It must lead with the strongest genuine
   overlap between this candidate and this job, name at least one concrete achievement
   already in the profile (with its real number), and read like a person wrote it.
   No adjective stacking, no "passionate", no "results-driven".
3. "bullet_order" — for each experience id, the ids of its achievements in the order they
   should appear for this job. You may only reorder within an experience. You may not
   drop, merge, rewrite or move achievements between jobs.

Also return "skill_group_order": the skill section keys, most relevant to this job first.

Write everything in {language}. Return JSON:
{{"headline": "", "summary": "", "bullet_order": {{"<experience id>": ["<bullet id>"]}},
  "skill_group_order": ["<skill key>"]}}"""
    user = f"""Candidate profile (the only facts you may use):
{_profile_digest(profile, language)}

Job advertisement:
{_job_digest(job)}

Skills worth emphasising for this job, because the candidate has them and the job asks
for them: {", ".join(labels) or "(none identified)"}"""
    return system, user


# ---------------------------------------------------------------------------
# 4. Cover letter and recruiter email — generated on demand, per job
# ---------------------------------------------------------------------------


def cover_letter(profile: Profile, job: Job, gaps: list[str], language: str) -> tuple[str, str]:
    system = f"""You write a short cover letter for one job application.

{NO_FABRICATION}

Constraints:
- One or two paragraphs. Shorter is better. No letterhead, no address block.
- Plain, natural language. No "I am writing to express my interest", no "I believe I
  would be a great fit", no adjective stacking.
- Name the single biggest gap between the candidate and the job openly, in one clause,
  and say what compensates for it. A senior recruiter spots a covered-up gap in seconds
  and it costs more credibility than the gap itself.
- Anchor the interest in something specific and real from this advertisement or company,
  never a generic compliment.
- Write in {language}. Return plain text only, no JSON, no subject line."""
    user = f"""Candidate profile:
{_profile_digest(profile, language)}

Job advertisement:
{_job_digest(job, 4000)}

The candidate's main gaps against this job: {", ".join(gaps or []) or "(none identified)"}"""
    return system, user


def recruiter_email(profile: Profile, job: Job, alerts: list[str], language: str) -> tuple[str, str]:
    system = f"""You write the email that accompanies a job application.

{NO_FABRICATION}

Structure, exactly:
- A subject line, prefixed "Subject: ".
- A greeting using the placeholder [name] so the candidate can fill it in.
- Paragraph 1: who the candidate is, and the one concrete achievement from the profile
  that connects to this specific role. Use its real number.
- Paragraph 2: why this company in particular — something real from the advertisement or
  the company, never a generic compliment — and a mention of the attached CV. If the ad
  leaves something material unclear, ask about it here in one sentence.
- A sign-off with the candidate's name and contact details from the profile.

Write in {language}. Return plain text only."""
    user = f"""Candidate profile:
{_profile_digest(profile, language)}

Job advertisement:
{_job_digest(job, 4000)}

Things the advertisement leaves unclear, worth asking about:
{", ".join(alerts or []) or "(nothing flagged)"}"""
    return system, user