"""After applying: a follow-up for a quiet application, and an interview prep pack.

Both are written on demand from a job's card, like the letters, and both keep
the rule every document here keeps: nothing that is not in the profile.

* **Follow-up** — a short email for an application with no answer yet. It
  names the date you applied and one achievement the CV already carried, and
  asks where the process stands. It never adds a claim the materials you sent
  did not make, so it cannot contradict them.
* **Interview prep** — what the interview will be about, read from the ad's
  requirements by weight: for each one you meet, the achievement of yours that
  proves it, laid out to tell as a STAR story; for each gap, how long it
  really takes to learn and an honest way to answer; the questions worth
  asking them (what the ad leaves unclear); and the practical facts.

Without a language model the follow-up is a skeleton with brackets, and the
prep pack is complete on its own (the model then adds likely questions).
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any

from ..config import Settings
from ..i18n import skill_label
from ..llm import LLMClient
from ..llm.prompts import follow_up_email, interview_questions
from ..models import Application, GeneratedDocument, Job, MatchScore, Profile, localized
from ..taxonomy import difficulty_for, find_skills
from .letters import contact_line
from .tailor import _best_achievement
from .validator import validate_document

#: Days without an answer after which a follow-up is worth sending.
FOLLOW_UP_AFTER_DAYS = 10

SKELETON_FOLLOW_UP: dict[str, str] = {
    "en": """Subject: {title} — following up on my application

Hello [name],

On {applied_on} I applied for the {title} role at {company}, and I remain very interested. {achievement}

Could you tell me where the process stands, or whether you need anything else from me?

Best regards,
{name}
{contact}""",
    "es": """Asunto: {title} — seguimiento de mi candidatura

Hola [nombre]:

El {applied_on} envié mi candidatura al puesto de {title} en {company}, y sigo muy interesado/a. {achievement}

¿Podrías decirme en qué punto está el proceso, o si necesitáis algo más de mí?

Un saludo,
{name}
{contact}""",
}

PREP_TEXT: dict[str, dict[str, Any]] = {
    "en": {
        "title": "Interview prep — {title} at {company}",
        "stage": "Stage: {stage}",
        "intro": ("What they will ask about, from the ad's requirements, most insisted on "
                  "first. Tell each example as a story: Situation, Task, Action, Result."),
        "strengths": "What you can prove",
        "example": "Your example: {text}",
        "no_example": ("Listed in your skills, but no achievement of yours shows it: think "
                       "of a time you used it, with what came of it."),
        "star": "  S/T: [the situation and what was asked of you]\n"
                "  A: [what you did]\n"
                "  R: [the result, with its number]",
        "gaps": "Gaps — answer them honestly",
        "gap": "{label} (asked with weight {weight}) — {note}",
        "gap_answer": "  \"I have not worked with {label} directly. The closest is [...], and "
                      "[how you would close it].\"",
        "questions": "Questions worth asking them",
        "generic_questions": ["What would a good first six months look like in this role?",
                              "How is the team organised, and who would I work with most?",
                              "What are the next steps, and when can I expect to hear?"],
        "facts": "Practical facts",
        "work_mode": "Work mode: {value}",
        "location": "Place: {value}",
        "salary": "Salary: {value}",
        "published": "published", "estimated": "estimate",
        "likely": "Likely questions (language model)",
    },
    "es": {
        "title": "Preparación de entrevista — {title} en {company}",
        "stage": "Fase: {stage}",
        "intro": ("De qué te preguntarán, según los requisitos de la oferta, primero lo que "
                  "más exige. Cuenta cada ejemplo como una historia: Situación, Tarea, "
                  "Acción, Resultado."),
        "strengths": "Lo que puedes demostrar",
        "example": "Tu ejemplo: {text}",
        "no_example": ("Está en tus competencias, pero ningún logro tuyo lo muestra: piensa "
                       "en una vez que lo usaste y en qué resultó."),
        "star": "  S/T: [la situación y lo que se te pidió]\n"
                "  A: [lo que hiciste]\n"
                "  R: [el resultado, con su número]",
        "gaps": "Carencias — respóndelas con honestidad",
        "gap": "{label} (pedida con peso {weight}) — {note}",
        "gap_answer": "  «No he trabajado directamente con {label}. Lo más cercano es [...], y "
                      "[cómo lo cerrarías].»",
        "questions": "Preguntas que merece la pena hacerles",
        "generic_questions": ["¿Cómo serían unos buenos seis primeros meses en este puesto?",
                              "¿Cómo está organizado el equipo y con quién trabajaría más?",
                              "¿Cuáles son los siguientes pasos y cuándo sabré algo?"],
        "facts": "Datos prácticos",
        "work_mode": "Modalidad: {value}",
        "location": "Lugar: {value}",
        "salary": "Salario: {value}",
        "published": "publicado", "estimated": "estimación",
        "likely": "Preguntas probables (modelo de lenguaje)",
    },
}

DIFFICULTY_TEXT: dict[str, dict[str, str]] = {
    "en": {"fast": "days to a week to read up on: worth doing before the interview.",
           "medium": "several weeks of real work: say where you would start.",
           "slow": "not learnt in one hiring process: answer it honestly."},
    "es": {"fast": "de días a una semana: merece la pena repasarlo antes de la entrevista.",
           "medium": "varias semanas de trabajo real: di por dónde empezarías.",
           "slow": "no se aprende en un proceso de selección: respóndela con honestidad."},
}


def days_waiting(application: Application | None, today: date | None = None) -> int | None:
    """Days since you applied, or None when there is no date."""
    if application is None or application.applied_on is None:
        return None
    return ((today or date.today()) - application.applied_on).days


def generate_follow_up(profile: Profile, job: Job, application: Application | None,
                       sent: list[str], settings: Settings,
                       llm: LLMClient | None = None) -> GeneratedDocument:
    """The follow-up email for one application. ``sent`` is the text you sent."""
    language = job.language or settings.default_language
    applied_on = application.applied_on.isoformat() if application and application.applied_on \
        else "[date]"
    template = SKELETON_FOLLOW_UP.get(language, SKELETON_FOLLOW_UP["en"])
    text = template.format(
        title=job.title, company=job.company or "[company]", applied_on=applied_on,
        achievement=_best_achievement(profile, job, language) or "",
        name=profile.contact.name_for(language), contact=contact_line(profile, language))
    used_model = False
    if llm and settings.llm.write_letters:
        system, user = follow_up_email(profile, job, applied_on, sent, language)
        draft = llm.complete(system, user)
        if draft and len(draft.strip()) > 80:
            report = validate_document(draft, profile, language, strict_numbers=False)
            if report.ok:
                text, used_model = draft.strip(), True
    return GeneratedDocument(job_id=job.id, kind="follow_up", language=language, text=text,
                             generated_at=datetime.now(timezone.utc), llm_generated=used_model)


def _example_for(key: str, profile: Profile, language: str) -> str:
    """Your achievement that best proves skill ``key``, verbatim, or an empty string."""
    best, count = "", 0
    for bullet in profile.all_bullets():
        text = localized(bullet.text, language)
        found = find_skills(text)
        hits = found.get(key, 0) + (1 if key in (bullet.skills or []) else 0)
        if hits > count:
            best, count = text, hits
    return best


def interview_prep_text(profile: Profile, job: Job, score: MatchScore,
                        application: Application | None, language: str,
                        likely: str = "") -> str:
    """The prep pack as plain text, from the profile and the ad alone."""
    words = PREP_TEXT.get(language, PREP_TEXT["en"])
    difficulty = DIFFICULTY_TEXT.get(language, DIFFICULTY_TEXT["en"])
    evidence = profile.evidence or {}
    lines = [words["title"].format(title=job.title, company=job.company or "—")]
    if application and application.stage:
        lines.append(words["stage"].format(stage=application.stage.value.replace("_", " ")))
    lines += ["", words["intro"], "", f"## {words['strengths']}"]

    requirements = sorted(job.requirements or [], key=lambda r: -r.weight)
    owned = [r for r in requirements if evidence.get(r.key, 0.0) > 0.0]
    for requirement in owned[:8]:
        example = _example_for(requirement.key, profile, language)
        name = skill_label(requirement.key, requirement.label, language)
        lines.append(f"- {name} ({requirement.weight})")
        lines.append("  " + (words["example"].format(text=example) if example
                             else words["no_example"]))
        if example:
            lines.append(words["star"])
    gaps = score.gap_details or [{"key": r.key, "label": r.label, "weight": r.weight}
                                 for r in requirements if evidence.get(r.key, 0.0) <= 0.0]
    if gaps:
        lines += ["", f"## {words['gaps']}"]
        for gap in gaps[:6]:
            level = str(gap.get("difficulty") or difficulty_for(str(gap.get("key"))))
            name = skill_label(str(gap.get("key")), str(gap["label"]), language)
            lines.append("- " + words["gap"].format(label=name, weight=gap["weight"],
                                                    note=difficulty.get(level, "")))
            lines.append(words["gap_answer"].format(label=name))

    lines += ["", f"## {words['questions']}"]
    lines += [f"- {alert}" for alert in (job.alerts or [])[:4]]
    lines += [f"- {question}" for question in words["generic_questions"]]

    facts = []
    if job.work_mode and job.work_mode.value != "unknown":
        facts.append(words["work_mode"].format(value=job.work_mode.value))
    if job.location:
        facts.append(words["location"].format(value=job.location))
    if job.salary and (job.salary.minimum or job.salary.maximum):
        figure = "–".join(f"{value:,.0f}" for value in (job.salary.minimum, job.salary.maximum)
                          if value)
        origin = words["published" if job.salary.origin.value == "published" else "estimated"]
        facts.append(words["salary"].format(value=f"{figure} {job.salary.currency} ({origin})"))
    if facts:
        lines += ["", f"## {words['facts']}"] + [f"- {fact}" for fact in facts]
    if likely.strip():
        lines += ["", f"## {words['likely']}", likely.strip()]
    return "\n".join(lines)


def generate_interview_prep(profile: Profile, job: Job, score: MatchScore,
                            application: Application | None, settings: Settings,
                            llm: LLMClient | None = None) -> GeneratedDocument:
    """The interview prep pack for one job."""
    language = job.language or settings.default_language
    likely, used_model = "", False
    if llm and settings.llm.write_letters:
        system, user = interview_questions(profile, job, score.gaps, language)
        draft = llm.complete(system, user) or ""
        # Not run through the validator: these are notes for you, and naming
        # your gaps is the point of them. Nothing here is sent.
        if len(draft.strip()) > 80:
            likely, used_model = draft.strip(), True
    text = interview_prep_text(profile, job, score, application, language, likely)
    return GeneratedDocument(job_id=job.id, kind="interview_prep", language=language, text=text,
                             generated_at=datetime.now(timezone.utc), llm_generated=used_model)
