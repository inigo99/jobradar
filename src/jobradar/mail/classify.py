"""What an email about an application means, decided by rules.

Three kinds matter (:class:`~jobradar.models.MailKind`): a rejection, an
advance — a person moved: an interview, a test, a call, a request for
documents — and an automatic acknowledgement. Everything else (job alerts,
newsletters, portal notifications) is noise and ignored.

The order of the checks is the order of what costs most to get wrong: a
rejection often *also* thanks you for applying and mentions the "next steps"
other candidates will take, so it is recognised first; an advance next; an
acknowledgement last. Rules cover English and Spanish, the languages the
dashboard's users write most in; add phrases for another language to the
tuples below.

The excerpt is always a literal sentence from the message — the one that
decided the classification — so nothing shown on the dashboard is a guess.
"""

from __future__ import annotations

import re
from datetime import date, datetime, time

from ..models import MailKind

REJECTION = (
    "unfortunately", "we regret", "regret to inform", "not moving forward",
    "not be moving forward", "decided to move forward with other", "decided to proceed with other",
    "other candidates whose", "no longer considering", "position has been filled",
    "will not be progressing", "not been successful", "unsuccessful",
    "lamentablemente", "lamentamos", "sentimos comunicarte", "sentimos informarte",
    "no ha sido seleccionad", "no has sido seleccionad", "no continuar con tu candidatura",
    "no seguir adelante con tu candidatura", "continuar con otros candidatos",
    "otros perfiles que se ajustan", "hemos decidido no avanzar", "descartad",
    "la posición ha sido cubierta", "el puesto ha sido cubierto",
)
ADVANCE = (
    "interview", "entrevista", "next step", "next stage", "siguiente fase", "siguiente paso",
    "próxima fase", "proxima fase", "technical test", "prueba técnica", "prueba tecnica",
    "assessment", "take-home", "coding challenge", "would like to schedule", "schedule a call",
    "set up a call", "book a time", "your availability", "tu disponibilidad",
    "nos gustaría conocerte", "nos gustaria conocerte", "videollamada", "llamada",
    "we would like to invite", "invite you", "te invitamos", "pleased to invite",
    "send us your references", "documentación", "documentacion", "right to work",
    "your cv has been viewed", "tu cv ha sido visto", "tu candidatura ha sido vista",
    "cv leído", "cv leido", "has pasado a la siguiente",
)
ACKNOWLEDGEMENT = (
    "we have received your application", "we've received your application",
    "thank you for applying", "thanks for applying", "application received",
    "thank you for your application", "hemos recibido tu candidatura",
    "hemos recibido tu solicitud", "gracias por tu candidatura", "gracias por inscribirte",
    "tu inscripción", "tu inscripcion", "candidatura recibida", "gracias por tu interés",
)
#: Mail that mentions applications without being about one of yours.
NOISE = (
    "job alert", "alerta de empleo", "new jobs for you", "jobs you may be interested",
    "ofertas que te pueden interesar", "recommended jobs", "empleos recomendados",
    "weekly digest", "newsletter", "unsubscribe from these alerts",
)

_SENTENCE = re.compile(r"(?<=[.!?])\s+|\n+")
EXCERPT_LIMIT = 300


def _cue(text: str, phrases: tuple[str, ...]) -> str | None:
    lowered = text.lower()
    return next((phrase for phrase in phrases if phrase in lowered), None)


def excerpt_around(text: str, cue: str) -> str:
    """The sentence containing ``cue``, verbatim, cut at a word boundary."""
    for sentence in _SENTENCE.split(text):
        if cue in sentence.lower():
            sentence = " ".join(sentence.split())
            if len(sentence) <= EXCERPT_LIMIT:
                return sentence
            return sentence[:EXCERPT_LIMIT].rsplit(" ", 1)[0] + " …"
    return ""


def classify(subject: str, body: str) -> tuple[MailKind | None, str]:
    """``(kind, excerpt)`` for one message; ``(None, "")`` for noise."""
    text = f"{subject}\n{body}"
    if _cue(text, NOISE) and not _cue(text, REJECTION + ADVANCE):
        return None, ""
    for kind, phrases in ((MailKind.REJECTION, REJECTION), (MailKind.ADVANCE, ADVANCE),
                          (MailKind.ACKNOWLEDGEMENT, ACKNOWLEDGEMENT)):
        cue = _cue(text, phrases)
        if cue:
            return kind, excerpt_around(body, cue) or excerpt_around(subject, cue)
    return None, ""


# ---------------------------------------------------------------------------
# Interview date and time
# ---------------------------------------------------------------------------

MONTHS = {
    "january": 1, "february": 2, "march": 3, "april": 4, "may": 5, "june": 6, "july": 7,
    "august": 8, "september": 9, "october": 10, "november": 11, "december": 12,
    "enero": 1, "febrero": 2, "marzo": 3, "abril": 4, "mayo": 5, "junio": 6, "julio": 7,
    "agosto": 8, "septiembre": 9, "setiembre": 9, "octubre": 10, "noviembre": 11,
    "diciembre": 12,
}
_MONTH = "|".join(sorted(MONTHS, key=len, reverse=True))
_NUMERIC_DATE = re.compile(r"\b(\d{1,2})[/.-](\d{1,2})(?:[/.-](\d{2,4}))?\b")
_WORDY_DATE = re.compile(rf"\b(\d{{1,2}})(?:st|nd|rd|th)?\s+(?:de\s+)?({_MONTH})\b"
                         rf"(?:\s+(?:de\s+)?(\d{{4}}))?", re.I)
_MONTH_FIRST = re.compile(rf"\b({_MONTH})\s+(\d{{1,2}})(?:st|nd|rd|th)?(?:,?\s+(\d{{4}}))?", re.I)
_TIME = re.compile(r"\b(?:at|a las|a la)?\s*(\d{1,2})[:.h](\d{2})\s*(am|pm|h)?\b|"
                   r"\b(?:at|a las)\s+(\d{1,2})\s*(am|pm|h)\b", re.I)


def _year_for(month: int, day: int, year: str | None, received: date) -> int:
    if year:
        value = int(year)
        return value + 2000 if value < 100 else value
    # "the 3rd of March" written in December means next year.
    candidate = received.year
    try:
        if date(candidate, month, day) < received:
            candidate += 1
    except ValueError:
        pass
    return candidate


def find_interview(text: str, received: date) -> tuple[datetime | None, str]:
    """A proposed interview date/time in ``text``, with the phrase it came from.

    Only a date *and* a time count: "next week" or a bare date is not
    something to put in a calendar. Day-first is assumed for numeric dates
    (13/10), which is how the ads this reads are written; a date that would
    be invalid read that way is skipped rather than flipped.
    """
    for sentence in _SENTENCE.split(text):
        clock = _TIME.search(sentence)
        if not clock:
            continue
        day = month = None
        year: str | None = None
        wordy = _WORDY_DATE.search(sentence)
        month_first = _MONTH_FIRST.search(sentence)
        numeric = _NUMERIC_DATE.search(sentence)
        if wordy:
            day, month, year = int(wordy.group(1)), MONTHS[wordy.group(2).lower()], wordy.group(3)
        elif month_first:
            month, day, year = MONTHS[month_first.group(1).lower()], int(month_first.group(2)), \
                month_first.group(3)
        elif numeric:
            day, month, year = int(numeric.group(1)), int(numeric.group(2)), numeric.group(3)
        if day is None or month is None:
            continue
        hour = int(clock.group(1) or clock.group(4))
        minute = int(clock.group(2) or 0)
        meridiem = (clock.group(3) or clock.group(5) or "").lower()
        if meridiem == "pm" and hour < 12:
            hour += 12
        if meridiem == "am" and hour == 12:
            hour = 0
        try:
            when = datetime.combine(date(_year_for(month, day, year, received), month, day),
                                    time(hour, minute))
        except ValueError:
            continue
        return when, " ".join(sentence.split())[:EXCERPT_LIMIT]
    return None, ""
