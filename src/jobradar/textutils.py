"""Language-agnostic text helpers used by sources, the pipeline and the linter.

Nothing here needs a language model. These are the deterministic fallbacks that
keep JobRadar useful with ``--no-llm``, and they also pre-fill fields so the
model (when enabled) has less to do and costs less.
"""

from __future__ import annotations

import re
import unicodedata
from datetime import date, datetime, timedelta, timezone

from .models import RemoteScope, Salary, SalaryOrigin, WorkMode

# ---------------------------------------------------------------------------
# Basic normalisation
# ---------------------------------------------------------------------------

_TAG = re.compile(r"<[^>]+>")
_WS = re.compile(r"[ \t\xa0]+")
_BLANKS = re.compile(r"\n{3,}")

_ENTITIES = {
    "&nbsp;": " ", "&amp;": "&", "&lt;": "<", "&gt;": ">", "&quot;": '"',
    "&#39;": "'", "&rsquo;": "’", "&ndash;": "–", "&mdash;": "—", "&euro;": "€",
}


def strip_html(html: str) -> str:
    """Turn an HTML fragment into readable plain text.

    Deliberately simple: job ads are prose in ``<p>``/``<li>`` soup, and a real
    parser would be another dependency for no gain.
    """
    if not html:
        return ""
    text = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", " ", html)
    text = re.sub(r"(?i)<(br|/p|/li|/div|/h[1-6])[^>]*>", "\n", text)
    text = re.sub(r"(?i)<li[^>]*>", "• ", text)
    text = _TAG.sub(" ", text)
    for entity, char in _ENTITIES.items():
        text = text.replace(entity, char)
    text = re.sub(r"&#(\d+);", lambda m: chr(int(m.group(1))), text)
    text = _WS.sub(" ", text)
    return _BLANKS.sub("\n\n", text).strip()


def normalise(value: str) -> str:
    """Lowercase, de-accent and squash punctuation — for fuzzy comparison."""
    decomposed = unicodedata.normalize("NFKD", value or "")
    stripped = "".join(c for c in decomposed if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]+", " ", stripped.lower()).strip()


def slugify(value: str, max_length: int = 48) -> str:
    """Filesystem-safe slug, used for generated CV filenames."""
    text = normalise(value).replace(" ", "_")
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
    "es": {"de", "que", "para", "con", "los", "las", "una", "del", "por", "experiencia", "empresa"},
    "fr": {"le", "les", "des", "pour", "avec", "vous", "nous", "une", "dans", "notre", "sur"},
    "de": {"und", "der", "die", "das", "mit", "für", "sie", "wir", "ein", "eine", "bei"},
    "pt": {"de", "que", "para", "com", "uma", "dos", "das", "você", "nossa", "experiência"},
    "it": {"di", "che", "per", "con", "una", "del", "delle", "nostro", "esperienza", "sviluppo"},
    "nl": {"de", "het", "een", "van", "voor", "met", "wij", "je", "onze", "werken"},
}


def detect_language(text: str, default: str = "en") -> str:
    """Best-effort ISO-639-1 code for ``text``.

    Job ads mix English technical vocabulary into every language, so the score
    is a plain stop-word count: the winner is whichever language contributes
    most function words.
    """
    tokens = normalise(text).split()
    if len(tokens) < 12:
        return default
    counts = {lang: sum(1 for t in tokens if t in words) for lang, words in _STOPWORDS.items()}
    best = max(counts, key=lambda k: counts[k])
    return best if counts[best] >= 3 else default


# ---------------------------------------------------------------------------
# Work mode
# ---------------------------------------------------------------------------

_REMOTE_HINTS = (
    "100% remote", "fully remote", "remote-first", "work from home", "teletrabajo",
    "totalmente remoto", "en remoto", "télétravail", "homeoffice", "home office",
    "remote position", "remote role", "trabajo remoto", "remoto",
)
_HYBRID_HINTS = ("hybrid", "híbrido", "hibrido", "hybride", "hybrid working", "2 days in office",
                 "3 days in the office", "modelo híbrido")
_ONSITE_HINTS = ("on-site", "onsite", "presencial", "in office", "in-office", "vor ort")


def detect_work_mode(text: str, location: str = "") -> WorkMode:
    """Classify a posting as remote / hybrid / on-site from its own words.

    Hybrid is checked first on purpose: ads that mean hybrid almost always also
    contain the word "remote", and taking "remote" at face value is the single
    most common way a job radar wastes its owner's time.
    """
    blob = f"{text} {location}".lower()
    if any(hint in blob for hint in _HYBRID_HINTS):
        return WorkMode.HYBRID
    if any(hint in blob for hint in _REMOTE_HINTS):
        return WorkMode.REMOTE
    if any(hint in blob for hint in _ONSITE_HINTS):
        return WorkMode.ONSITE
    return WorkMode.UNKNOWN


# ---------------------------------------------------------------------------
# Remote scope — where a remote job actually lets you live
# ---------------------------------------------------------------------------

_WORLDWIDE = ("anywhere in the world", "work from anywhere", "worldwide", "globally remote",
              "fully distributed, any timezone", "any country")
_REGIONS = {
    "EMEA": ("emea",),
    "EU": ("european union", "eu-based", "within the eu", "eu only", "europe only",
           "anywhere in europe", "european timezones", "cet timezone", "cet +/-"),
    "LATAM": ("latam", "latin america"),
    "APAC": ("apac", "asia pacific"),
    "NORAM": ("north america", "us or canada"),
}
_COUNTRY_LOCK = (
    "us only", "usa only", "united states only", "must be based in the us",
    "us-based only", "authorized to work in the us", "authorised to work in the uk",
    "uk only", "must reside in", "must be located in", "residents of",
    "eligible to work in", "work authorization in",
)


def detect_remote_scope(text: str) -> tuple[RemoteScope, list[str]]:
    """Infer where a remote job may be performed from.

    Returns the scope plus any named regions. ``UNKNOWN`` is a legitimate and
    common answer; the pipeline turns it into an alert on the job rather than
    silently guessing, so the user asks in the first call instead of finding
    out after three interviews.
    """
    blob = (text or "").lower()
    if any(hint in blob for hint in _WORLDWIDE):
        return RemoteScope.WORLDWIDE, []
    regions = [name for name, hints in _REGIONS.items() if any(h in blob for h in hints)]
    if regions:
        return RemoteScope.REGION, regions
    if any(hint in blob for hint in _COUNTRY_LOCK):
        return RemoteScope.COUNTRY, []
    return RemoteScope.UNKNOWN, []


# ---------------------------------------------------------------------------
# Experience requirement
# ---------------------------------------------------------------------------

_YEARS_PATTERNS = (
    r"(?:at least|minimum(?: of)?|min\.?|more than|over)\s*(\d{1,2})\+?\s*(?:years|yrs|años|ans|jahre)",
    r"(\d{1,2})\+?\s*(?:years|yrs|años|ans|jahre)[^.\n]{0,30}(?:experience|experiencia|expérience|erfahrung)",
    r"al menos\s*(\d{1,2})\s*años",
    r"(\d{1,2})\s*[-–]\s*\d{1,2}\s*(?:years|años)",
)


def extract_min_years(text: str) -> int | None:
    """Smallest number of years of experience the ad demands, if it says."""
    blob = (text or "").lower()
    found: list[int] = []
    for pattern in _YEARS_PATTERNS:
        found.extend(int(m) for m in re.findall(pattern, blob) if m.isdigit())
    sane = [y for y in found if 0 < y <= 25]
    return min(sane) if sane else None


# ---------------------------------------------------------------------------
# Salary
# ---------------------------------------------------------------------------

_CURRENCY_SYMBOLS = {"€": "EUR", "$": "USD", "£": "GBP", "chf": "CHF", "zł": "PLN", "kr": "SEK"}
_CURRENCY_CODES = ("EUR", "USD", "GBP", "CHF", "CAD", "AUD", "PLN", "SEK", "NOK", "DKK",
                   "BRL", "MXN", "ARS", "COP", "CLP", "INR", "SGD", "NZD", "ZAR")

_AMOUNT = r"(\d{1,3}(?:[.,\s]\d{3})+|\d{2,3}(?:[.,]\d)?\s?[kK]|\d{4,7})"
_RANGE = re.compile(rf"{_AMOUNT}\s*(?:-|–|—|to|a|hasta|bis)\s*{_AMOUNT}")


def _to_int(raw: str) -> int | None:
    """Parse '45.000', '45,000', '45k' or '45000' into an integer."""
    token = raw.strip().replace(" ", "")
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
    blob = text or ""
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
    blob = text.replace(" ", " ")
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
