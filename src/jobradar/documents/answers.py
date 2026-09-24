"""Answers to the free-text questions of application forms, and the answer bank.

Few applications stop at "attach your CV": there are three or four free-text
fields — why us, a project you are proud of, expected salary — answered late
at night, and they end up sounding like a template or, worse, promising
something the CV does not hold.

This is the cover-letter engine in the shape of a conversation, one thread per
job: paste the question as the form asks it, get an answer drawn from the
profile, and if it does not fit say so in the same thread ("shorter", "less
formal", "in English") instead of starting again.

Three things make it different from a letter:

* **The form's limit rules.** Forms cut at 500 characters or 150 words without
  warning. The limit is set per job, the answer is asked to respect it, and
  one that still runs over is shortened once more automatically.
* **The bank.** Questions repeat between companies. An answer the user likes
  is saved, and when a similar question comes up for another job it goes into
  the prompt as a precedent to adapt, not to copy.
* **Figures and dates the profile lacks** (expected salary, availability) are
  never invented: they come back as ``[pending: …]`` for the user to fill in,
  and every answer goes through ``review`` like letters do.
"""

from __future__ import annotations

import hashlib
import re
import unicodedata
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Literal

from ..config import Settings
from ..llm import LLMClient
from ..llm.prompts import form_answer
from ..models import AnswerThread, BankEntry, Job, Profile, ThreadMessage
from ..textutils import slugify
from .review import measure
from .tailor import _best_achievement

#: Words every form question has, which say nothing about which question it
#: is. Without removing them "why do you want to work here?" would match "why
#: did you leave your last job?".
FILLER_WORDS = frozenset((
    "que cual cuales como cuando donde quien por para con sin del las los una unos unas "
    "tus mis ser estar haber tiene tienes cuentanos cuentame describe explica hablanos dinos "
    "indica detalla brevemente favor puedes podrias crees consideras nos mas menos algo alguna "
    "alguno sobre desde hasta este esta estos estas "
    "what which how when where who why your you the and for with are does did tell about "
    "explain please could would can yourself briefly this that these those have has "
    "quel quelle pourquoi comment votre vous warum wie was ihre sie"
).split())
#: A bank entry is offered as a precedent from this word overlap (Jaccard) up.
SIMILARITY_THRESHOLD = 0.34
#: At most this many precedents go into a prompt.
MAX_PRECEDENTS = 2


def question_words(question: str) -> set[str]:
    """The words that tell one form question from another."""
    plain = unicodedata.normalize("NFD", question or "")
    plain = "".join(c for c in plain if unicodedata.category(c) != "Mn").lower()
    return {w for w in re.findall(r"[a-z0-9+#]+", plain) if len(w) > 2 and w not in FILLER_WORDS}


def similarity(a: str, b: str) -> float:
    """Word overlap between two questions, from 0 (nothing shared) to 1."""
    left, right = question_words(a), question_words(b)
    if not left or not right:
        return 0.0
    shared = len(left & right)
    return shared / (len(left) + len(right) - shared)


@dataclass
class Precedent:
    entry: BankEntry
    similarity: float


def similar_answers(question: str, bank: list[BankEntry], exclude_job: str = "") -> list[Precedent]:
    """Bank entries for questions like ``question``, best first.

    The job's own answers are left out: within one application the thread
    itself already carries them.
    """
    scored = [Precedent(entry, similarity(question, entry.question)) for entry in bank
              if entry.answer and entry.job_id != exclude_job]
    scored = [p for p in scored if p.similarity >= SIMILARITY_THRESHOLD]
    scored.sort(key=lambda p: -p.similarity)
    return scored[:MAX_PRECEDENTS]


def bank_id(question: str) -> str:
    """A stable id for a bank entry: readable slug plus a short hash."""
    digest = hashlib.sha1(question.strip().lower().encode("utf-8")).hexdigest()[:6]
    return f"{slugify(question, 34) or 'question'}_{digest}"


def last_question_for(thread: AnswerThread, index: int) -> str:
    """The question an answer at ``index`` replies to (the latest one before it)."""
    for message in reversed(thread.messages[:index]):
        if message.role == "question":
            return message.text
    return ""


def _skeleton(profile: Profile, job: Job, question: str, precedents: list[Precedent],
              language: str) -> str:
    """An honest starting point when no language model is configured."""
    if precedents:
        return precedents[0].entry.answer
    achievement = _best_achievement(profile, job, language)
    if language == "es":
        return (f"{achievement} [pendiente: responde a «{question}» con tus palabras]"
                if achievement else f"[pendiente: responde a «{question}»]")
    return (f"{achievement} [pending: answer \"{question}\" in your own words]"
            if achievement else f"[pending: answer \"{question}\"]")


def answer(
    profile: Profile,
    job: Job,
    thread: AnswerThread,
    question: str,
    bank: list[BankEntry],
    settings: Settings,
    llm: LLMClient | None = None,
) -> tuple[str, bool, list[Precedent]]:
    """Answer ``question`` in the job's thread: ``(text, written_by_model, precedents)``.

    Without a model the best precedent from the bank is offered as is, or a
    skeleton with the most relevant achievement and a ``[pending: …]`` part.
    """
    language = job.language or settings.default_language
    precedents = similar_answers(question, bank, exclude_job=job.id)
    if not (llm and llm.usable()):
        return _skeleton(profile, job, question, precedents, language), False, precedents

    history: list[tuple[str, str]] = [(m.role, m.text) for m in thread.messages]
    system, user = form_answer(
        profile, job, question, history,
        [(p.entry.question, p.entry.answer, p.entry.company) for p in precedents],
        thread.limit, thread.unit.value, language)
    text = (llm.complete(system, user) or "").strip()
    if not text:
        return _skeleton(profile, job, question, precedents, language), False, precedents
    if thread.limit and measure(text, thread.unit) > thread.limit:
        shorter = (llm.complete(system, user + f"\n\nYour answer was {measure(text, thread.unit)} "
                                f"{thread.unit.value}; the limit is {thread.limit}. Rewrite it "
                                "shorter, keeping the concrete facts.") or "").strip()
        if shorter:
            text = shorter
    return text, True, precedents


def add_turn(thread: AnswerThread, role: Literal["question", "answer"], text: str) -> None:
    """Append one message to the thread, stamped now."""
    thread.messages.append(ThreadMessage(role=role, text=text, at=datetime.now(timezone.utc)))


def to_bank(thread: AnswerThread, index: int, job: Job, language: str) -> BankEntry:
    """A bank entry from the answer at ``index`` and the question it replies to."""
    message = thread.messages[index]
    question = last_question_for(thread, index)
    return BankEntry(id=bank_id(question), question=question, answer=message.text,
                     company=job.company, job_title=job.title, job_id=job.id,
                     language=language, saved_at=datetime.now(timezone.utc))


__all__ = [
    "Precedent",
    "add_turn",
    "answer",
    "bank_id",
    "last_question_for",
    "question_words",
    "similar_answers",
    "similarity",
    "to_bank",
]
