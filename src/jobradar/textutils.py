"""Language-agnostic text helpers used by sources, the pipeline and the linter.

Nothing here needs a language model. These are the deterministic fallbacks that
keep JobRadar useful with ``--no-llm``, and they also pre-fill fields so the
model (when enabled) has less to do and costs less.
"""

from __future__ import annotations

import re
import unicodedata
from datetime import date, datetime, timedelta, timezone
from html import unescape

from .models import RemoteScope, Salary, SalaryOrigin, WorkMode

# ---------------------------------------------------------------------------
# Basic normalisation
# ---------------------------------------------------------------------------

_TAG = re.compile(r"<[^>]+>")
_WS = re.compile(r"[ \t\xa0]+")
_BLANKS = re.compile(r"\n{3,}")


def strip_html(html: str) -> str:
    """Turn an HTML fragment into readable plain text.

    Deliberately simple: job ads are prose in ``<p>``/``<li>`` soup, and a real
    parser would be another dependency for no gain.
    """
    if not html:
        return ""
    text = str(html).replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", " ", text)
    text = re.sub(r"(?s)<!--.*?-->", " ", text)
    text = re.sub(r"(?i)<(br|/p|/li|/div|/h[1-6])[^>]*>", "\n", text)
    text = re.sub(r"(?i)<li[^>]*>", "• ", text)
    text = _TAG.sub(" ", text)
    text = _WS.sub(" ", unescape(text))  # every named entity (&ntilde;…), not a few
    text = re.sub(r"(?m)^ +| +$", "", text)
    text = re.sub(r"(?m)^[• ]+$", "", text)  # bullets of empty <li>s, as in menus
    return _BLANKS.sub("\n\n", text).strip()


def normalise(value: str) -> str:
    """Lowercase, de-accent and squash punctuation — for fuzzy comparison."""
    decomposed = unicodedata.normalize("NFKD", str(value or ""))
    stripped = "".join(c for c in decomposed if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]+", " ", stripped.lower()).strip()


#: Words too common in job titles to say anything about which job it is.
_TITLE_NOISE = frozenset({"de", "del", "la", "el", "en", "y", "a", "o", "para", "con", "por",
                          "the", "of", "and", "for", "in", "at", "to", "senior", "junior"})


#: Ways the same job is named in Spanish, Catalan and English titles, compared
#: after :func:`normalise`. A searched term containing one of them also
#: matches titles that use another: "técnico de recursos humanos" finds
#: "Tècnic/a de RRHH" and "HR Specialist". Grouped by meaning, not translated
#: word for word; add a group when a field's titles need it.
TITLE_SYNONYMS: tuple[tuple[str, ...], ...] = (
    ("recursos humanos", "recursos humans", "rrhh", "rr hh", "human resources", "hr",
     "people operations", "people partner"),
    ("seleccion", "seleccio", "reclutamiento", "recruitment", "recruiter", "recruiting",
     "talent acquisition"),
    ("nominas", "nomines", "payroll"),
    ("responsable", "jefe", "manager", "head of"),
    ("administrativo", "administrativa", "administratiu", "administrative", "office assistant"),
    ("enfermero", "enfermera", "infermer", "infermera", "nurse"),
    ("profesor", "profesora", "professor", "docente", "teacher"),
    ("abogado", "abogada", "advocat", "lawyer", "solicitor"),
    ("contable", "comptable", "accountant", "bookkeeper"),
    ("camarero", "camarera", "cambrer", "waiter", "waitress"),
    ("cocinero", "cocinera", "cuiner", "cook", "chef"),
    ("conductor", "conductora", "xofer", "driver"),
    ("desarrollador", "programador", "developer", "programmer"),
    ("comercial", "sales representative", "account executive"),
)


#: Words that say what level of job it is, not which job: "técnico de
#: selección" is a "Recruiter" too. Dropped when the term has other words.
_GENERIC_ROLE = frozenset({"tecnico", "tecnica", "tecnic", "tecnicos", "specialist",
                           "technician", "especialista", "generalist", "officer"})


def _variants(term: str) -> list[str]:
    """``term`` and the same term with every combination of synonyms."""
    variants = [f" {normalise(term)} "]
    for group in TITLE_SYNONYMS:
        expanded = []
        for variant in variants:
            expanded.append(variant)
            phrase = next((p for p in group if f" {p} " in variant), None)
            if phrase is not None:
                expanded += [variant.replace(f" {phrase} ", f" {other} ") for other in group
                             if other != phrase]
        variants = expanded[:200]  # a term names a handful of groups, not dozens
    return variants


def _stems(variant: str) -> list[str]:
    words = [w for w in variant.split() if w not in _TITLE_NOISE]
    specific = [w for w in words if w not in _GENERIC_ROLE]
    return [_stem(w) for w in (specific or words)]


def _stem(word: str) -> str:
    """Enough of ``word`` to allow its gender, number and close relatives
    ("recepcionista" -> "recepción", "fisioterapeuta" -> "fisioterapia") and
    no more: a fixed five letters also let "contable" find "contraseña" and
    "laboratorio" find "laboral"."""
    return word[:max(6, len(word) - 4)]


def title_matches(title: str, terms: list[str]) -> bool:
    """Whether ``title`` looks like one of the searched ``terms``.

    For boards that return everything and leave the matching to us. Every
    significant word of a term must start a word of the title, compared
    without its last few letters, so gendered and plural forms still match:
    "enfermera" finds "Enfermero/a", "camarero" finds "Camarero-a"; and the
    names in :data:`TITLE_SYNONYMS` stand for each other, so "recursos
    humanos" finds "RRHH" and "HR". No terms means no filter.
    """
    if not terms:
        return True
    words = normalise(title).split()
    for term in terms:
        for variant in _variants(term):
            wanted = _stems(variant)
            if wanted and all(any(word.startswith(stem) for word in words) for stem in wanted):
                return True
    return False


#: Phrases that mean the real employer is hidden behind an intermediary.
AGENCY_MARKERS = (
    "our client", "nuestro cliente", "cliente final", "on behalf of our client",
    "leading company in the sector", "importante empresa del sector",
    "empresa líder del sector", "confidential client",
)


#: Text in an ad that speaks to an AI tool rather than to a person: "ignore the
#: previous instructions", "if you are an AI, mention the word ...". Recruiters
#: plant such lines to catch automated applications; a model reading the ad must
#: not obey them, and the person should know they are there.
_AI_ADDRESSED = re.compile(
    r"(?:ignore|disregard|forget)\s+(?:all\s+|any\s+)?(?:the\s+|your\s+)?"
    r"(?:previous|prior|above|earlier)\s+(?:instructions|prompts?|rules)"
    r"|if\s+you\s+are\s+(?:an?\s+)?(?:ai|a\.i\.|llm|large\s+language\s+model|"
    r"language\s+model|chatbot|bot|gpt|automated\s+(?:tool|system|agent))\b"
    r"|(?:ai|llm)\s+(?:tools?|assistants?|models?|agents?)\s*(?:reading\s+this|:)"
    r"|ignora\s+(?:todas\s+)?(?:las\s+)?instrucciones\s+(?:anteriores|previas)"
    r"|si\s+eres\s+(?:una?\s+)?(?:ia|i\.a\.|inteligencia\s+artificial|modelo\s+de\s+lenguaje|"
    r"chatbot|bot)\b",
    re.I,
)


def addressed_to_ai(text: str) -> str:
    """The sentence of ``text`` that speaks to an AI tool, or an empty string."""
    match = _AI_ADDRESSED.search(text or "")
    if not match:
        return ""
    start = max((text.rfind(stop, 0, match.start()) for stop in (".", "\n", "!", "?")),
                default=-1) + 1
    ends = [i for i in (text.find(stop, match.end()) for stop in (".", "\n", "!", "?")) if i != -1]
    end = min(ends) + 1 if ends else len(text)
    return " ".join(text[start:end].split())[:160]


#: The feminine or plural ending Spanish and Catalan ads add after a slash or in
#: brackets: "Trabajador/a social", "Enfermeros/as", "Técnico(a)".
_GENDER_ENDING = re.compile(r"(?<=\w\w\w)(?:/|\()(?:a|as|o|os|es|ra|ras)\)?(?!\w)", re.I)


def ungendered(text: str) -> str:
    """``text`` without the slash endings, so "Trabajador/a social" reads as
    "Trabajador social" and a keyword written once matches both forms."""
    return _GENDER_ENDING.sub("", text or "")


def contains_phrase(text: str, phrase: str) -> bool:
    """Whether ``phrase`` appears in ``text`` as whole words.

    Never a raw substring: "java" is inside "javascript" and "alan" inside
    "talan", and a filter that matches those drops good jobs in silence. A
    trailing ``*`` asks for a prefix instead ("practic*" matches "practicas"
    and "practicante").
    """
    wanted = str(phrase or "").strip()
    prefix = wanted.endswith("*")
    needle = normalise(wanted.rstrip("*"))
    if not needle:
        return False
    haystack = f" {normalise(text)} "
    return f" {needle}" in haystack if prefix else f" {needle} " in haystack


def slugify(value: str, max_length: int = 48) -> str:
    """Filesystem-safe slug, used for generated CV filenames."""
    text = normalise(str(value or "")).replace(" ", "_")
    return re.sub(r"_+", "_", text).strip("_")[:max_length] or "untitled"


def token_set(value: str) -> set[str]:
    return {t for t in normalise(value).split() if len(t) > 2}


# ---------------------------------------------------------------------------
# Language detection
# ---------------------------------------------------------------------------

# Small stop-word profiles. Enough to tell apart the languages job ads are
# actually written in, without pulling in a detection library.
_STOPWORDS: dict[str, set[str]] = {
    "en": {"the", "and", "for", "with", "you", "our", "are", "will", "your", "have", "team"},
    "es": {"de", "que", "para", "con", "los", "las", "una", "del", "por", "experiencia", "empresa",
           "el", "y", "al", "como"},
    "fr": {"le", "les", "des", "pour", "avec", "vous", "nous", "une", "dans", "notre", "sur"},
    "de": {"und", "der", "die", "das", "mit", "für", "sie", "wir", "ein", "eine", "bei"},
    "pt": {"de", "que", "para", "com", "uma", "dos", "das", "você", "nossa", "experiência"},
    "it": {"di", "che", "per", "con", "una", "del", "delle", "nostro", "esperienza", "sviluppo"},
    "nl": {"de", "het", "een", "van", "voor", "met", "wij", "je", "onze", "werken"},
}


#: The same words as the text is compared: without accents ("für" -> "fur").
_FOLDED_STOPWORDS = {lang: {normalise(word) for word in words} for lang, words in _STOPWORDS.items()}


def detect_language(text: str, default: str = "en") -> str:
    """Best-effort ISO-639-1 code for ``text``.

    Job ads mix English technical vocabulary into every language, so the score
    is a plain stop-word count: the winner is whichever language contributes
    most function words.
    """
    # Addresses carry words of their own: "example.com" is not Portuguese "com".
    plain = re.sub(r"\S+@\S+|https?://\S+|www\.\S+|\b[\w.-]+\.(?:com|es|org|net|eu)\b", " ",
                   str(text or ""))
    tokens = normalise(plain).split()
    if len(tokens) < 12:
        return default
    counts = {lang: sum(1 for t in tokens if t in words) for lang, words in _FOLDED_STOPWORDS.items()}
    best = max(counts, key=lambda k: counts[k])
    return best if counts[best] >= 3 else default


# ---------------------------------------------------------------------------
# Work mode
# ---------------------------------------------------------------------------
#
# Ported from a personal radar that ran these patterns against real ads every
# day, with the bugs it hit written down next to the fix. Three lessons shape
# them, and each one cost real jobs before it was learnt:
#
# * Match whole words. "remote" as a bare word is the commonest way an ad says
#   it ("This is a remote position"), so it has to be in; but as a substring it
#   also fires inside words that mean something else.
# * Read negations. "This is not a remote position" contains "remote".
# * Look at the whole text, not the first few hits. An ad that says "remote"
#   three times in the header and "2 days a week in the office" further down is
#   hybrid, and so is "work from home (2 days per week)".
#
# Everything is matched against folded text (lower case, no accents), so the
# patterns are written without accents.

_RE_REMOTE = re.compile(
    r"(100\s*%?\s*remot|fully remote|full[- ]remote|remote[- ]first|"
    r"totalmente remot|completamente remot|en remoto|teletrabajo|teletravail|"
    r"trabajo remot|remote work|work from home|work remotely|homeoffice|home office|"
    r"\bremote\b|\bremoto\b|\bremota\b)"
)
_RE_HYBRID = re.compile(
    r"(hibrid|hybrid|\d\s*dias? (en|de|a la) (oficina|casa|semana)|"
    r"days? (in|at|per week in) (the )?office|"
    r"office[^.]{0,40}\d+\s*days?\s*(a|per)\s*week|"
    r"\d+\s*days?\s*(a|per)\s*week[^.]{0,40}office|"
    r"dias? (de )?presencialidad|modelo hibrido|parcialmente remot|"
    r"remoto parcial|combinacion de (teletrabajo|remoto)|"
    r"flexib\w* .{0,25}remot|some days? (a week )?(in|at) (the )?office|"
    r"office[- ]based .{0,25}(flexib|remot)|"
    # "work from home (2 days per week)": how many days at HOME, the inverse
    # of "N days in the office". Limited to 1-4 on purpose — "remote 5 days a
    # week" is a full remote week, not hybrid.
    r"(work(ing)? from home|remote(ly)?)[^.]{0,40}[1-4]\s*days?\s*(a|per)\s*week|"
    r"[1-4]\s*days?\s*(a|per)\s*week[^.]{0,40}(work(ing)? from home|remote(ly)?))"
)
_RE_ONSITE = re.compile(
    r"(presencial|on-?site|in-?person|en la oficina|nuestras? oficinas?|vor ort|"
    r"not remote|no remote|not a remote|no es (un puesto )?remoto|"
    r"no (se admite|se permite|admite|permite) (el )?teletrabajo|"
    r"sin opcion de teletrabajo|acudir a (la )?oficina|"
    r"asistencia (a|diaria) (la )?oficina|desde (la|nuestra) oficina|"
    r"from (our|the) office|based in (our|the) office|office[- ]based role\b)"
)
_RE_NOT_REMOTE = re.compile(
    r"(not remote|no remote|not a remote|no es (un puesto )?remoto|"
    r"no (se admite|se permite|admite|permite) (el )?teletrabajo|"
    r"sin opcion de teletrabajo)"
)
#: "No hybrid, no office" is a remote ad saying so twice.
_RE_NOT_HYBRID = re.compile(r"\b(?:no|not|non|sin|nada de)[- ](?:hybrid|hibrid)\w*")
_RE_ANY_MODE = re.compile(
    _RE_REMOTE.pattern + "|" + _RE_HYBRID.pattern + "|" + _RE_ONSITE.pattern
)


def fold(text: str) -> str:
    """Lower case without accents, punctuation kept (patterns rely on '.')."""
    decomposed = unicodedata.normalize("NFKD", str(text or ""))
    return "".join(c for c in decomposed if not unicodedata.combining(c)).lower()


def detect_work_mode(text: str, location: str = "") -> WorkMode:
    """Classify a posting as remote / hybrid / on-site from its own words.

    Returns ``UNKNOWN`` when the text says nothing about it — silence is not a
    contradiction, and the caller decides whether to trust the board's tag.
    """
    blob = _RE_NOT_HYBRID.sub(" ", fold(f"{text} . {location}"))
    remote = bool(_RE_REMOTE.search(blob))
    hybrid = bool(_RE_HYBRID.search(blob))
    onsite = bool(_RE_ONSITE.search(blob))
    if _RE_NOT_REMOTE.search(blob) and not hybrid:
        return WorkMode.ONSITE
    if remote and not hybrid and not onsite:
        return WorkMode.REMOTE
    if remote or hybrid:
        # "remote" next to office days is a perk, not the mode.
        return WorkMode.HYBRID
    if onsite:
        return WorkMode.ONSITE
    return WorkMode.UNKNOWN


def work_mode_evidence(text: str, limit: int = 3) -> list[str]:
    """Up to ``limit`` literal snippets where the ad talks about work mode.

    Kept next to the verdict so the user can check the sentence the decision
    came from instead of trusting the label.
    """
    blob = re.sub(r"\s+", " ", fold(text))
    snippets: list[str] = []
    for match in _RE_ANY_MODE.finditer(blob):
        snippet = blob[max(0, match.start() - 55): match.start() + 80].strip()
        if snippet not in snippets:
            snippets.append(snippet)
        if len(snippets) >= limit:
            break
    return snippets


# ---------------------------------------------------------------------------
# Remote scope — where a remote job actually lets you live
# ---------------------------------------------------------------------------

_WORLDWIDE = ("anywhere in the world", "work from anywhere", "worldwide", "globally remote",
              "fully distributed, any timezone", "any country")
_REGIONS = {
    "EMEA": ("emea",),
    "EU": ("european union", "eu-based", "within the eu", "eu only", "europe only",
           "anywhere in europe", "european timezones", "cet timezone", "cet +/-",
           "union europea"),
    "LATAM": ("latam", "latin america"),
    "APAC": ("apac", "asia pacific"),
    "NORAM": ("north america", "us or canada"),
}
#: A residency or work-permit condition, and what follows it. The phrase is the
#: same grammatical shape whether it restricts ("must reside in the US") or
#: opens up ("eligible to work anywhere in the EU"), so the countries it names
#: are read out of it rather than guessed from the phrase alone.
_COUNTRY_LOCK = re.compile(
    r"(must (?:be )?(?:located|based|resident|reside)|must reside|eligible to work|"
    r"authori[sz]ed to work|work authori[sz]ation|right to work|residents? of|"
    r"only accepting|us[- ]only|usa only|united states only|uk only|us[- ]based only|"
    r"residir en|imprescindible residir|residencia en|resident in)[^.;\n]{0,70}"
)
_EUROPE_IN_LOCK = re.compile(r"\b(eu|e\.u\.|european union|europe|emea|union europea|europa)\b")
_US_IN_LOCK = re.compile(r"(\bthe us\b|\bus[- ](?:only|based)\b|\bu\.s\.a?\.?|\busa\b|united states)")
_UK_IN_LOCK = re.compile(r"(\bthe uk\b|\buk[- ](?:only|based)\b|\buk\b|united kingdom|great britain)")
#: Names ads use that the country registry (English names only) does not.
_EXTRA_COUNTRY_NAMES = {
    "espana": "ES", "francia": "FR", "alemania": "DE", "italia": "IT", "portugal": "PT",
    "paises bajos": "NL", "holanda": "NL", "irlanda": "IE", "belgica": "BE",
    "suiza": "CH", "polonia": "PL", "reino unido": "GB", "estados unidos": "US",
    "mexico": "MX", "deutschland": "DE", "espagne": "ES", "allemagne": "DE",
}


def _country_names() -> dict[str, str]:
    from .config import countries  # local import: config imports models too

    names = dict(_EXTRA_COUNTRY_NAMES)
    for code, info in (countries() or {}).items():
        name = fold(str((info or {}).get("name") or ""))
        if name:
            names[name] = str(code).upper()
    return names


def _countries_in(snippet: str) -> list[str]:
    codes: list[str] = []
    if _US_IN_LOCK.search(snippet):
        codes.append("US")
    if _UK_IN_LOCK.search(snippet):
        codes.append("GB")
    for name, code in _country_names().items():
        if re.search(rf"\b{re.escape(name)}\b", snippet) and code not in codes:
            codes.append(code)
    return codes


def detect_remote_scope(text: str) -> tuple[RemoteScope, list[str]]:
    """Infer where a remote job may be performed from.

    Returns the scope plus what it is limited to: region names for ``REGION``,
    ISO country codes for ``COUNTRY`` (empty when the ad states a residency
    condition without naming where — the filter keeps those and flags them,
    because a rule that guesses which way that sentence goes throws away good
    jobs). ``UNKNOWN`` is a legitimate and common answer.
    """
    blob = fold(text)
    if any(hint in blob for hint in _WORLDWIDE):
        return RemoteScope.WORLDWIDE, []
    regions = [name for name, hints in _REGIONS.items()
               if any(re.search(rf"\b{re.escape(h)}\b", blob) for h in hints)]
    lock = _COUNTRY_LOCK.search(blob)
    if lock and not regions and _EUROPE_IN_LOCK.search(lock.group(0)):
        regions = ["EU"]
    if regions:
        return RemoteScope.REGION, regions
    if lock:
        return RemoteScope.COUNTRY, _countries_in(lock.group(0))
    return RemoteScope.UNKNOWN, []


def remote_scope_evidence(text: str) -> str:
    """The literal residency/work-permit sentence, if the ad has one."""
    lock = _COUNTRY_LOCK.search(fold(text))
    return lock.group(0).strip() if lock else ""


# ---------------------------------------------------------------------------
# Experience requirement
# ---------------------------------------------------------------------------

_YEARS_UNIT = r"(?:years?|yrs|anos|ans|jahre)"
#: Ranges are collapsed to their lower bound first: "between 6 and 9 years of
#: experience" asks for 6, and without this the "9 years of experience" inside
#: it would be read as the requirement.
_YEAR_RANGES = (
    re.compile(r"(?:entre|between|zwischen)\s*(\d{1,2})\s*(?:y|and|und|-|–|to|a)\s*\d{1,2}"),
    re.compile(rf"(\d{{1,2}})\s*(?:-|–|to)\s*\d{{1,2}}(?=\s*\+?\s*{_YEARS_UNIT})"),
)
_YEARS_PATTERNS = tuple(re.compile(p) for p in (
    rf"(?:at least|minimum(?: of)?|a minimum of|min\.?|more than|over)\s*(\d{{1,2}})\s*\+?\s*{_YEARS_UNIT}",
    r"(?:mas de|al menos|minim[oa](?:\s+de)?|desde|a partir de)\s*(\d{1,2})\s*anos",
    rf"(\d{{1,2}})\s*\+\s*{_YEARS_UNIT}",
    rf"(\d{{1,2}})\s*(?:or more|o mas|ou plus|oder mehr)\s*{_YEARS_UNIT}",
    rf"(\d{{1,2}})\s*{_YEARS_UNIT}\s+(?:of\s+)?(?:professional\s+|relevant\s+|hands-on\s+|total\s+|proven\s+)?"
    r"(?:experience|experiencia|d'experience|erfahrung)",
    r"(\d{1,2})\s*anos\s+de\s+experiencia",
    # The unit is optional here ("experiencia minima: 2"), so months are ruled
    # out explicitly: "experiencia minima de 6 meses" is half a year, not six.
    r"experiencia\s+minima[^0-9]{0,20}(\d{1,2})(?!\d|\s*(?:mes|month|semana|week|dia|day|hora|hour))",
))


#: Above this, "a partir de 25 años" is an age, not experience: public
#: employment ads state age limits ("desde 25 años", "edad mínima 25 años")
#: in the same words.
MAX_YEARS_ASKED = 15
#: Age conditions, removed before experience is looked for.
_AGE = re.compile(r"\bedad\b[^.;\n]{0,40}|\b(?:mayor|menor)(?:es)?\s+de\s+\d{1,2}\s*anos")


def extract_min_years(text: str) -> int | None:
    """Years of experience the ad demands, if it says.

    When the ad states several, the largest wins: "2 years with Python and 5
    years of experience overall" asks for 5 — the overall figure is the one
    that ends an application. Ranges count by their lower bound.
    """
    blob = _AGE.sub(" ", fold(text))
    for pattern in _YEAR_RANGES:
        blob = pattern.sub(r"\1+", blob)
    found: list[int] = []
    for pattern in _YEARS_PATTERNS:
        found.extend(int(m) for m in pattern.findall(blob) if m.isdigit())
    sane = [y for y in found if 0 < y <= MAX_YEARS_ASKED]
    return max(sane) if sane else None


# ---------------------------------------------------------------------------
# Salary
# ---------------------------------------------------------------------------

_CURRENCY_SYMBOLS = {"€": "EUR", "$": "USD", "£": "GBP", "chf": "CHF", "zł": "PLN", "kr": "SEK"}
_CURRENCY_CODES = ("EUR", "USD", "GBP", "CHF", "CAD", "AUD", "PLN", "SEK", "NOK", "DKK",
                   "CZK", "HUF", "BGN", "ISK",  # not RON: "ron" is Spanish for rum
                   "BRL", "MXN", "ARS", "COP", "CLP", "INR", "SGD", "NZD", "ZAR")

_AMOUNT = r"(\d{1,3}(?:[.,\s]\d{3})+|\d{2,3}(?:[.,]\d)?\s?[kK]|\d{4,7})"
_RANGE = re.compile(rf"{_AMOUNT}\s*(?:-|–|—|to|a|hasta|bis)\s*{_AMOUNT}")


def _to_int(raw: str) -> int | None:
    """Parse '45.000', '45,000', '45k' or '45000' into an integer."""
    token = str(raw).strip().replace(" ", "")
    multiplier = 1
    if token.lower().endswith("k"):
        multiplier = 1000
        token = token[:-1]
    token = token.replace(".", "").replace(",", ".")
    try:
        return int(round(float(token) * multiplier))
    except ValueError:
        return None


def detect_currency(text: str, default: str = "EUR") -> str:
    blob = str(text or "")
    for code in _CURRENCY_CODES:
        if re.search(rf"\b{code}\b", blob, re.IGNORECASE):
            return code
    for symbol, code in _CURRENCY_SYMBOLS.items():
        if symbol in blob.lower():
            return code
    return default


def extract_salary(text: str, default_currency: str = "EUR") -> Salary | None:
    """Pull a published annual gross band out of an ad's own words.

    Monthly and hourly figures are annualised; anything that lands outside a
    plausible annual range is discarded rather than guessed at, because a wrong
    published figure is worse than no figure.
    """
    if not text:
        return None
    blob = str(text).replace(" ", " ")
    currency = detect_currency(blob, default_currency)
    lowered = blob.lower()
    per_month = any(w in lowered for w in ("per month", "/month", "mensual", "al mes", "monatlich", "brutto/monat"))
    per_hour = any(w in lowered for w in ("per hour", "/hour", "hourly", "por hora", "/h "))

    match = _RANGE.search(blob)
    minimum = maximum = None
    if match:
        minimum, maximum = _to_int(match.group(1)), _to_int(match.group(2))
    else:
        single = re.search(rf"{_AMOUNT}\s*(?:€|eur|usd|\$|gbp|£)", blob, re.IGNORECASE) or re.search(
            rf"(?:€|eur|usd|\$|gbp|£)\s*{_AMOUNT}", blob, re.IGNORECASE
        )
        if single:
            minimum = maximum = _to_int(single.group(1))

    if minimum is None:
        return None
    if maximum is None or maximum < minimum:
        maximum = minimum

    factor = 12 if per_month else (1720 if per_hour else 1)
    minimum, maximum = minimum * factor, maximum * factor

    # Sanity window: annual gross pay outside this range is almost certainly a
    # misparse (a phone number, an employee count, a funding round).
    if not (8_000 <= minimum <= 1_000_000) or maximum > 2_000_000:
        return None

    return Salary(
        minimum=minimum,
        maximum=maximum,
        currency=currency,
        origin=SalaryOrigin.PUBLISHED,
        basis="Published in the job ad.",
    )


# ---------------------------------------------------------------------------
# Dates
# ---------------------------------------------------------------------------


def parse_date(value: object) -> date | None:
    """Parse the many date shapes job APIs return, or None."""
    if value is None or value == "":
        return None
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, (int, float)):  # epoch seconds
        try:
            return datetime.fromtimestamp(float(value), tz=timezone.utc).date()
        except (OverflowError, OSError, ValueError):
            return None
    text = str(value).strip()
    for pattern in ("%Y-%m-%d", "%Y/%m/%d", "%d/%m/%Y", "%d-%m-%Y", "%a, %d %b %Y %H:%M:%S %z",
                    "%a, %d %b %Y %H:%M:%S %Z", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(text, pattern).date()
        except ValueError:
            continue
    try:  # ISO-8601 with timezone, the most common shape
        return datetime.fromisoformat(text.replace("Z", "+00:00")).date()
    except ValueError:
        pass
    relative = re.match(r"(?:hace\s*)?(\d{1,3})\s*(d|day|days|día|dias|días|h|hour|hours|w|week|weeks)",
                        text.lower())
    if relative:
        amount, unit = int(relative.group(1)), relative.group(2)
        days = amount * (7 if unit.startswith("w") else (1 / 24 if unit.startswith("h") else 1))
        return (datetime.now(timezone.utc) - timedelta(days=days)).date()
    return None
