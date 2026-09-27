"""Sub-national regions: NUTS codes <-> the names people type.

Some boards say where a job is only as a region code (EURES gives a NUTS-3
code, a province in Spain) and search only by NUTS-2. This module turns those
codes into names for the job's location, and the user's areas ("Pamplona",
"Barcelona") into codes a board can search by and province names a location
can be matched against. The data is ``resources/regions.yaml``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache

from .config import load_resource
from .textutils import contains_phrase, normalise


@dataclass(frozen=True)
class Province:
    code: str      # NUTS-3
    name: str
    region: str    # NUTS-2 code
    region_name: str
    country: str
    places: tuple[str, ...] = ()


@lru_cache(maxsize=1)
def _provinces() -> dict[str, Province]:
    provinces: dict[str, Province] = {}
    for country, block in load_resource("regions.yaml").items():
        regions = (block or {}).get("regions") or {}
        for code, entry in ((block or {}).get("provinces") or {}).items():
            code = str(code).upper()
            region = code[:4]
            provinces[code] = Province(
                code=code, name=str(entry["name"]), region=region,
                region_name=str(regions.get(region, "")), country=str(country).upper(),
                places=tuple(str(p) for p in entry.get("places") or ()),
            )
    return provinces


def province(code: str) -> Province | None:
    return _provinces().get(str(code or "").upper())


def location_for(code: str, country_name: str) -> str:
    """"Navarra, Spain" for a NUTS-3 code; the country alone when unknown.

    The NUTS-2 region is added when its name differs ("Barcelona, Cataluña,
    Spain"), so an area typed as either still matches.
    """
    found = province(code)
    if not found:
        return country_name
    parts = [found.name]
    if found.region_name and normalise(found.region_name) != normalise(found.name):
        parts.append(found.region_name)
    parts.append(country_name)
    return ", ".join(p for p in parts if p)


def names_a_place(location: str, country: str) -> bool:
    """Whether a location says more than its country ("Spain", "ES")."""
    from .config import country_info  # local import: config imports this

    plain = normalise(location or "")
    if not plain:
        return False
    return not country or plain not in {
        normalise(country), normalise(country_info(country).get("name", ""))}


def provinces_for(area: str) -> list[Province]:
    """The provinces an area names: itself, its capital or a town in it, or a
    NUTS-2 region (every province in it)."""
    wanted = normalise(area)
    if not wanted:
        return []
    found = []
    for item in _provinces().values():
        names = [item.name, *item.name.split("/"), *item.places]
        if any(normalise(name) == wanted for name in names) or normalise(item.region_name) == wanted:
            found.append(item)
    return found


def area_names(areas: list[str]) -> list[str]:
    """``areas`` plus the province each one lies in, for matching a location
    that names only the province ("Pamplona" -> also "Navarra")."""
    names = list(areas)
    for area in areas:
        for item in provinces_for(area):
            if item.name not in names:
                names.append(item.name)
    return names


def in_areas(location: str, areas: list[str]) -> bool:
    """Whether a job location lies in one of ``areas``, at province grain."""
    return any(contains_phrase(location or "", name) for name in area_names(areas))


def region_codes(areas: list[str], country: str) -> list[str]:
    """NUTS-2 codes, in ``country``, that the areas lie in."""
    codes: list[str] = []
    for area in areas:
        for item in provinces_for(area):
            if item.country == country.upper() and item.region not in codes:
                codes.append(item.region)
    return codes


#: Where an ad says its place: "Provincia: Navarra", "Localidad de ubicación
#: del puesto: Pamplona", "Location: Bilbao".
_PLACE_LABEL = re.compile(
    r"(?:provincia|localidad(?: de ubicaci[oó]n del puesto)?|ubicaci[oó]n(?: del puesto)?|"
    r"lugar de trabajo|centro de trabajo|location|place of work)\s*:\s*(.{2,80})",
    re.I)


#: "RIOJA (LA)", "PALMAS (LAS)", "BALEARS (ILLES)": how official lists sort a
#: name by its first real word. Put back in reading order before matching.
_TRAILING_ARTICLE = re.compile(r"([^\s()][^()]*?)\s*\((la|las|los|el|a|as|o|os|illes|les)\)", re.I)


def place_in(text: str) -> tuple[str, str] | None:
    """``(location, country)`` from the place an ad states, when it names a
    province, a town or a region this module knows; ``None`` otherwise.

    Only the words right after a label are read: a Pamplona firm's ad for a job
    in Madrid mentions both, and the label says which one is the job.
    """
    from .config import country_info  # local import: config imports this

    for label in _PLACE_LABEL.finditer(text or ""):
        stated = _TRAILING_ARTICLE.sub(r"\2 \1", label.group(1))
        window = f" {normalise(stated)} "
        best: tuple[int, str, str] | None = None  # (position, location, country)
        for item in _provinces().values():
            country = country_info(item.country).get("name", "")
            for name in (item.name, *item.name.split("/"), *item.places):
                at = window.find(f" {normalise(name)} ")
                if at >= 0 and (best is None or at < best[0]):
                    best = (at, location_for(item.code, country), item.country)
            # A region that is not one province ("Illes Balears", "Canarias").
            at = window.find(f" {normalise(item.region_name)} ") if item.region_name else -1
            if at >= 0 and (best is None or at < best[0]):
                best = (at, f"{item.region_name}, {country}", item.country)
        if best:
            return best[1], best[2]
    return None
