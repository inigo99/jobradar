"""Translating what the dashboard shows.

JobRadar's own text — alerts, filter reasons, focus reasons, linter findings,
warnings, error messages — is written in English where it is produced, and
much of it is stored that way (a filtered ad's reason, a job's alerts). So it
is translated on the way out, at the API boundary, from a catalogue in
``resources/i18n/<language>.yaml``:

* ``exact``    — whole sentences, looked up as they are;
* ``patterns`` — sentences with parts that vary, written as templates:
  ``"asks for {years} years, you have {held}"``. Each ``{name}`` matches any
  text, and that text is itself translated when the catalogue knows it (a
  family label, a company type);
* ``skills``, ``families`` — display names by key.

Text the catalogue does not know is returned unchanged: a new message shows in
English until someone adds it, which is better than showing nothing. Long
texts built from several sentences ("…; …", "…. …") are translated piece by
piece. What the user wrote — their CV, their notes, an ad, an email — is never
translated.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

import yaml

from .taxonomy import taxonomy

RESOURCES = Path(__file__).parent / "resources" / "i18n"
#: Languages the dashboard can be shown in. English is the source language.
LANGUAGES = ("en", "es")
DEFAULT_LANGUAGE = "en"
_PLACEHOLDER = re.compile(r"\{(\w+)\}")


@dataclass
class Catalogue:
    """One language's translations, compiled."""

    exact: dict[str, str] = field(default_factory=dict)
    patterns: list[tuple[re.Pattern[str], str]] = field(default_factory=list)
    skills: dict[str, str] = field(default_factory=dict)
    families: dict[str, str] = field(default_factory=dict)


def _compile(template: str) -> re.Pattern[str]:
    """``"asks for {years} years"`` -> a regex with a named group per placeholder."""
    parts: list[str] = []
    position = 0
    for match in _PLACEHOLDER.finditer(template):
        parts.append(re.escape(template[position:match.start()]))
        parts.append(f"(?P<{match.group(1)}>.+?)")
        position = match.end()
    parts.append(re.escape(template[position:]))
    return re.compile("".join(parts) + r"\Z", re.DOTALL)


@lru_cache(maxsize=8)
def catalogue(language: str) -> Catalogue:
    """The compiled catalogue for ``language`` (empty for English or unknown ones)."""
    path = RESOURCES / f"{language}.yaml"
    if language == DEFAULT_LANGUAGE or not path.is_file():
        return Catalogue()
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    patterns = []
    for entry in data.get("patterns") or []:
        source, target = str(entry["en"]), str(entry[language])
        patterns.append((_compile(source), target))
    # Longer templates first, so the most specific one wins.
    patterns.sort(key=lambda item: -len(item[0].pattern))
    skills = {str(k): str(v) for k, v in (data.get("skills") or {}).items()}
    exact = {str(k): str(v) for k, v in (data.get("exact") or {}).items()}
    # A skill's English label is also a term: gaps and strengths arrive as labels.
    for key, skill in taxonomy().items():
        if key in skills:
            exact.setdefault(skill.label, skills[key])
    return Catalogue(
        exact=exact,
        patterns=patterns,
        skills=skills,
        families={str(k): str(v) for k, v in (data.get("families") or {}).items()},
    )


def normalise_language(value: str | None) -> str:
    """``"es-ES,es;q=0.9"`` -> ``"es"``; anything unsupported -> English."""
    code = (value or "").split(",")[0].split("-")[0].split(";")[0].strip().lower()
    return code if code in LANGUAGES else DEFAULT_LANGUAGE


def _term(text: str, table: Catalogue) -> str:
    return table.exact.get(text, text)


def translate(text: str | None, language: str) -> str:
    """``text`` in ``language``, or unchanged when the catalogue does not know it."""
    if not text or language == DEFAULT_LANGUAGE:
        return text or ""
    table = catalogue(language)
    if not table.exact and not table.patterns:
        return text
    stripped = text.strip()
    if stripped in table.exact:
        return table.exact[stripped]
    for pattern, target in table.patterns:
        match = pattern.match(stripped)
        if match:
            values = {name: _term(value, table) for name, value in match.groupdict().items()}
            return target.format(**values)
    # Composite texts: translate each clause, then each sentence.
    for separator in ("; ", ". "):
        if separator in stripped:
            pieces = stripped.split(separator)
            translated = [translate(piece, language) for piece in pieces]
            if translated != pieces:
                return separator.join(translated)
    return text


def translate_all(texts: list[str] | None, language: str) -> list[str]:
    return [translate(text, language) for text in (texts or [])]


def skill_label(key: str, default: str, language: str) -> str:
    """A skill's display name in ``language`` (the user's own labels are kept)."""
    if language == DEFAULT_LANGUAGE:
        return default
    return catalogue(language).skills.get(key, default)


def family_label(key: str, default: str, language: str) -> str:
    if language == DEFAULT_LANGUAGE:
        return default
    return catalogue(language).families.get(key, default)
