"""Deduplication.

The same opening routinely appears on three boards at once, plus once more via
a recruitment agency that hides the client's name, and again next week under a
new id when the ad is reposted. Left unchecked this is the fastest way to make
a job radar unusable, so duplicates are collapsed on four increasingly
forgiving signals:

1. the job id (same source, same ad);
2. the same ad URL at the same company;
3. an exact key of normalised company + title;
4. same company and a high token overlap in the title.

Company names lose their legal form and filler words first ("Talan España,
S.L.U." and "Talan" are one employer), and titles lose the tags boards glue
onto them ("(m/f/d)", "100% remote", "Senior") so two labels of one vacancy
compare equal.

Only whole-token comparison is used. Substring matching looks tempting and is a
trap: "Alan" is inside "Talan", "UST" is inside "Braintrust", and the resulting
merges are silent and wrong.

Two entry points:

* :func:`deduplicate` collapses one run's results among themselves. When two
  records describe the same job, the more informative one wins — a published
  salary and a longer description beat an empty stub — and the winner inherits
  the other's apply URL if it had none.
* :func:`split_known` sets aside new ids that are a job already on file —
  active, closed or aged out — so a repost does not come back as "new".
"""

from __future__ import annotations

import re
from collections.abc import Iterable

from ..models import Job, SalaryOrigin
from ..textutils import normalise

#: How much of the shorter title must overlap for two ads at the same company
#: to be considered the same job.
TITLE_OVERLAP = 0.72

#: Legal forms and filler that do not tell one employer from another.
COMPANY_NOISE = {
    "sl", "slu", "sa", "sau", "sas", "srl", "spa", "sarl", "sccl",
    "gmbh", "mbh", "ag", "ab", "as", "oy", "bv", "nv", "plc", "ltd", "limited",
    "inc", "llc", "corp", "corporation", "co", "kg", "aps", "sp", "zoo",
    "group", "grupo", "holding", "holdings", "iberia", "spain", "espana",
    "technologies", "technology", "tech", "solutions", "consulting",
    "consultores", "consultoria", "services", "servicios", "digital",
    # "Banco Santander" / "Grupo Santander": one bank, two ways of saying it.
    "banco",
}

#: Words that do not tell one vacancy from another: seniority, generic role
#: nouns, work mode, gender tags, stop words.
TITLE_NOISE = {
    "senior", "sr", "jr", "junior", "mid", "midlevel", "semi", "ssr",
    "engineer", "engineering", "ingeniero", "ingeniera", "developer",
    "desarrollador", "desarrolladora", "programador", "programadora",
    "specialist", "especialista", "expert", "experto", "experta",
    "remote", "remoto", "remota", "teletrabajo", "hibrido", "presencial",
    "onsite", "hybrid", "fulltime", "full", "time", "jornada", "completa",
    "m", "f", "d", "h", "x", "w", "mfd", "hmx", "mwd",
    "de", "del", "la", "el", "los", "las", "y", "e", "o", "u", "en", "con",
    "para", "a", "al", "the", "and", "or", "for", "with", "in", "of", "to",
    "puesto", "oferta", "empleo", "trabajo", "job", "vacante", "position",
    "role", "nueva", "nuevo", "urgente", "inmediata",
}

# "Acme, S.L.U.": dotted legal forms fall apart into single letters when split
# into words, so they are removed before splitting.
_LEGAL_FORM = re.compile(
    r"[,\s]*\b(?:s\.\s*l\.?\s*u?\.?|s\.\s*a\.?\s*u?\.?|s\.\s*a\.?\s*s\.?|"
    r"s\.\s*r\.\s*l\.?|c\.\s*b\.?|s\.\s*c\.?)\s*$",
    re.I,
)
# "(m/f/d)", "100% remote", "| Madrid", "- Barcelona", "[Hybrid]": tails boards
# glue onto a title that say nothing about the job.
_TITLE_TAIL = re.compile(
    r"\s*[\(\[\|/–—-]\s*(?:m\s*/\s*f\s*/\s*[dx]|h\s*/\s*m\s*/\s*x|"
    r"\d{1,3}\s*%\s*\w+|remote|remoto|teletrabajo|h[ií]brido|hybrid|presencial|"
    r"full[\s-]?time|part[\s-]?time)\b.*$",
    re.I,
)


def company_key(name: str) -> str:
    """Employer name for comparison: no accents, legal form or filler words."""
    plain = _LEGAL_FORM.sub("", name or "")
    words = [w for w in normalise(plain).split() if w not in COMPANY_NOISE and len(w) > 1]
    return " ".join(words) or normalise(name)


def title_tokens(title: str) -> set[str]:
    """The title words that actually tell one vacancy from another."""
    plain = _TITLE_TAIL.sub("", title or "")
    words = [w for w in normalise(plain).split() if len(w) > 1 and not w.isdigit()]
    useful = {w for w in words if w not in TITLE_NOISE}
    return useful or set(words)


def job_key(job: Job) -> str:
    """Company + title, normalised. Two jobs with the same key are one job."""
    return f"{company_key(job.company)}|{' '.join(sorted(title_tokens(job.title)))}"


def _url(job: Job) -> str:
    """The ad URL as a dedupe signal, scoped to the employer."""
    url = (job.apply_url or job.url or "").strip().rstrip("/").lower()
    return f"{company_key(job.company)}@{url}" if url else ""


def _informativeness(job: Job) -> tuple[int, int, int, int]:
    """Sort key: the higher, the better a record is worth keeping."""
    salary_obj = getattr(job, "salary", None)
    return (
        1 if salary_obj and salary_obj.origin == SalaryOrigin.PUBLISHED else 0,
        1 if job.posted_at else 0,
        len(job.description or ""),
        len(job.requirements or []),
    )


def _same_job(left: Job, right: Job) -> bool:
    if not left.company or not right.company:
        return False
    if company_key(left.company) != company_key(right.company):
        return False
    left_tokens, right_tokens = title_tokens(left.title), title_tokens(right.title)
    if not left_tokens or not right_tokens:
        return False
    overlap = len(left_tokens & right_tokens) / min(len(left_tokens), len(right_tokens))
    return overlap >= TITLE_OVERLAP


def _merge(winner: Job, loser: Job) -> Job:
    """Fold anything the discarded record knew into the surviving one."""
    if not winner.apply_url and loser.link:
        winner.apply_url = loser.link
    if not winner.description and loser.description:
        winner.description = loser.description
        
    winner_salary = getattr(winner, "salary", None)
    loser_salary = getattr(loser, "salary", None)
    if (not winner_salary or winner_salary.origin != SalaryOrigin.PUBLISHED) and (loser_salary and loser_salary.origin == SalaryOrigin.PUBLISHED):
        winner.salary = loser.salary
        
    if not winner.posted_at and loser.posted_at:
        winner.posted_at = loser.posted_at
    if winner.min_years_experience is None:
        winner.min_years_experience = loser.min_years_experience
        
    if winner.alerts is None:
        winner.alerts = []
    for alert in (loser.alerts or []):
        if alert not in winner.alerts:
            winner.alerts.append(alert)
            
    seen_also = winner.raw.setdefault("also_seen_on", [])
    if loser.source not in seen_also and loser.source != winner.source:
        seen_also.append(loser.source)
    return winner


def deduplicate(jobs: list[Job]) -> list[Job]:
    """Collapse duplicates, keeping the most informative record of each job."""
    ordered = sorted(jobs, key=_informativeness, reverse=True)

    by_id: dict[str, Job] = {}
    for job in ordered:
        job.ensure_id()
        existing = by_id.get(job.id)
        by_id[job.id] = _merge(existing, job) if existing else job

    by_url: dict[str, Job] = {}
    for job in by_id.values():
        url = _url(job)
        if not url:
            by_url[f"id:{job.id}"] = job
            continue
        existing = by_url.get(url)
        by_url[url] = _merge(existing, job) if existing else job

    by_key: dict[str, Job] = {}
    for job in by_url.values():
        key = job_key(job)
        existing = by_key.get(key)
        by_key[key] = _merge(existing, job) if existing else job

    survivors: list[Job] = []
    for job in by_key.values():
        for kept in survivors:
            if _same_job(kept, job):
                _merge(kept, job)
                break
        else:
            survivors.append(job)
    return survivors


def split_known(jobs: list[Job], known: Iterable[Job]) -> tuple[list[Job], list[tuple[Job, Job]]]:
    """Separate new ids that are really a job already on file."""
    known = list(known)
    known_ids = {job.id for job in known}
    by_url: dict[str, Job] = {}
    by_key: dict[str, Job] = {}
    by_company: dict[str, list[Job]] = {}
    for job in known:
        url = _url(job)
        if url:
            by_url.setdefault(url, job)
        by_key.setdefault(job_key(job), job)
        by_company.setdefault(company_key(job.company), []).append(job)

    fresh: list[Job] = []
    duplicates: list[tuple[Job, Job]] = []
    for job in jobs:
        job.ensure_id()
        if job.id in known_ids:
            fresh.append(job)
            continue
        url = _url(job)
        twin = by_url.get(url) if url else None
        twin = twin or by_key.get(job_key(job))
        if twin is None and job.company:
            twin = next(
                (other for other in by_company.get(company_key(job.company), [])
                 if _same_job(other, job)),
                None,
            )
        if twin is not None:
            duplicates.append((job, twin))
        else:
            fresh.append(job)
    return fresh, duplicates