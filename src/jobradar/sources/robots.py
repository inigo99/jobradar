"""robots.txt rules, wildcards included.

Python's ``urllib.robotparser`` only matches path prefixes: a rule such as
``Disallow: *motsCles=*`` (France Travail's search pages) or
``Disallow: /*?*chaves=`` (Net-Empregos') is compared literally and never
matches, so a crawler relying on it fetches exactly what the site asked it
not to. This follows RFC 9309 instead: ``*`` matches any run of characters,
``$`` anchors the end, the longest matching rule wins, and on a tie ``Allow``
wins.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from urllib.parse import urlparse


@dataclass
class _Group:
    agents: list[str] = field(default_factory=list)
    rules: list[tuple[bool, str]] = field(default_factory=list)  # (allow, pattern)


def _pattern(rule: str) -> re.Pattern[str]:
    anchored = rule.endswith("$")
    body = re.escape(rule.rstrip("$")).replace(r"\*", ".*")
    return re.compile(body + ("$" if anchored else ""))


class RobotRules:
    """The rules one ``robots.txt`` sets."""

    def __init__(self, text: str):
        self.groups: list[_Group] = []
        current: _Group | None = None
        reading_agents = False
        for raw in text.splitlines():
            line = raw.split("#", 1)[0].strip()
            if ":" not in line:
                continue
            key, _, value = line.partition(":")
            key, value = key.strip().lower(), value.strip()
            if key == "user-agent":
                if current is None or not reading_agents:
                    current = _Group()
                    self.groups.append(current)
                current.agents.append(value.lower())
                reading_agents = True
            elif key in ("allow", "disallow") and current is not None:
                reading_agents = False
                if value or key == "allow":
                    current.rules.append((key == "allow", value))

    def _group_for(self, user_agent: str) -> list[tuple[bool, str]]:
        agent = user_agent.lower()
        best: tuple[int, list[tuple[bool, str]]] | None = None
        fallback: list[tuple[bool, str]] = []
        for group in self.groups:
            for name in group.agents:
                if name == "*":
                    fallback = fallback + group.rules
                elif name and name in agent and (best is None or len(name) > best[0]):
                    best = (len(name), group.rules)
        return best[1] if best else fallback

    def can_fetch(self, user_agent: str, url: str) -> bool:
        parts = urlparse(url)
        target = (parts.path or "/") + (f"?{parts.query}" if parts.query else "")
        verdict, length = True, -1
        for allow, rule in self._group_for(user_agent):
            if not rule:
                continue
            if _pattern(rule).match(target):
                size = len(rule)
                if size > length or (size == length and allow):
                    verdict, length = allow, size
        return verdict
