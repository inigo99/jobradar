"""Your portals — any job board you use, listed in Settings.

JobRadar cannot ship an adapter for every regional service, college or trade
board, so this source reads the pages you give it, one address per line:

* a search page, with ``{query}`` where the search words go
  (``https://example.org/jobs?q={query}``) — fetched once per search term;
* an RSS or Atom feed of offers;
* any page that lists offers.

From each page it takes, in order of reliability: the items of a feed; the
offers the page marks up for search engines (schema.org ``JobPosting``, which
most job boards publish); and failing both, the links whose text matches one
of your job titles. Pages are fetched politely and ``robots.txt`` is honoured;
a page that blocks automated readers, or builds its list with JavaScript,
yields nothing and says so in the run history.
"""

from __future__ import annotations

import hashlib
import html
import json
import re
from typing import Any
from urllib.parse import parse_qsl, quote_plus, urlencode, urljoin, urlparse, urlunparse

from ..models import Job, RemoteScope, WorkMode
from ..textutils import detect_language, parse_date, strip_html, title_matches
from .base import JobSource, SearchQuery

#: Links taken from one page when it has no feed or JobPosting markup.
MAX_LINKS = 40
#: Longest ad text kept from a page read for its description.
MAX_TEXT = 12000

_JSON_LD = re.compile(r'<script[^>]*type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
                      re.S | re.I)
_LINK = re.compile(r'<a\b[^>]*href=["\']([^"\'#]+)["\'][^>]*>(.*?)</a>', re.S | re.I)
_HEADING = re.compile(r"<h[1-6]\b[^>]*>(.*?)</h[1-6]>", re.S | re.I)
_MAIN = re.compile(r"<(main|article)\b[^>]*>(.*?)</\1>", re.S | re.I)
_BODY = re.compile(r"<body\b[^>]*>(.*?)</body>", re.S | re.I)


#: Query parameters that change on every visit (sessions, tracking) and would
#: make the same ad look new each day.
_VOLATILE = re.compile(r"(sess|^sid$|jsessionid|flujo|token|^utm_|^fbclid$|^gclid$|^ret$|^origen$)",
                       re.I)


def canonical(url: str) -> str:
    """``url`` without session and tracking parameters, so an ad keeps one id."""
    parts = urlparse(url)
    path = re.sub(r";jsessionid=[^/?#]*", "", parts.path, flags=re.I)
    query = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True)
             if not _VOLATILE.search(k)]
    params = "" if "jsessionid" in parts.params.lower() else parts.params
    return urlunparse(parts._replace(path=path, params=params, query=urlencode(query),
                                     fragment=""))


def _tag(block: str, name: str) -> str:
    match = re.search(rf"<{name}\b[^>]*>(.*?)</{name}>", block, re.S | re.I)
    if not match:
        return ""
    text = re.sub(r"^\s*<!\[CDATA\[(.*)\]\]>\s*$", r"\1", match.group(1), flags=re.S)
    return html.unescape(text).strip()


def feed_items(body: str) -> list[dict[str, str]] | None:
    """Items of an RSS or Atom feed, or None when ``body`` is not a feed."""
    head = body.lstrip()[:500].lower()
    if not (head.startswith("<?xml") or "<rss" in head or "<feed" in head):
        return None
    items = []
    for block in re.findall(r"<(?:item|entry)\b.*?</(?:item|entry)>", body, re.S | re.I):
        link = _tag(block, "link")
        if not link:  # Atom: <link href="..."/>
            found = re.search(r'<link\b[^>]*href=["\']([^"\']+)["\']', block, re.I)
            link = found.group(1) if found else ""
        items.append({
            "title": strip_html(_tag(block, "title")),
            "url": link,
            "description": strip_html(_tag(block, "description") or _tag(block, "content")
                                      or _tag(block, "summary")),
            "date": _tag(block, "pubDate") or _tag(block, "published") or _tag(block, "updated"),
        })
    return items


def job_postings(body: str) -> list[dict[str, Any]]:
    """Every schema.org JobPosting in the page's JSON-LD blocks."""
    found: list[dict[str, Any]] = []

    def walk(node: Any) -> None:
        if isinstance(node, list):
            for item in node:
                walk(item)
        elif isinstance(node, dict):
            kind = node.get("@type")
            kinds = kind if isinstance(kind, list) else [kind]
            if "JobPosting" in kinds:
                found.append(node)
                return
            for key in ("@graph", "itemListElement", "item", "mainEntity"):
                if key in node:
                    walk(node[key])

    for block in _JSON_LD.findall(body):
        try:
            walk(json.loads(html.unescape(block).strip()))
        except (json.JSONDecodeError, RecursionError):
            continue
    return found


def _text(value: Any) -> str:
    if isinstance(value, dict):
        value = value.get("name") or value.get("@value") or ""
    if isinstance(value, list):
        value = ", ".join(_text(v) for v in value)
    return str(value or "").strip()


def _place(posting: dict[str, Any]) -> tuple[str, str]:
    """``(location, country)`` from a JobPosting's jobLocation."""
    locations = posting.get("jobLocation") or []
    first = locations[0] if isinstance(locations, list) and locations else locations
    address = first.get("address") if isinstance(first, dict) else None
    if not isinstance(address, dict):
        return _text(address), ""
    country = _text(address.get("addressCountry"))
    parts = [_text(address.get(key)) for key in ("addressLocality", "addressRegion")]
    location = ", ".join(part for part in parts if part) or country
    return location, country.upper() if len(country) == 2 else ""


class PortalsSource(JobSource):
    id = "portals"
    name = "Your portals"
    homepage = ""
    tos_tier = "open"
    tos_note = ("The pages you list under Settings → Job portals you use. robots.txt is "
                "honoured; whether a site allows automated reading is in its own terms.")

    def search(self, query: SearchQuery) -> list[Job]:
        jobs: dict[str, Job] = {}
        terms = query.terms()
        for entry in self.options.get("portals") or []:
            entry = entry.strip()
            if not entry.startswith(("http://", "https://")):
                continue
            if "{query}" in entry:
                pages = [(entry.replace("{query}", quote_plus(term)), [term]) for term in terms]
            else:
                pages = [(entry, terms)]
            for url, wanted in pages:
                body = self.get(url)
                if not body:
                    self.fetcher._report_once(
                        f"portal:{url}",
                        f"Could not read {url}: it did not answer, or its robots.txt "
                        "does not allow automated readers.")
                    continue
                found = self.read_page(body, url, wanted)
                if not found:
                    self.fetcher._report_once(
                        f"portal-empty:{urlparse(url).netloc}",
                        f"Nothing recognisable on {url}: no feed, no JobPosting markup "
                        "and no link matching your job titles. The page may build its "
                        "list with JavaScript.")
                for job in found:
                    jobs.setdefault(job.native_id, job)
                if len(jobs) >= query.limit:
                    return list(jobs.values())[: query.limit]
        return list(jobs.values())

    def read_page(self, body: str, url: str, terms: list[str]) -> list[Job]:
        """The offers on one fetched page: feed items, JobPostings, or matching links."""
        items = feed_items(body)
        if items is not None:
            return [job for item in items if (job := self._from_item(item, url, terms))]
        postings = job_postings(body)
        if postings:
            return [job for posting in postings
                    if (job := self._from_posting(posting, url, terms))]
        return self._from_links(body, url, terms)

    def _job(self, link: str, **fields: Any) -> Job:
        link = canonical(link)
        native = hashlib.sha1(link.encode()).hexdigest()[:16]
        fields.setdefault("company", urlparse(link).netloc.removeprefix("www."))
        return self.make_job(native, url=link, **fields)

    def _from_item(self, item: dict[str, str], page: str, terms: list[str]) -> Job | None:
        if not item["title"] or not title_matches(item["title"], terms):
            return None
        link = urljoin(page, item["url"]) if item["url"] else page
        return self._job(link, title=item["title"], description=item["description"],
                         posted_at=parse_date(item["date"]),
                         language=detect_language(f"{item['title']} {item['description']}"))

    def _from_posting(self, posting: dict[str, Any], page: str, terms: list[str]) -> Job | None:
        title = strip_html(_text(posting.get("title")))
        if not title or not title_matches(title, terms):
            return None
        link = urljoin(page, _text(posting.get("url")) or page)
        description = strip_html(_text(posting.get("description")))
        location, country = _place(posting)
        remote = "TELECOMMUTE" in _text(posting.get("jobLocationType")).upper()
        company = _text(posting.get("hiringOrganization"))
        return self._job(
            link,
            title=title,
            **({"company": company} if company else {}),
            location=location,
            country=country,
            work_mode=WorkMode.REMOTE if remote else WorkMode.UNKNOWN,
            remote_scope=RemoteScope.UNKNOWN,
            posted_at=parse_date(_text(posting.get("datePosted"))),
            description=description,
            language=detect_language(f"{title} {description}"),
        )

    def _from_links(self, body: str, page: str, terms: list[str]) -> list[Job]:
        if not terms:
            return []  # without titles to match, every menu link would be a "job"
        jobs: dict[str, Job] = {}
        for href, anchor in _LINK.findall(body):
            # A result card is often one link around a heading, the company and
            # a summary: the heading is the title.
            heading = _HEADING.search(anchor)
            text = strip_html(heading.group(1) if heading else anchor)
            if not 4 <= len(text) <= 160 or not title_matches(text, terms):
                continue
            link = urljoin(page, html.unescape(href))
            if not link.startswith(("http://", "https://")) or link.rstrip("/") == page.rstrip("/"):
                continue
            jobs.setdefault(canonical(link), self._job(link, title=text,
                                                       language=detect_language(text)))
            if len(jobs) >= MAX_LINKS:
                break
        return list(jobs.values())

    def fetch_description(self, job: Job) -> str:
        """The ad page: its JobPosting description if it has one, else its main text."""
        if len(job.description or "") >= 400:
            return job.description
        body = self.get(job.link)
        if not body:
            return job.description or ""
        for posting in job_postings(body):
            text = strip_html(_text(posting.get("description")))
            if text:
                return text[:MAX_TEXT]
        main = _MAIN.search(body) or _BODY.search(body)
        text = strip_html(main.group(2) if main and main.lastindex == 2 else
                          (main.group(1) if main else body))
        return text[:MAX_TEXT] or job.description or ""
