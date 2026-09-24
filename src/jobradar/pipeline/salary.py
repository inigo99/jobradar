"""Salary: currency conversion and estimation.

Two thirds of job ads publish no pay information at all, which makes a
minimum-salary filter useless unless something fills the gap. JobRadar
estimates a band from the job family's reference band, adjusted for the kind of
employer, the country the candidate would be hired in and a few signals in the
ad (see ``resources/salary_bands.yaml``), and marks it
``SalaryOrigin.ESTIMATED`` with a one-line explanation of how it got there.
The dashboard always shows that explanation, so an estimate never masquerades
as a published figure.

Conversion uses the European Central Bank's daily reference rates: free, no
key, no rate limit, and authoritative enough for "is this above my floor?".
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from xml.etree import ElementTree

import httpx

from ..config import salary_bands
from ..families import GENERAL, Family, classify, families_for
from ..models import Job, RemoteScope, Salary, SalaryOrigin, WorkMode
from ..textutils import AGENCY_MARKERS, contains_phrase

log = logging.getLogger(__name__)

ECB_DAILY = "https://www.ecb.europa.eu/stats/eurofxref/eurofxref-daily.xml"


# ---------------------------------------------------------------------------
# Currency
# ---------------------------------------------------------------------------


def _read_text(path: Path) -> str | None:
    """A cache file's content, or None if it cannot be read."""
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        log.warning("Ignoring the unreadable cache file %s: %s", path, exc)
        return None


@dataclass
class ExchangeRates:
    """Euro-based exchange rates, fetched once per day and cached on disk."""

    rates: dict[str, float] = field(default_factory=lambda: {"EUR": 1.0})
    as_of: date | None = None

    @classmethod
    def load(cls, cache_dir: Path | None = None, timeout: float = 10.0) -> ExchangeRates:
        """Today's ECB rates, falling back to the cache and then to EUR-only.

        A missing rate is never fatal: the filter chain simply keeps the job
        and warns that it could not convert the currency.
        """
        cache = (cache_dir / "ecb-rates.xml") if cache_dir else None
        body: str | None = None
        if cache and cache.exists() and _fresh(cache):
            body = _read_text(cache)
        if body is None:
            try:
                response = httpx.get(ECB_DAILY, timeout=timeout)
                response.raise_for_status()
                body = response.text
            except httpx.HTTPError as exc:
                log.warning("Could not fetch ECB rates (%s); using the cached rates if any", exc)
                body = _read_text(cache) if cache and cache.exists() else None
                if body is None:
                    log.warning("No exchange rates available: salaries in other currencies "
                                "will not be converted.")
                    return cls()
            else:
                if cache:
                    try:
                        cache.parent.mkdir(parents=True, exist_ok=True)
                        cache.write_text(body, encoding="utf-8")
                    except OSError as exc:  # a cache that cannot be written is only slower
                        log.warning("Could not cache the exchange rates in %s: %s", cache, exc)
        return cls._parse(body)

    @classmethod
    def _parse(cls, xml: str) -> ExchangeRates:
        """Rates from the ECB's XML; EUR-only if it cannot be parsed."""
        rates = {"EUR": 1.0}
        as_of: date | None = None
        try:
            root = ElementTree.fromstring(xml)
        except ElementTree.ParseError:
            return cls(rates)
        for element in root.iter():
            attrib = element.attrib
            if "time" in attrib:
                try:
                    as_of = date.fromisoformat(attrib["time"])
                except ValueError:
                    pass
            if "currency" in attrib and "rate" in attrib:
                try:
                    rates[attrib["currency"].upper()] = float(attrib["rate"])
                except ValueError:
                    continue
        return cls(rates, as_of)

    def convert(self, amount: float, source: str, target: str) -> float | None:
        """Convert between two currencies, or None if either is unknown."""
        source, target = (source or "EUR").upper(), (target or "EUR").upper()
        if source == target:
            return amount
        if source not in self.rates or target not in self.rates:
            return None
        return amount / self.rates[source] * self.rates[target]

    def note(self) -> str:
        return f"ECB reference rates of {self.as_of.isoformat()}" if self.as_of else "ECB reference rates"


def _fresh(path: Path) -> bool:
    from datetime import datetime, timedelta

    return datetime.fromtimestamp(path.stat().st_mtime) > datetime.now() - timedelta(hours=20)


# ---------------------------------------------------------------------------
# Estimation
# ---------------------------------------------------------------------------

#: Title words that map a job onto a band family. First match wins, so the
#: more specific families are listed first.
SENIOR_HINTS = ("senior", "sr.", "sénior", "lead", "principal", "staff", "iii")
LEAD_HINTS = ("head of", "director", "vp ", "manager", "team lead", "tech lead", "architect",
              "arquitecto", "jefe de", "jefa de", "responsable de", "gerente")
JUNIOR_HINTS = ("junior", "jr.", "trainee", "intern", "becario", "prácticas", "graduate",
                "entry level", "aprendiz", "auxiliar")

#: Words that make "fluent English" a real requirement.
HIGH_ENGLISH = re.compile(
    r"\b(?:fluent|advanced|proficient|native|excellent|c1|c2)\b[^.\n]{0,40}\benglish\b|"
    r"\benglish\b[^.\n]{0,40}\b(?:fluent|advanced|c1|c2|native|proficiency)\b|"
    r"\bingl[eé]s\b[^.\n]{0,40}\b(?:avanzado|fluido|nativo|c1|c2|alto)\b",
    re.I,
)
REGULATED = ("bank", "banco", "banca", "insurance", "aseguradora", "seguros", "pharma",
             "farmacéutica", "laboratorio farmacéutico", "energy", "energía", "utilities")
#: Countries whose working language is English: fluent English is no premium there.
ENGLISH_MARKETS = {"GB", "IE", "US", "CA", "AU", "NZ", "SG", "IN", "ZA", "MT"}
MAX_ADJUSTMENTS = 2


def infer_seniority(title: str | None, min_years: int | None) -> str:
    lowered = (title or "").lower()
    if any(hint in lowered for hint in LEAD_HINTS):
        return "lead"
    if any(hint in lowered for hint in JUNIOR_HINTS):
        return "junior"
    if any(hint in lowered for hint in SENIOR_HINTS):
        return "senior"
    if min_years is not None:
        if min_years >= 8:
            return "lead"
        if min_years >= 5:
            return "senior"
        if min_years <= 1:
            return "junior"
    return "mid"


def company_type(job: Job) -> tuple[str, str, float]:
    """``(key, label, factor)`` of the employer type the ad's wording suggests."""
    types = salary_bands().get("company_types") or {}
    blob = f"{job.company or ''} {job.description or ''}"
    for key, entry in types.items():
        if key == "unknown" or not isinstance(entry, dict):
            continue
        if any(contains_phrase(blob, hint) for hint in entry.get("hints") or []):
            return key, str(entry.get("label", key)), float(entry.get("factor", 1.0))
    unknown = types.get("unknown") or {}
    return "unknown", str(unknown.get("label", "company of unknown type")), \
        float(unknown.get("factor", 1.0))


def hiring_country(job: Job, home_country: str = "") -> str:
    """Where the candidate would be employed — what sets the pay level.

    A remote job open to the candidate's own country is paid at that
    country's level; anything else, at the country of the ad.
    """
    home = (home_country or "").upper()
    if home and job.work_mode == WorkMode.REMOTE:
        regions = {r.upper() for r in job.remote_regions}
        if (job.remote_scope == RemoteScope.WORLDWIDE
                or home in regions
                or (job.remote_scope == RemoteScope.UNKNOWN and not job.country)):
            return home
    return (job.country or "").upper()


def adjustments_for(job: Job, country: str) -> list[tuple[str, float]]:
    """The adjustments that apply, largest effect first, at most two."""
    table = salary_bands().get("adjustments") or {}
    text = f"{job.title or ''} {job.description or ''}"
    lowered = text.lower()
    applies = {
        "asks_many_years": job.min_years_experience is not None and job.min_years_experience >= 5,
        "asks_few_years": job.min_years_experience is not None and job.min_years_experience <= 2,
        "high_english": bool(HIGH_ENGLISH.search(text)) and country not in ENGLISH_MARKETS,
        "unnamed_client": any(marker in lowered for marker in AGENCY_MARKERS),
        "regulated_sector": any(contains_phrase(text, word) for word in REGULATED),
    }
    found = [
        (str(entry.get("label", key)), float(entry.get("factor", 1.0)))
        for key, entry in table.items()
        if isinstance(entry, dict) and applies.get(key)
    ]
    found.sort(key=lambda item: -abs(item[1] - 1.0))
    return found[:MAX_ADJUSTMENTS]


def estimate_salary(
    job: Job,
    target_currency: str = "EUR",
    rates: ExchangeRates | None = None,
    families: dict[str, Family] | None = None,
    home_country: str = "",
) -> Salary:
    """Estimate an annual gross band for a job that publishes none.

    The result is always marked as an estimate and carries the reasoning, so
    the user can see a guess for what it is — and override it if they know the
    market better, which they usually do. See ``resources/salary_bands.yaml``
    for the formula.
    """
    config = salary_bands()
    multipliers = config.get("country_multipliers", {})
    base_currency = config.get("base_currency", "EUR")
    families = families or families_for(None)

    family_key = job.family or classify(job, families)
    family = families.get(family_key) or families[GENERAL]
    seniority = infer_seniority(job.title, job.min_years_experience)
    band = family.bands.get(seniority) or families[GENERAL].bands.get(seniority)
    if not band:
        return Salary(origin=SalaryOrigin.UNKNOWN, basis="No reference band for this role.")

    _type_key, type_label, type_factor = company_type(job)
    country = hiring_country(job, home_country)
    country_factor = float(multipliers.get(country, multipliers.get("_default", 1.0)))
    adjustments = adjustments_for(job, country)
    factor = type_factor * country_factor
    for _label, value in adjustments:
        factor *= value
    low, high = _round_thousands(band[0] * factor), _round_thousands(band[1] * factor)

    currency = base_currency
    conversion = ""
    if target_currency and target_currency != base_currency and rates is not None:
        converted_low = rates.convert(low, base_currency, target_currency)
        converted_high = rates.convert(high, base_currency, target_currency)
        if converted_low and converted_high:
            low, high, currency = int(converted_low), int(converted_high), target_currency
            conversion = f" Converted from {base_currency} at the ECB rate of {rates.as_of or 'unknown date'}."

    where = country or "no anchor country"
    steps = [f"{family.label} / {seniority} band", f"{type_label} x{type_factor:g}",
             f"hired in {where} x{country_factor:g}"]
    steps += [f"{label} x{value:g}" for label, value in adjustments]
    basis = (f"Estimated: no salary published. {'; '.join(steps)}.{conversion} "
             "Edit resources/families.yaml and salary_bands.yaml to match your market.")
    return Salary(minimum=low, maximum=high, currency=currency, origin=SalaryOrigin.ESTIMATED,
                  basis=basis)


def _round_thousands(value: float) -> int:
    """Estimates are rounded to the thousand: more digits would claim precision."""
    return int(round(value / 1000.0) * 1000)


def normalise_salary(
    job: Job,
    target_currency: str,
    rates: ExchangeRates | None,
    families: dict[str, Family] | None = None,
    home_country: str = "",
) -> Salary:
    """Ensure every job carries a usable band, published or estimated."""
    salary_obj = getattr(job, "salary", None)
    if salary_obj and salary_obj.origin == SalaryOrigin.PUBLISHED and salary_obj.midpoint:
        return salary_obj
    return estimate_salary(job, target_currency, rates, families, home_country)


def annual_from_text(text: str) -> int | None:
    """Best-effort annual figure from a phrase like '3.500 € / month'."""
    match = re.search(r"(\d[\d.,]{2,})", text or "")
    if not match:
        return None
    digits = match.group(1).replace(".", "").replace(",", "")
    try:
        value = int(digits)
    except ValueError:
        return None
    return value * 12 if value < 12_000 else value
