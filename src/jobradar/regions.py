"""Sub-national regions: NUTS codes <-> the names people type.

Some boards say where a job is only as a region code (EURES gives a NUTS-3
code, a province in Spain) and search only by NUTS-2. This module turns those
codes into names for the job's location, and the user's areas ("Pamplona",
"Barcelona") into codes a board can search by and province names a location
can be matched against. The data is ``resources/regions.yaml``.
"""

from __future__ import annotations

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
