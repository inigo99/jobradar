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


@dataclass(frozen=True)
class Skill:
    key: str
    label: str
    group: str
    aliases: tuple[str, ...]


@lru_cache(maxsize=1)
def taxonomy() -> dict[str, Skill]:
    """Every skill known to JobRadar, keyed by its stable key."""
    raw = yaml.safe_load((RESOURCES / "skills.yaml").read_text(encoding="utf-8")) or {}
    skills: dict[str, Skill] = {}
    for key, entry in raw.items():
        aliases = tuple(str(a).lower() for a in entry.get("aliases", []))
        skills[key] = Skill(
            key=key,
            label=entry.get("label", key.replace("_", " ").title()),
            group=entry.get("group", "other"),
            aliases=aliases or (key.replace("_", " "),),
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
