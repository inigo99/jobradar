"""The source plugin contract, plus the polite HTTP client every source uses.

A *source* is one place jobs come from: a public API, an RSS feed, or a company
applicant-tracking system. Adding one means writing a subclass of
``JobSource``, registering it in ``jobradar/sources/__init__.py`` and nothing
else — the pipeline, the filters, the dashboard and the CLI pick it up
automatically. See ``docs/SOURCES.md`` for a worked example.

Every source declares its own ``tos_tier``:

``open``       A documented public API or feed intended for programmatic use.
               Enabled by default.
``credentials`` A public API that needs a free key the user must obtain.
               Enabled once the key is present.
``restricted`` Reached by parsing pages that the site's terms may not intend to
               be automated. **Never enabled by default.** The user must switch
               it on explicitly, having read the warning, and accepts
               responsibility for their own use.

The ``restricted`` sources are also the only ones that ever ask ``Fetcher`` to
open a real browser (see ``Fetcher.get(..., browser=...)``) instead of a plain
HTTP request — that needs the ``scrapling`` package's browsers installed once
via ``scrapling install``. Every ``open``/``credentials`` source keeps using
plain HTTP, which is faster and needs nothing extra.
"""

from __future__ import annotations

import hashlib
import json
import logging
import time
import urllib.robotparser
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx

from ..config import SourceSettings
from ..models import Job

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Query
# ---------------------------------------------------------------------------


@dataclass
class SearchQuery:
    """What the pipeline asks every source for.

    Sources honour what they can and ignore the rest; the filter chain applies
    the full set of rules afterwards, so an imprecise source is never a
    correctness problem, only a bandwidth one.
    """

    titles: list[str] = field(default_factory=list)
    keywords: list[str] = field(default_factory=list)
    #: ISO-3166 alpha-2 codes the user may be employed from.
    countries: list[str] = field(default_factory=list)
    #: Free-text areas for on-site/hybrid searches ("Navarre", "Berlin").
    local_areas: list[str] = field(default_factory=list)
    remote_only: bool = False
    max_age_days: int = 7
    limit: int = 100
    languages: list[str] = field(default_factory=lambda: ["en"])

    def terms(self) -> list[str]:
        """Every query string worth sending, de-duplicated, order preserved."""
        seen: set[str] = set()
        result: list[str] = []
        for term in [*self.titles, *self.keywords]:
            if not term:
                continue
            key = str(term).strip().lower()
            if key and key not in seen:
                seen.add(key)
                result.append(str(term).strip())
        return result


# ---------------------------------------------------------------------------
# HTTP
# ---------------------------------------------------------------------------


class Fetcher:
    """Rate-limited, cached, robots-aware HTTP client shared by all sources.

    Being a good citizen is not optional here: a job board that blocks the
    default user agent because JobRadar hammered it hurts every user of the
    project. The defaults are deliberately slow.

    Plain HTTP (``httpx``) is the default and only transport for every
    ``open``/``credentials`` source. The three ``restricted`` sources — the
    ones reached by parsing pages built for a browser, not a program — can
    instead ask :meth:`get` to fetch through Scrapling's browser engines by
    passing ``browser="dynamic"`` or ``browser="stealthy"``; see that
    method's docstring. Throttling, ``robots.txt`` and the disk cache apply
    identically either way, so a source never has to think about it.
    """

    def __init__(self, settings: SourceSettings, cache_dir: Path | None = None):
        self.settings = settings
        self.cache_dir = cache_dir
        if cache_dir:
            cache_dir.mkdir(parents=True, exist_ok=True)
        self._last_request: dict[str, float] = {}
        self._robots: dict[str, urllib.robotparser.RobotFileParser | None] = {}
        self._client = httpx.Client(
            timeout=settings.timeout,
            follow_redirects=True,
            headers={"User-Agent": settings.user_agent, "Accept-Language": "en,es;q=0.8"},
        )

    # -- internals ---------------------------------------------------------

    def _throttle(self, url: str) -> None:
        host = urlparse(url).netloc
        elapsed = time.monotonic() - self._last_request.get(host, 0.0)
        if elapsed < self.settings.request_delay:
            time.sleep(self.settings.request_delay - elapsed)
        self._last_request[host] = time.monotonic()

    def _allowed(self, url: str) -> bool:
        if not self.settings.respect_robots:
            return True
        parsed = urlparse(url)
        origin = f"{parsed.scheme}://{parsed.netloc}"
        if origin not in self._robots:
            parser = urllib.robotparser.RobotFileParser()
            parser.set_url(f"{origin}/robots.txt")
            try:
                response = self._client.get(f"{origin}/robots.txt")
                if response.status_code == 200:
                    parser.parse(response.text.splitlines())
                else:  # no robots.txt at all == everything allowed
                    parser.parse([])
            except httpx.HTTPError:
                self._robots[origin] = None
                return True
            self._robots[origin] = parser
        parser = self._robots[origin]
        if parser is None:
            return True
        return parser.can_fetch(self.settings.user_agent, url)

    def _cache_path(self, url: str, body: str = "") -> Path | None:
        if not self.cache_dir:
            return None
        digest = hashlib.sha1(f"{url}{body}".encode()).hexdigest()
        return self.cache_dir / f"{digest}.json"

    def _read_cache(self, path: Path | None) -> str | None:
        if not path or not path.exists():
            return None
        ttl = timedelta(minutes=self.settings.cache_ttl_minutes)
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            stored = datetime.fromisoformat(payload["at"])
        except (json.JSONDecodeError, KeyError, ValueError):
            return None
        if datetime.now(timezone.utc) - stored > ttl:
            return None
        return payload["body"]

    def _write_cache(self, path: Path | None, body: str) -> None:
        if not path:
            return
        path.write_text(
            json.dumps({"at": datetime.now(timezone.utc).isoformat(), "body": body}),
            encoding="utf-8",
        )

    def _browser_get(self, url: str, *, headers: dict | None, mode: str) -> str | None:
        """Fetch ``url`` through Scrapling's browser engines instead of ``httpx``."""
        try:
            from scrapling.fetchers import DynamicFetcher, StealthyFetcher
        except ImportError:
            log.warning(
                "scrapling is not installed — cannot fetch %s through a browser; "
                "run `pip install jobradar` again or `scrapling install`", url,
            )
            return None
        fetch = StealthyFetcher.fetch if mode == "stealthy" else DynamicFetcher.fetch
        kwargs: dict[str, Any] = {
            "headless": True,
            "real_chrome": self.settings.scrapling_real_chrome,
            "extra_headers": headers or None,
            "retries": 0,
        }
        if mode == "stealthy":
            kwargs["solve_cloudflare"] = True
        try:
            page = fetch(url, **kwargs)
        except Exception as exc:  # Playwright/browser errors, not one Scrapling type
            log.debug("browser fetch %s failed: %s", url, exc)
            return None
        if page.status >= 400:
            log.debug("%s returned HTTP %s via browser", url, page.status)
            return None
        return page.body.decode("utf-8", errors="replace")

    # -- public API --------------------------------------------------------

    def get(self, url: str, *, params: dict | None = None, retries: int = 2,
            use_cache: bool = True, headers: dict | None = None,
            browser: str | None = None) -> str | None:
        """GET ``url``, returning the body or None if it could not be fetched."""
        full = str(httpx.URL(url, params=params or {}))
        cache_path = self._cache_path(full) if use_cache else None
        cached = self._read_cache(cache_path)
        if cached is not None:
            return cached
        if not self._allowed(full):
            log.warning("robots.txt disallows %s — skipping", full)
            return None
        for attempt in range(retries + 1):
            self._throttle(full)
            if browser:
                body = self._browser_get(full, headers=headers, mode=browser)
                if body is not None:
                    self._write_cache(cache_path, body)
                    return body
                time.sleep(1.5 * (attempt + 1))
                continue
            try:
                response = self._client.get(full, headers=headers)
                if response.status_code == 429:
                    time.sleep(2 ** attempt * 5)
                    continue
                if response.status_code >= 400:
                    log.debug("%s returned HTTP %s", full, response.status_code)
                    return None
                self._write_cache(cache_path, response.text)
                return response.text
            except httpx.HTTPError as exc:
                log.debug("GET %s failed (%s/%s): %s", full, attempt + 1, retries + 1, exc)
                time.sleep(1.5 * (attempt + 1))
        return None

    def get_json(self, url: str, **kwargs: Any) -> Any | None:
        body = self.get(url, **kwargs)
        if body is None:
            return None
        try:
            return json.loads(body)
        except json.JSONDecodeError:
            log.debug("%s did not return JSON", url)
            return None

    def post_json(self, url: str, payload: dict, *, headers: dict | None = None) -> Any | None:
        self._throttle(url)
        try:
            response = self._client.post(url, json=payload, headers=headers)
            if response.status_code >= 400:
                return None
            return response.json()
        except (httpx.HTTPError, json.JSONDecodeError):
            return None

    def head_status(self, url: str) -> int | None:
        """Status code of ``url``, used by the closed-ad sweep."""
        self._throttle(url)
        try:
            response = self._client.get(url)
            return response.status_code
        except httpx.HTTPError:
            return None

    def close(self) -> None:
        self._client.close()


# ---------------------------------------------------------------------------
# The plugin contract
# ---------------------------------------------------------------------------


class JobSource(ABC):
    """Base class for every job source.

    Subclasses must set the class attributes and implement :meth:`search`.
    Everything else has a working default.
    """

    #: Stable identifier used in settings and in job ids. Never change it.
    id: str = ""
    name: str = ""
    homepage: str = ""
    #: ``open`` | ``credentials`` | ``restricted`` — see the module docstring.
    tos_tier: str = "open"
    #: Shown to the user before a ``restricted`` source can be switched on.
    tos_note: str = ""
    #: Environment variables this source needs, if any.
    required_env: tuple[str, ...] = ()
    #: True when the source itself can tell remote from on-site reliably.
    supports_remote_filter: bool = False

    def __init__(self, fetcher: Fetcher, options: dict | None = None):
        self.fetcher = fetcher
        self.options = options or {}

    # -- contract ----------------------------------------------------------

    @abstractmethod
    def search(self, query: SearchQuery) -> list[Job]:
        """Return jobs matching ``query``. Must never raise."""

    def fetch_description(self, job: Job) -> str:
        """Full ad text for ``job``. Defaults to whatever ``search`` collected."""
        return job.description or ""

    def check_open(self, job: Job) -> tuple[bool, str]:
        """Is the ad still accepting applications?

        Returns ``(is_open, reason)``. The default heuristic — a 404 on the ad
        URL means gone, anything else means open — is right often enough for
        sources that delete expired ads, and sources that instead leave a
        tombstone page override it.
        """
        link = job.link
        if not link:
            return True, ""
        status = self.fetcher.head_status(link)
        if status is None:
            return True, ""  # network trouble is not evidence of closure
        if status in (404, 410):
            return False, f"HTTP {status}"
        return True, ""

    # -- helpers for subclasses -------------------------------------------

    @property
    def default_enabled(self) -> bool:
        """Restricted sources are never on unless the user says so."""
        return self.tos_tier == "open"

    def make_job(self, native_id: str, **fields: Any) -> Job:
        """Build a :class:`Job` already stamped with this source's id."""
        job = Job(source=self.id, native_id=str(native_id), **fields)
        return job.ensure_id()

    def credentials_present(self) -> bool:
        import os

        return all(os.environ.get(name) for name in self.required_env)