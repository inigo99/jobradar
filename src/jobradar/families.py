"""Job families: what kind of work an ad is for, in any sector.

The default catalogue lives in ``resources/families.yaml``. The user's changes
— a new label, different keywords, a priority, a family switched off, or a
family of their own — are stored as :class:`~jobradar.config.FamilyOverride`
entries in ``Settings.families`` and merged over it by :func:`families_for`,
so an upgrade that improves the catalogue still reaches families the user has
not touched.

A family feeds three things: the priority nudge in the board's initial order
(:func:`priority_for`), the salary estimate's starting band, and the
per-family CV variants of the profile. It never changes the match score.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from functools import lru_cache

from .config import FamilyOverride, Settings, load_resource
from .models import Job
from .textutils import contains_phrase

#: The family every job falls back to; it cannot be switched off.
GENERAL = "general"
#: Points for a keyword found in the title and in the start of the description.
TITLE_POINTS, DESCRIPTION_POINTS = 3, 1
#: How much of the description is read: the opening says what the job is,
#: the rest is benefits, company history and boilerplate.
DESCRIPTION_WINDOW = 600
SENIORITIES = ("junior", "mid", "senior", "lead")


@dataclass(frozen=True)
class Family:
    key: str
    label: str
    keywords: tuple[str, ...] = ()
    #: Seniority -> (min, max) annual gross in the base currency.
    bands: dict[str, tuple[int, int]] = field(default_factory=dict)
    #: Multiplier on the board's initial order; 1.0 is neutral.
    priority: float = 1.0
    #: True for families the user added, not in the default catalogue.
    custom: bool = False


def _bands(raw: object) -> dict[str, tuple[int, int]]:
    """``{"junior": [a, b], ...}`` with anything malformed dropped."""
    bands: dict[str, tuple[int, int]] = {}
    if not isinstance(raw, dict):
        return bands
    for seniority, pair in raw.items():
        try:
            low, high = int(pair[0]), int(pair[1])
        except (TypeError, ValueError, IndexError, KeyError):
            continue
        if str(seniority) in SENIORITIES and 0 < low <= high:
            bands[str(seniority)] = (low, high)
    return bands


@lru_cache(maxsize=1)
def default_families() -> dict[str, Family]:
    """The catalogue shipped in ``resources/families.yaml``."""
    catalogue: dict[str, Family] = {}
    for key, entry in load_resource("families.yaml").items():
        if not isinstance(entry, dict):
            continue
        catalogue[str(key)] = Family(
            key=str(key),
            label=str(entry.get("label") or str(key).replace("_", " ").title()),
            keywords=tuple(str(k) for k in entry.get("keywords") or []),
            bands=_bands(entry.get("bands")),
        )
    if GENERAL not in catalogue:
        catalogue[GENERAL] = Family(key=GENERAL, label="General")
    return catalogue


def _apply(base: Family | None, key: str, override: FamilyOverride) -> Family | None:
    """One family with the user's override applied, or None if switched off."""
    if not override.enabled and key != GENERAL:
        return None
    label = (override.label or "").strip() or (base.label if base else key.replace("_", " ").title())
    keywords = (tuple(k.strip() for k in override.keywords if k.strip())
                if override.keywords is not None else (base.keywords if base else ()))
    bands = _bands(override.bands) if override.bands else (base.bands if base else {})
    return Family(key=key, label=label, keywords=keywords, bands=bands,
                  priority=override.priority, custom=base is None)


def families_for(settings: Settings | None) -> dict[str, Family]:
    """The catalogue with the user's changes, in classification order.

    Default families keep their catalogue order; the user's own families come
    after them, and ``general`` is always last.
    """
    overrides = settings.families if settings is not None else {}
    merged: dict[str, Family] = {}
    for key, family in default_families().items():
        if key == GENERAL:
            continue
        override = overrides.get(key)
        applied = _apply(family, key, override) if override else family
        if applied is not None:
            merged[key] = applied
    for key, override in overrides.items():
        if key not in default_families():
            applied = _apply(None, key, override)
            if applied is not None:
                merged[key] = applied
    general = default_families()[GENERAL]
    if GENERAL in overrides:
        general = _apply(general, GENERAL, overrides[GENERAL]) or general
    merged[GENERAL] = general
    return merged


def catalogue_view(settings: Settings | None) -> list[dict]:
    """Every family — including switched-off ones — for the settings screen.

    Each entry carries the effective values and the catalogue's own, so the
    screen can tell a change from a default and store only what changed.
    """
    overrides = settings.families if settings is not None else {}
    effective = families_for(settings)
    rows: list[dict] = []
    keys = list(default_families()) + [k for k in overrides if k not in default_families()]
    for key in keys:
        base = default_families().get(key)
        current = effective.get(key)
        shown = current or (_apply(base, key, overrides[key].model_copy(update={"enabled": True}))
                            if key in overrides else base)
        if shown is None:
            continue
        rows.append({
            "key": key,
            "label": shown.label,
            "keywords": list(shown.keywords),
            "priority": shown.priority,
            "enabled": current is not None,
            "custom": base is None,
            "default": None if base is None else {
                "label": base.label, "keywords": list(base.keywords), "priority": 1.0,
            },
        })
    return rows


def classify(job: Job, families: dict[str, Family]) -> str:
    """The family ``job`` belongs to, ``general`` when nothing matches.

    Title keywords count three times as much as description keywords: an ad
    for a nurse that mentions the hospital's IT systems is still for a nurse.
    """
    title = job.title or ""
    opening = (job.description or "")[:DESCRIPTION_WINDOW]
    best, best_points = GENERAL, 0
    for key, family in families.items():
        points = 0
        for keyword in family.keywords:
            if contains_phrase(title, keyword):
                points += TITLE_POINTS
            elif opening and contains_phrase(opening, keyword):
                points += DESCRIPTION_POINTS
        if points > best_points:
            best, best_points = key, points
    return best


def label_for(key: str, families: dict[str, Family]) -> str:
    family = families.get(key)
    return family.label if family else (key or GENERAL).replace("_", " ").title()


def priority_for(job: Job, families: dict[str, Family]) -> float:
    """The user's priority for ``job``'s family; 1.0 when it has none."""
    family = families.get(job.family or GENERAL)
    return family.priority if family else 1.0
