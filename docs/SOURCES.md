# Job sources

## The three tiers

Every adapter declares a `tos_tier`, and the tier decides whether it runs by
default.

**`open`** — a documented public API or feed intended for programmatic use.
Enabled by default.

**`credentials`** — a public API that needs a free key the user obtains
themselves. Enabled as soon as the key is present in the environment; skipped
with a log line when it is not.

**`restricted`** — reached by parsing pages built for human visitors, where the
site's terms may not permit automated access. **Never enabled by default.** The
user must name it in `settings.sources.enabled`, having seen the warning.

The reason the restricted tier exists at all is that for many people the
national boards are where the jobs are, and a tool that ignores them is not
useful. The reason it is off by default is that whether automated access is
acceptable is a decision for the person running the software, under their own
jurisdiction and the site's terms — not a default this project should make on
their behalf. If you enable one, keep `request_delay` generous, leave
`respect_robots` on, and use it at the volume of a person doing their own job
search.

## Being a good citizen

`sources/base.Fetcher` enforces this for every adapter, so you get it for free:

- one request per second per host (`request_delay`, raise it if you like);
- `robots.txt` checked before any fetch (`respect_robots`, on by default);
- responses cached on disk for an hour (`cache_ttl_minutes`);
- exponential backoff on HTTP 429, and a bounded retry on transport errors;
- an honest user agent naming the project.

A board that blocks the default user agent because someone hammered it hurts
every user of the project. The defaults are deliberately slow.

## Writing an adapter

A source does two things: turn a `SearchQuery` into HTTP requests, and turn the
responses into `Job` objects. It never touches the database and never decides
whether a job is wanted — the pipeline does that, which is why an adapter can
be tested with no database at all.

```python
"""Example Board — public JSON API.

Docs: https://exampleboard.dev/api
"""

from __future__ import annotations

from ..models import Job, WorkMode
from ..textutils import detect_language, detect_remote_scope, parse_date, strip_html
from .base import JobSource, SearchQuery

API = "https://exampleboard.dev/api/jobs"


class ExampleBoardSource(JobSource):
    id = "exampleboard"            # stable forever: it is part of every job id
    name = "Example Board"
    homepage = "https://exampleboard.dev"
    tos_tier = "open"
    required_env = ()              # ("EXAMPLE_API_KEY",) for the credentials tier

    def search(self, query: SearchQuery) -> list[Job]:
        jobs: list[Job] = []
        for term in query.terms():
            payload = self.fetcher.get_json(API, params={"q": term, "limit": 50})
            for entry in (payload or {}).get("results", []):
                description = strip_html(entry.get("description", ""))
                scope, regions = detect_remote_scope(description)
                jobs.append(self.make_job(
                    entry["id"],
                    title=entry.get("title", ""),
                    company=entry.get("company", ""),
                    location=entry.get("location", ""),
                    country=entry.get("country_code", "").upper(),
                    work_mode=WorkMode.REMOTE if entry.get("remote") else WorkMode.UNKNOWN,
                    remote_scope=scope,
                    remote_regions=regions,
                    url=entry.get("url", ""),
                    posted_at=parse_date(entry.get("published_at")),
                    description=description,
                    language=detect_language(description),
                ))
                if len(jobs) >= query.limit:
                    return jobs
        return jobs
```

Then register it:

```python
# sources/__init__.py
from .exampleboard import ExampleBoardSource

REGISTRY = (..., ExampleBoardSource, ...)
```

Nothing else changes. The pipeline, the filters, the dashboard's source list and
`jobradar sources` all pick it up.

### The three rules

1. **Never raise.** A dead board must not end someone's run. Return an empty
   list; `Fetcher.get` already returns `None` rather than throwing.
2. **Always use `self.fetcher`.** It is what enforces the rate limiting, the
   cache and `robots.txt`. Calling `httpx` directly bypasses all of it.
3. **Fill what you can, leave the rest.** `WorkMode.UNKNOWN` and
   `RemoteScope.UNKNOWN` are legitimate answers; the enrichment stage resolves
   them from the ad body. Guessing is worse than admitting you do not know.

### Optional overrides

`fetch_description(job)` — return the full ad text when `search` could only get
a summary. The pipeline calls it for any job whose description is short, and
re-derives work mode, remote scope, minimum years and salary from what you
return.

`check_open(job)` — used by `jobradar sweep`. The default treats a 404 as gone
and anything else as open. Override it when the board leaves a tombstone page
instead of deleting the ad; InfoJobs, for example, keeps the title visible and
only the redirect reveals that it is closed.

## Company career boards

`sources/ats.py` is one adapter covering seven applicant tracking systems:
Greenhouse, Lever, Ashby, Workable, Recruitee, SmartRecruiters and Personio.
Users add entries to `settings.sources.company_domains`:

```
stripe.com            # bare domain — the ATS is detected once and cached
greenhouse:airbnb     # explicit provider and board slug
lever:netflix
```

Detection reads the company's careers page and looks for the known board
hostnames; failing that it guesses a slug from the domain and probes each API.
Adding an eighth system is a URL template in `BOARD_URLS`, a pattern in
`DETECTION_PATTERNS` and a `_parse_<provider>` method.

This path is strongly preferred over scraping a company's careers page: the
endpoints exist so that aggregators can read them, they are stable, and they
return the full ad text as structured data.
