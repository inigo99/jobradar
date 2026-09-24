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
import os
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
from ..models import Job, WorkMode

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
            try:
                cache_dir.mkdir(parents=True, exist_ok=True)
            except OSError as exc:  # no cache is slower, not broken
                log.warning("Cannot create the cache directory %s (%s); caching is off.",
                            cache_dir, exc)
                self.cache_dir = None
        self._last_request: dict[str, float] = {}
        self._robots: dict[str, urllib.robotparser.RobotFileParser | None] = {}
        #: Browser executable Scrapling launches, once one has been found to
        #: work; ``None`` until then, meaning "Playwright's own build".
        self._browser_executable: str | None = None
        #: Hosts whose robots.txt was deliberately not consulted, logged once.
        self._robots_skipped: set[str] = set()
        #: Problems already reported, so a run of 50 failed pages logs once.
        self._reported: set[str] = set()
        #: Those problems' messages, in order, for the run log.
        self.problems: list[str] = []
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
        rules = self._robots[origin]
        if rules is None:
            return True
        return rules.can_fetch(self.settings.user_agent, url)

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
        except (OSError, KeyError, TypeError, ValueError):  # a bad cache entry is a miss
            return None
        if datetime.now(timezone.utc) - stored > ttl:
            return None
        return payload["body"]

    def _write_cache(self, path: Path | None, body: str) -> None:
        if not path:
            return
        try:
            path.write_text(
                json.dumps({"at": datetime.now(timezone.utc).isoformat(), "body": body}),
                encoding="utf-8",
            )
        except OSError as exc:  # the page was fetched; failing to cache it is not fatal
            log.warning("Could not write the cache file %s: %s", path, exc)

    def _browser_get(self, url: str, *, headers: dict | None, mode: str) -> str | None:
        """Fetch ``url`` through Scrapling's browser engines instead of ``httpx``.

        Only called by :meth:`get` when a ``restricted`` source passes
        ``browser=``. ``mode`` is ``"dynamic"`` — a plain headless browser,
        enough to get past a check for a real browser fingerprint, such as
        LinkedIn's guest endpoints — or ``"stealthy"`` — fingerprint spoofing
        plus Cloudflare-style challenge solving, for a page that answers a
        plain browser with a block instead of the content, such as
        InfoJobs' ad pages (they return HTTP 405 behind a CAPTCHA challenge
        to ``"dynamic"``, and load normally under ``"stealthy"``).

        When the Chromium build Playwright expects is not installed, the
        browsers found by :func:`jobradar.documents.browser.fallback_executables`
        are tried in turn and the first that starts is kept for the run.

        Returns ``None`` — same contract as :meth:`get` itself — when the page
        cannot be fetched; the reason is logged once as a warning, because a
        restricted source that silently returns nothing looks exactly like a
        board with no jobs.
        """
        try:
            from scrapling.fetchers import DynamicFetcher, StealthyFetcher
        except ImportError:
            self._report_once(
                "scrapling-missing",
                "The 'scrapling' package is not installed, so the restricted sources "
                "(LinkedIn, InfoJobs, Tecnoempleo, Indeed) cannot fetch anything. "
                "Reinstall JobRadar with: pip install -e .",
            )
            return None

        fetch = StealthyFetcher.fetch if mode == "stealthy" else DynamicFetcher.fetch
        kwargs: dict[str, Any] = {
            "headless": True,
            "real_chrome": self.settings.scrapling_real_chrome,
            "extra_headers": headers or None,
            # Scrapling's minimum. Fetcher.get() already retries whole
            # attempts with backoff; more here would only multiply the wait.
            "retries": 1,
        }
        if mode == "stealthy":
            kwargs["solve_cloudflare"] = True

        page = None
        for executable in self._browser_candidates():
            attempt = dict(kwargs)
            if executable:
                attempt["executable_path"] = executable
            try:
                page = fetch(url, **attempt)
            except Exception as exc:  # Playwright/browser errors, not one Scrapling type
                if _browser_missing(exc):
                    continue  # try the next installed browser
                self._report_once(
                    f"browser-error:{urlparse(url).netloc}",
                    f"Fetching {urlparse(url).netloc} through a browser failed: "
                    f"{_first_line(exc)}",
                )
                return None
            self._browser_executable = executable
            break
        if page is None:
            self._report_once(
                "browser-missing",
                "No browser could be started for the restricted sources. Run "
                "'scrapling install' (or 'playwright install chromium'), or set "
                "JOBRADAR_CHROMIUM_PATH to an installed Chromium or Chrome.",
            )
            return None
        if page.status >= 400:
            hint = (" — the site answered with a challenge page; the request delay may be "
                    "too short, or the site now blocks automated browsers"
                    if page.status in (403, 405, 429) else "")
            self._report_once(
                f"http-{page.status}:{urlparse(url).netloc}",
                f"{urlparse(url).netloc} answered HTTP {page.status} to the browser{hint}.",
            )
            return None
        body = page.body
        return body.decode(getattr(page, "encoding", None) or "utf-8", errors="replace") \
            if isinstance(body, bytes) else str(body)

    def _browser_candidates(self) -> list[str | None]:
        """Executables to try for Scrapling, the one known to work first.

        ``None`` stands for "whatever Playwright expects", which is right
        whenever ``playwright install`` / ``scrapling install`` matched the
        installed package; the fallbacks cover the case where it did not.
        """
        if self._browser_executable is not None or "browser-missing" in self._reported:
            return [self._browser_executable]
        from ..documents.browser import CHROMIUM_PATH_VARIABLE, fallback_executables

        explicit = os.environ.get(CHROMIUM_PATH_VARIABLE, "").strip()
        candidates: list[str | None] = [] if explicit else [None]
        candidates += [str(path) for path in fallback_executables()]
        return candidates

    def _report_once(self, key: str, message: str) -> None:
        """Log a problem as a warning the first time it happens in this run."""
        if key in self._reported:
            log.debug(message)
            return
        self._reported.add(key)
        self.problems.append(message)
        log.warning(message)

    # -- public API --------------------------------------------------------

    def get(self, url: str, *, params: dict | None = None, retries: int = 2,
            use_cache: bool = True, headers: dict | None = None,
            browser: str | None = None, obey_robots: bool = True) -> str | None:
        """GET ``url``, returning the body or None if it could not be fetched.

        Sources are expected to treat None as "this query yielded nothing" and
        carry on: one dead board must never abort a whole run.

        ``browser`` routes the request through a real browser instead of a
        plain HTTP request — pass ``"dynamic"`` or ``"stealthy"``, see
        :meth:`_browser_get`. Leave it ``None`` (the default) for every
        ``open``/``credentials`` source: plain HTTP is faster and all of them
        answer it correctly.

        ``obey_robots=False`` skips the ``robots.txt`` check. Only the
        ``restricted`` sources pass it (through :meth:`JobSource.get`): their
        sites disallow every automated client, so honouring it would make them
        return nothing, and they only run when the user switched them on by
        name after reading their terms note.
        """
        full = str(httpx.URL(url, params=params or {}))
        cache_path = self._cache_path(full) if use_cache else None
        cached = self._read_cache(cache_path)
        if cached is not None:
            return cached
        if not obey_robots:
            host = urlparse(full).netloc
            if host not in self._robots_skipped:
                self._robots_skipped.add(host)
                log.info("Not consulting robots.txt for %s: it is a restricted source you "
                         "enabled explicitly.", host)
        elif not self._allowed(full):
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

    def resolve_work_mode(self, job: Job) -> WorkMode | None:
        """The board's own work-mode label for ``job``, or None.

        Called only for jobs still marked ``remote_unconfirmed`` after their
        text was read — the board says remote, the ad says nothing — so a
        source that can look up a more reliable label (LinkedIn's badge) can
        settle it with one extra request instead of leaving an alert.
        """
        return None

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

    def get(self, url: str, **kwargs: Any) -> str | None:
        """Fetch ``url`` through the shared :class:`Fetcher`.

        The one place a source's terms tier changes how it fetches:
        ``restricted`` sources skip ``robots.txt`` (see :meth:`Fetcher.get`),
        everything else honours it.
        """
        kwargs.setdefault("obey_robots", self.tos_tier != "restricted")
        return self.fetcher.get(url, **kwargs)

    def make_job(self, native_id: str, **fields: Any) -> Job:
        """Build a :class:`Job` already stamped with this source's id."""
        job = Job(source=self.id, native_id=str(native_id), **fields)
        return job.ensure_id()

    def credentials_present(self) -> bool:
        return all(os.environ.get(name) for name in self.required_env)


def _browser_missing(exc: Exception) -> bool:
    """Whether a browser launch failed because the executable is not installed."""
    text = str(exc).lower()
    return "executable doesn't exist" in text or "playwright install" in text


def _first_line(exc: Exception) -> str:
    """The first line of an exception message; Playwright's run to a boxed banner."""
    return (str(exc).strip().splitlines() or [type(exc).__name__])[0]
