"""Cover letters and recruiter emails — generated on demand, one job at a time.

These are deliberately *not* produced by the daily search run. Writing a letter
for every job found is the slowest and most expensive part of any job-search
automation, and the letters are wanted for a small minority of the jobs — the
ones the user has decided to actually apply to. So the dashboard puts a button
on each job instead, and the text is written, stored and re-editable from there.

Without a language model the functions below still return something usable: a
skeleton assembled from the profile with the parts that need a human marked in
brackets. That is honest about what it is, and it beats a blank page.
"""

from __future__ import annotations

from datetime import datetime, timezone

from ..config import Settings
from ..llm import LLMClient
from ..llm.prompts import cover_letter, recruiter_email
from ..models import GeneratedDocument, Job, MatchScore, Profile, localized
from .tailor import _best_achievement, defensible_headline
from .validator import validate_document

SKELETON_LETTER: dict[str, str] = {
    "en": """Dear [name],

I am applying for the {title} role at {company}. {achievement} That is the part of
my background that lines up most directly with what you describe.

To be straightforward about the fit: {gap_sentence} [Add one sentence on why you
would still be effective here, and one concrete thing about {company} that made you
apply.]

Best regards,
{name}
{contact}""",
    "es": """Estimado/a [nombre]:

Le escribo para optar al puesto de {title} en {company}. {achievement} Es la parte
de mi experiencia que más directamente encaja con lo que describen.

Siendo claro con el encaje: {gap_sentence} [Añade una frase sobre por qué serías
igualmente efectivo aquí y algo concreto de {company} que te hizo aplicar.]

Un saludo,
{name}
{contact}""",
}

SKELETON_EMAIL: dict[str, str] = {
    "en": """Subject: {title} — {name}

Hello [name],

{achievement} I am writing about the {title} position at {company}; my CV is attached.

[One sentence on why this company in particular — something real from the ad.]
{question}

Best regards,
{name}
{contact}""",
    "es": """Asunto: {title} — {name}

Hola [nombre]:

{achievement} Te escribo por la oferta de {title} en {company}; adjunto mi CV.

[Una frase sobre por qué esta empresa en concreto — algo real de la oferta.]
{question}

Un saludo,
{name}
{contact}""",
}

GAP_SENTENCE: dict[str, str] = {
    "en": "the advertisement asks for {gap}, which I have not worked with directly.",
    "es": "la oferta pide {gap}, con lo que no he trabajado directamente.",
}

NO_GAP_SENTENCE: dict[str, str] = {
    "en": "I meet the requirements as listed.",
    "es": "cumplo los requisitos tal y como los describen.",
}


def _contact_line(profile: Profile, language: str) -> str:
    contact = profile.contact
    parts = [contact.email, contact.phone, contact.linkedin]
    return " · ".join(part for part in parts if part)


def _skeleton(template: dict[str, str], profile: Profile, job: Job, score: MatchScore,
              language: str) -> str:
    gap = score.gaps[0] if score.gaps else ""
    gap_sentence = (
        GAP_SENTENCE.get(language, GAP_SENTENCE["en"]).format(gap=gap)
        if gap
        else NO_GAP_SENTENCE.get(language, NO_GAP_SENTENCE["en"])
    )
    question = ""
    if job.alerts:
        question = f"[Ask about: {job.alerts[0]}]"
    return template.get(language, template["en"]).format(
        title=job.title,
        company=job.company or "[company]",
        name=profile.contact.name_for(language),
        contact=_contact_line(profile, language),
        achievement=_best_achievement(profile, job, language)
        or localized(profile.summary, language)
        or f"[Your strongest achievement relevant to {job.title}.]",
        gap_sentence=gap_sentence,
        question=question,
        role=defensible_headline(job, profile),
    )


def _generate(
    kind: str,
    profile: Profile,
    job: Job,
    score: MatchScore,
    settings: Settings,
    llm: LLMClient | None,
) -> GeneratedDocument:
    language = job.language or settings.default_language
    template = SKELETON_LETTER if kind == "cover_letter" else SKELETON_EMAIL
    text = _skeleton(template, profile, job, score, language)
    used_model = False

    if llm and settings.llm.write_letters:
        if kind == "cover_letter":
            system, user = cover_letter(profile, job, score.gaps, language)
        else:
            system, user = recruiter_email(profile, job, job.alerts, language)
        draft = llm.complete(system, user)
        if draft and len(draft.strip()) > 120:
            # Letters legitimately quote the advertisement, so figures are not
            # checked here; invented *skills* still are.
            report = validate_document(draft, profile, language, strict_numbers=False)
            if report.ok:
                text, used_model = draft.strip(), True

    return GeneratedDocument(
        job_id=job.id,
        kind=kind,
        language=language,
        text=text,
        generated_at=datetime.now(timezone.utc),
        llm_generated=used_model,
    )


def generate_cover_letter(profile: Profile, job: Job, score: MatchScore, settings: Settings,
                          llm: LLMClient | None = None) -> GeneratedDocument:
    """Write the cover letter for one job."""
    return _generate("cover_letter", profile, job, score, settings, llm)


def generate_email(profile: Profile, job: Job, score: MatchScore, settings: Settings,
                   llm: LLMClient | None = None) -> GeneratedDocument:
    """Write the application email for one job."""
    return _generate("email", profile, job, score, settings, llm)