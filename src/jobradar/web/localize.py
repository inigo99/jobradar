"""Translating API responses into the dashboard's language.

The page sends its language in the ``X-JobRadar-Language`` header; the CLI and
scripts send none and get English. Only text JobRadar wrote is translated —
alerts, reasons, findings, labels, messages — never what the user or an
employer wrote (a CV, notes, an ad, an email). See ``jobradar/i18n.py``.
"""

from __future__ import annotations

from contextvars import ContextVar
from typing import Any

from starlette.requests import Request

from ..families import default_families
from ..i18n import DEFAULT_LANGUAGE, family_label, normalise_language, skill_label, translate
from ..taxonomy import taxonomy

HEADER = "x-jobradar-language"
#: The language of the request being handled, set by the app's middleware.
#: Sync endpoints run in a worker thread, which receives a copy of it.
_LANGUAGE: ContextVar[str] = ContextVar("jobradar_language", default=DEFAULT_LANGUAGE)


def request_language(request: Request) -> str:
    """The language a request asks for; English when it says nothing."""
    return normalise_language(request.headers.get(HEADER))


def use_language(language: str) -> None:
    _LANGUAGE.set(language)


def current() -> str:
    return _LANGUAGE.get()


def _tr(value: Any, language: str | None = None) -> Any:
    return translate(value, language or current()) if isinstance(value, str) else value


def findings(items: list[dict], language: str | None = None) -> list[dict]:
    """Linter findings and text warnings: the message and the hint."""
    language = language or current()
    if language == DEFAULT_LANGUAGE:
        return items
    return [{**item, "message": _tr(item.get("message"), language),
             "hint": _tr(item.get("hint"), language)} for item in items]


def lint(report: dict | None, language: str | None = None) -> dict | None:
    language = language or current()
    if not report or language == DEFAULT_LANGUAGE:
        return report
    return {**report, "summary": _tr(report.get("summary"), language),
            "findings": findings(report.get("findings") or [], language)}


def family_name(key: str, label: str, language: str | None = None) -> str:
    """A family's name: translated unless the user renamed it."""
    language = language or current()
    default = default_families().get(key)
    if default is None or label != default.label:
        return label
    return family_label(key, label, language)


def job(view: dict, language: str | None = None) -> dict:
    """One board row (web.api.JobView as a dict)."""
    language = language or current()
    if language == DEFAULT_LANGUAGE:
        return view
    view = dict(view)
    for key in ("focus_reason", "salary_basis"):
        view[key] = _tr(view.get(key), language)
    for key in ("alerts", "strengths", "gaps", "requirements"):
        view[key] = [_tr(item, language) for item in view.get(key) or []]
    view["gap_details"] = [{**gap, "label": _tr(gap.get("label"), language),
                            "note": _tr(gap.get("note"), language)}
                           for gap in view.get("gap_details") or []]
    if view.get("family"):
        view["family_label"] = family_name(view["family"], view.get("family_label", ""), language)
    return view


def filtered(view: dict, language: str | None = None) -> dict:
    """One filtered-out ad (web.api.FilteredView as a dict)."""
    language = language or current()
    if language == DEFAULT_LANGUAGE:
        return view
    view = {**view, "reason": _tr(view.get("reason"), language)}
    if view.get("family"):
        view["family_label"] = family_name(view["family"], view.get("family_label", ""), language)
    return view


def tally(counts: dict, language: str | None = None) -> dict:
    """The filtered-out tally: the reason shapes are English sentences."""
    language = language or current()
    if language == DEFAULT_LANGUAGE:
        return counts
    return {**counts, "by_shape": [(_tr(shape, language), n)
                                   for shape, n in counts.get("by_shape") or []]}


def families(rows: list[dict], language: str | None = None) -> list[dict]:
    """The Settings family editor: translate a label and its default together,
    so an untouched family is not saved as a rename."""
    language = language or current()
    if language == DEFAULT_LANGUAGE:
        return rows
    out = []
    for row in rows:
        default = row.get("default")
        if default and row.get("label") == default.get("label"):
            translated = family_label(row["key"], row["label"], language)
            row = {**row, "label": translated, "default": {**default, "label": translated}}
        out.append(row)
    return out


def profile(summary: dict | None, language: str | None = None) -> dict | None:
    """The profile summary: skill names (not the user's own) and the linter."""
    language = language or current()
    if not summary or language == DEFAULT_LANGUAGE:
        return summary
    known = taxonomy()
    skills = [
        {**skill, "label": skill_label(skill["key"], skill["label"], language)}
        if not skill.get("custom") and skill["key"] in known
        and skill["label"] == known[skill["key"]].label else skill
        for skill in summary.get("skills") or []
    ]
    return {**summary, "skills": skills, "lint": lint(summary.get("lint"), language)}


def insights(funnel: dict, history: dict, language: str | None = None) -> tuple[dict, dict]:
    """The funnel's group names are labels (families, score bands)."""
    language = language or current()
    if language == DEFAULT_LANGUAGE:
        return funnel, history
    funnel = dict(funnel)
    for key in ("by_family", "by_score"):
        funnel[key] = {_tr(name, language): group for name, group in (funnel.get(key) or {}).items()}
    return funnel, history


def message(text: str, language: str | None = None) -> str:
    return _tr(text, language)
