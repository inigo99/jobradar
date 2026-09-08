"""Salary: currency conversion and estimation.

Two thirds of job ads publish no pay information at all, which makes a
minimum-salary filter useless unless something fills the gap. JobRadar
estimates a band from a reference table, adjusted for the country, and marks it
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
from ..models import Job, Salary, SalaryOrigin

log = logging.getLogger(__name__)

ECB_DAILY = "https://www.ecb.europa.eu/stats/eurofxref/eurofxref-daily.xml"


# ---------------------------------------------------------------------------
# Currency
# ---------------------------------------------------------------------------


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
            body = cache.read_text(encoding="utf-8")
        if body is None:
            try:
                response = httpx.get(ECB_DAILY, timeout=timeout)
                response.raise_for_status()
                body = response.text
                if cache:
                    cache.parent.mkdir(parents=True, exist_ok=True)
                    cache.write_text(body, encoding="utf-8")
            except httpx.HTTPError as exc:
                log.warning("Could not fetch ECB rates (%s); currency conversion disabled", exc)
                if cache and cache.exists():
                    body = cache.read_text(encoding="utf-8")
                else:
                    return cls()
        return cls._parse(body)

    @classmethod
    def _parse(cls, xml: str) -> ExchangeRates:
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
FAMILY_HINTS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("machine_learning", ("machine learning", "ml engineer", "ai engineer", "deep learning",
                          "computer vision", "nlp", "genai", "llm", "inteligencia artificial")),
    ("data_science", ("data scientist", "científico de datos", "cientifico de datos", "statistician",
                      "analytics")),
    ("data_engineering", ("data engineer", "ingeniero de datos", "analytics engineer", "etl")),
    ("devops", ("devops", "sre", "site reliability", "platform engineer", "infrastructure", "cloud engineer")),
    ("product", ("product manager", "product owner", "gestor de producto")),
    ("design", ("designer", "diseñador", "ux", "ui ")),
    ("marketing", ("marketing", "seo", "growth", "content")),
    ("sales", ("sales", "ventas", "account executive", "business development")),
    ("operations", ("operations", "logistics", "supply chain", "administrativo")),
    ("software_engineering", ("developer", "engineer", "programador", "desarrollador", "backend",
                              "frontend", "full stack", "software")),
)

SENIOR_HINTS = ("senior", "sr.", "sénior", "lead", "principal", "staff", "iii")
LEAD_HINTS = ("head of", "director", "vp ", "manager", "team lead", "tech lead", "architect", "arquitecto")
JUNIOR_HINTS = ("junior", "jr.", "trainee", "intern", "becario", "prácticas", "graduate", "entry level")


def infer_family(title: str, description: str = "") -> str:
    blob = f"{title} {description[:400]}".lower()
    for family, hints in FAMILY_HINTS:
        if any(hint in blob for hint in hints):
            return family
    return "generic"


def infer_seniority(title: str, min_years: int | None) -> str:
    lowered = title.lower()
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


def estimate_salary(job: Job, target_currency: str = "EUR", rates: ExchangeRates | None = None) -> Salary:
    """Estimate an annual gross band for a job that publishes none.

    The result is always marked as an estimate and carries the reasoning, so
    the user can see a guess for what it is — and override it if they know the
    market better, which they usually do.
    """
    config = salary_bands()
    families = config.get("families", {})
    multipliers = config.get("country_multipliers", {})
    base_currency = config.get("base_currency", "EUR")

    family = infer_family(job.title, job.description)
    seniority = infer_seniority(job.title, job.min_years_experience)
    band = (families.get(family) or families.get("generic", {})).get(seniority)
    if not band:
        return Salary(origin=SalaryOrigin.UNKNOWN, basis="No reference band for this role.")

    country = (job.country or "").upper()
    multiplier = multipliers.get(country, multipliers.get("_default", 1.0))
    low, high = int(band[0] * multiplier), int(band[1] * multiplier)

    currency = base_currency
    if target_currency and target_currency != base_currency and rates is not None:
        converted_low = rates.convert(low, base_currency, target_currency)
        converted_high = rates.convert(high, base_currency, target_currency)
        if converted_low and converted_high:
            low, high, currency = int(converted_low), int(converted_high), target_currency

    where = country or "no anchor country (remote)"
    basis = (
        f"Estimated: no salary published. Reference band for {family.replace('_', ' ')} "
        f"/ {seniority} adjusted for {where} (x{multiplier:g}). Edit "
        f"resources/salary_bands.yaml to match your market."
    )
    return Salary(minimum=low, maximum=high, currency=currency, origin=SalaryOrigin.ESTIMATED, basis=basis)


def normalise_salary(job: Job, target_currency: str, rates: ExchangeRates | None) -> Salary:
    """Ensure every job carries a usable band, published or estimated."""
    if job.salary.origin == SalaryOrigin.PUBLISHED and job.salary.midpoint:
        return job.salary
    return estimate_salary(job, target_currency, rates)


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
