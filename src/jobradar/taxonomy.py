"""The skill taxonomy: turning free text into stable skill keys.

Both halves of JobRadar need the same vocabulary. The pipeline uses it to read
requirements out of a job ad; the profile importer uses it to work out what the
candidate can evidence. Sharing one taxonomy is what lets a requirement be
compared against the profile at all.

The data lives in ``resources/skills.yaml`` and is deliberately editable — a
user in a field the shipped taxonomy does not cover adds their own keys there
and everything downstream keeps working.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import yaml

RESOURCES = Path(__file__).parent / "resources"


#: How long it is realistic to spend closing a gap between sending an
#: application and sitting an interview. Ordered from cheapest to dearest.
DIFFICULTIES = ("fast", "medium", "slow")

DIFFICULTY_NOTE = {
    "fast": "Days to a week on top of what you already know — worth a look before an interview.",
    "medium": "Several weeks of real work to discuss it with any authority, rather than by hearsay.",
    "slow": "Not realistic inside one hiring process. Prepare an honest answer instead of cramming.",
}


@dataclass(frozen=True)
class Skill:
    key: str
    label: str
    group: str
    aliases: tuple[str, ...]
    #: "fast", "medium" or "slow" — see :func:`difficulty_for`.
    difficulty: str = "medium"


def _raw() -> dict:
    return yaml.safe_load((RESOURCES / "skills.yaml").read_text(encoding="utf-8")) or {}


@lru_cache(maxsize=1)
def _difficulty_rules() -> tuple[str, dict[str, str], dict[str, str]]:
    """``(default, by_group, overrides)`` from the ``_learning_difficulty`` block."""
    block = _raw().get("_learning_difficulty") or {}
    default = str(block.get("default", "medium"))
    by_group = {str(k): str(v) for k, v in (block.get("by_group") or {}).items()}
    overrides = {str(k): str(v) for k, v in (block.get("overrides") or {}).items()}
    return default, by_group, overrides


#: Skills the user added in Settings that the shipped taxonomy does not know,
#: keyed like any other skill. Set from the profile by :func:`use_custom_skills`.
_CUSTOM: dict[str, Skill] = {}
#: Prefix of the keys of user-added skills.
CUSTOM_PREFIX = "custom_"


def use_custom_skills(custom: dict[str, list[str]], labels: dict[str, str] | None = None) -> None:
    """Make the user's own skills part of the vocabulary.

    ``custom`` maps each key to the other names the skill goes by in ads;
    ``labels`` gives its display name (``Profile.custom_skills`` and
    ``Profile.skill_labels``). Called whenever the profile is loaded or saved,
    so a skill added in Settings is read in job ads and checked by the
    validator like a shipped one.
    """
    labels = labels or {}
    wanted = {}
    for key, aliases in custom.items():
        label = labels.get(key) or key.removeprefix(CUSTOM_PREFIX).replace("_", " ")
        names = dict.fromkeys(a.strip().lower() for a in (label, *aliases) if a and a.strip())
        wanted[key] = Skill(key=key, label=label, group="custom", aliases=tuple(names),
                            difficulty=_difficulty_rules()[0])
    if wanted == _CUSTOM:
        return
    _CUSTOM.clear()
    _CUSTOM.update(wanted)
    _matchers.cache_clear()
    _names.cache_clear()


def taxonomy() -> dict[str, Skill]:
    """Every skill known to JobRadar, keyed by its stable key: shipped, then the user's."""
    return {**_shipped(), **_CUSTOM} if _CUSTOM else _shipped()


@lru_cache(maxsize=1)
def _shipped() -> dict[str, Skill]:
    """The taxonomy in ``resources/skills.yaml``."""
    raw = _raw()
    default, by_group, overrides = _difficulty_rules()
    skills: dict[str, Skill] = {}
    for key, entry in raw.items():
        # Keys starting with "_" are configuration blocks, not skills.
        if key.startswith("_") or not isinstance(entry, dict):
            continue
        aliases = tuple(str(a).lower() for a in entry.get("aliases", []))
        group = entry.get("group", "other")
        difficulty = entry.get("difficulty") or overrides.get(key) or by_group.get(group) or default
        if difficulty not in DIFFICULTIES:
            difficulty = default
        skills[key] = Skill(
            key=key,
            label=entry.get("label", key.replace("_", " ").title()),
            group=group,
            aliases=aliases or (key.replace("_", " "),),
            difficulty=difficulty,
        )
    return skills


@lru_cache(maxsize=1)
def _matchers() -> list[tuple[str, re.Pattern[str]]]:
    """Compiled whole-word patterns, longest alias first.

    Longest-first matters: without it "go" would fire inside "google" and
    "java" inside "javascript". Every alias is anchored on non-word characters
    for the same reason — substring matching is how a job radar decides you
    know Alan because the company is called Talan.
    """
    patterns: list[tuple[str, re.Pattern[str], int]] = []
    for skill in taxonomy().values():
        for alias in skill.aliases:
            escaped = re.escape(alias).replace(r"\ ", r"[\s\-]+")
            # Allow a trailing plural "s" when the alias ends in a letter, so
            # "REST API" also matches "REST APIs".
            plural = "s?" if alias[-1:].isalpha() else ""
            patterns.append(
                (
                    skill.key,
                    re.compile(rf"(?<![\w+#.]){escaped}{plural}(?![\w+#])", re.IGNORECASE),
                    len(alias),
                )
            )
    patterns.sort(key=lambda item: -item[2])
    return [(key, pattern) for key, pattern, _ in patterns]


@lru_cache(maxsize=1)
def _names() -> dict[str, str]:
    """Every alias and label, normalised, -> skill key."""
    names: dict[str, str] = {}
    for skill in taxonomy().values():
        for name in (*skill.aliases, skill.label, skill.key.replace("_", " ")):
            names.setdefault(_plain_name(name), skill.key)
    return names


def _plain_name(name: str) -> str:
    return re.sub(r"[\s\-_]+", " ", str(name or "").strip().lower())


def skill_for_name(name: str) -> str | None:
    """The skill a *name* denotes — the whole name, not a word inside it.

    For structured lists ("Soporte vital avanzado", "Excel") where
    :func:`find_skills` would be wrong: it looks for skills mentioned
    anywhere in a text, so it would read "soporte" as customer support.
    """
    plain = _plain_name(name)
    if not plain:
        return None
    return _names().get(plain) or (_names().get(plain[:-1]) if plain.endswith("s") else None)


def find_skills(text: str) -> dict[str, int]:
    """Skill keys mentioned in ``text``, mapped to how many times.

    The count is a crude proxy for how much the ad insists on something, and it
    is what the requirement weighting is built on when no language model is
    available.
    """
    if not text:
        return {}
    counts: dict[str, int] = {}
    for key, pattern in _matchers():
        hits = len(pattern.findall(text))
        if hits:
            counts[key] = counts.get(key, 0) + hits
    return counts


def label_for(key: str) -> str:
    skill = taxonomy().get(key)
    return skill.label if skill else key.replace("_", " ").title()


def group_for(key: str) -> str:
    skill = taxonomy().get(key)
    return skill.group if skill else "other"


def difficulty_for(key: str) -> str:
    """How realistic it is to close this gap before an interview.

    This does **not** decide whether something is a gap — the profile's
    evidence does that, and the anti-fabrication lock is unaffected. It only
    sorts gaps that already exist into what is worth reading up on and what is
    better answered honestly. A skill being "fast" to learn never puts it on
    the CV; it goes on the CV when the candidate has actually learnt it.
    """
    skill = taxonomy().get(key)
    if skill:
        return skill.difficulty
    return _difficulty_rules()[0]


def difficulty_note(key: str) -> str:
    return DIFFICULTY_NOTE.get(difficulty_for(key), DIFFICULTY_NOTE["medium"])
