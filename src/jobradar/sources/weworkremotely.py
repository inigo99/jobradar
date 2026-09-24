"""We Work Remotely — public per-category RSS feeds.

Feeds: https://weworkremotely.com/categories/<category>.rss

A warning worth keeping in mind, encoded in ``remote_scope`` below: WWR's
``<region>`` tag frequently says "Anywhere in the World" for roles that turn
out to be US-only in the body text. The tag is therefore treated as a hint, and
the ad body always overrides it.
"""

from __future__ import annotations

import re
from xml.etree import ElementTree

from ..models import Job, RemoteScope, WorkMode
from ..textutils import detect_language, detect_remote_scope, parse_date, strip_html
from .base import JobSource, SearchQuery

FEED = "https://weworkremotely.com/categories/{category}.rss"

DEFAULT_CATEGORIES = (
    "remote-programming-jobs",
    "remote-back-end-programming-jobs",
    "remote-front-end-programming-jobs",
    "remote-full-stack-programming-jobs",
    "remote-devops-sysadmin-jobs",
    "remote-data-jobs",
    "remote-design-jobs",
    "remote-product-jobs",
    "remote-marketing-jobs",
    "remote-customer-support-jobs",
    "remote-sales-and-marketing-jobs",
)


class WeWorkRemotelySource(JobSource):
    id = "weworkremotely"
    name = "We Work Remotely"
    homepage = "https://weworkremotely.com"
    tos_tier = "open"
    supports_remote_filter = True

    def search(self, query: SearchQuery) -> list[Job]:
        categories = self.options.get("categories") or DEFAULT_CATEGORIES
        terms = [t.lower() for t in query.terms()]
        jobs: list[Job] = []
        for category in categories:
            body = self.fetcher.get(FEED.format(category=category))
            if not body:
                continue
            try:
                root = ElementTree.fromstring(body)
            except ElementTree.ParseError:
                continue
            for item in root.iter("item"):
                job = self._parse_item(item, terms)
                if job:
                    jobs.append(job)
                if len(jobs) >= query.limit:
                    return jobs
        return jobs

    def _parse_item(self, item: ElementTree.Element, terms: list[str]) -> Job | None:
        title_raw = str(item.findtext("title") or "").strip()
        link = str(item.findtext("link") or "").strip()
        if not title_raw or not link:
            return None
        description = strip_html(str(item.findtext("description") or ""))
        if terms and not any(term in f"{title_raw} {description}".lower() for term in terms):
            return None

        # WWR titles look like "Company Name: Senior Backend Engineer".
        company, _, title = title_raw.partition(":")
        if not title:
            company, title = "", title_raw
        region = str(item.findtext("region") or "").strip()

        # The body always wins over the region tag; see the module docstring.
        scope, regions = detect_remote_scope(description)
        if scope == RemoteScope.UNKNOWN and "anywhere in the world" in region.lower():
            scope, regions = RemoteScope.UNKNOWN, []
            note = "WWR tags this 'Anywhere in the World' — confirm in the ad, the tag is unreliable."
        else:
            note = ""

        native_id = re.sub(r"[^0-9a-zA-Z]+", "-", link.rsplit("/", 1)[-1])[:80]
        return self.make_job(
            native_id,
            title=title.strip(),
            company=company.strip(),
            location=region or "Remote",
            work_mode=WorkMode.REMOTE,
            remote_scope=scope,
            remote_regions=regions,
            url=link,
            posted_at=parse_date(item.findtext("pubDate")),
            description=description,
            language=detect_language(description),
            alerts=[note] if note else [],
            raw={"region_tag": region},
        )
