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
their behalf. If you enable one, keep `request_delay` generous and use it at
the volume of a person doing their own job search.

Shipped restricted adapters: LinkedIn (guest endpoint), InfoJobs, Tecnoempleo
and Indeed. Manfred is `open`: it serves its offers as public JSON.

## Public employment services

For nurses, teachers, lawyers, tradespeople and most of the jobs that are not
in tech, a country's public employment service is often the fullest board.
Public-sector job offers are also information the law lets anyone reuse (in
Spain, Ley 37/2007; in the EU, the Commission's reuse decision), which is why
these adapters are `open`.

- **EURES** (`eures`, `open`): the European Commission's job portal, around
  three million vacancies fed by the public employment services of the EU,
  Norway, Iceland, Liechtenstein and Switzerland — Spain's regional services
  included. One JSON request per search term to the API behind the portal's
  own search (no key; documented by the community at
  [rorar/eures-api-documentation](https://github.com/rorar/eures-api-documentation)),
  restricted to your countries and your age limit. The ad is kept in the
  language it was written in, not the portal's machine translation.
- **Bundesagentur für Arbeit** (`arbeitsagentur`, Germany, `open`, **off
  until you switch it on**): the JSON API behind the agency's own search,
  with its public client id, documented at
  [jobsuche.api.bund.dev](https://jobsuche.api.bund.dev). Like the national
  boards in [PORTALS.md](PORTALS.md), it is for the people who look there;
  once on, it runs only when `DE` is one of your countries. Search results carry no text, so each
  ad's text is fetched later, one request per new ad. The ads are in German,
  and the skill vocabulary is English and Spanish, so expect fewer skill
  matches than for Spanish or English ads.
SEPE / Empléate (Spain) has no public search, and most Spanish regional
services publish on EURES; France Travail's official API needs an application
registered with it — a `credentials` adapter for it would be welcome.
Regional and national boards are not built in: users add the ones they read
as **their portals** (below), from the tested list in [PORTALS.md](PORTALS.md).

## Your portals

Nobody can ship an adapter for every regional service, college or trade
board, so users list the ones they read under **Settings → Job portals you
use** (`sources.portals`); each can be switched off without deleting it.
[PORTALS.md](PORTALS.md) lists tested ones by country and region. An address
can be:

- a search page, with `{query}` where the search words go
  (`https://example.org/jobs?q={query}`), fetched once per search term;
- an RSS or Atom feed;
- any page that lists offers.

`sources/portals.py` reads, in order of reliability: the feed's items; the
offers the page marks up for search engines (schema.org `JobPosting` in
JSON-LD, which most job boards publish because Google for Jobs reads it); and,
failing both, the links whose text matches one of the user's job titles
(first five letters of each word, so "enfermera" finds "Enfermero/a"). An
ad's text comes from its own page, again from its `JobPosting` markup when it
has one. Search words are sent without accents (older sites decode them in
their own charset), session parameters are dropped from ad addresses so an ad
keeps one id, and a link that wraps a whole result card is titled by the
heading inside it. Plain HTTP only, and `robots.txt` is honoured — wildcards
included (`Fetcher` uses `sources/robots.py`, since Python's own parser
ignores them): a page that blocks automated readers or builds its list with
JavaScript yields nothing, and the run history says so.

## Being a good citizen

`sources/base.Fetcher` enforces this for every adapter, so you get it for free:

- one request per second per host (`request_delay`, raise it if you like);
- `robots.txt` checked before any fetch (`respect_robots`, on by default) —
  except for `restricted` sources, which skip it (see below);
- responses cached on disk for an hour (`cache_ttl_minutes`);
- exponential backoff on HTTP 429, and a bounded retry on transport errors;
- an honest user agent naming the project.

A board that blocks the default user agent because someone hammered it hurts
every user of the project. The defaults are deliberately slow.

**Why restricted sources skip `robots.txt`.** LinkedIn, InfoJobs and Indeed
disallow every automated visitor in it, so honouring it meant the adapters a
user had deliberately switched on fetched nothing at all, silently. Switching
a restricted source on *is* the decision `robots.txt` would otherwise make, and
it is made by the person running the software, having read the warning.
`JobSource.get()` passes `obey_robots=False` for the restricted tier only; an
adapter calling `self.fetcher.get` directly keeps the check.

**Problems are reported, once.** A blocked page (403, a challenge), a missing
browser or a browser build Scrapling cannot launch is added to
`Fetcher.problems` once per run and shown in the run summary and the run
history — the alternative, an empty result, looks exactly like "no jobs today".

## Sources that run once a week

A source that publishes a handful of ads a week is not worth a request every
day. `settings.sources.weekly` lists sources that run only on
`settings.sources.weekly_day` (0 = Monday); on other days they are skipped
with a note in the run, and `jobradar sources` shows them as "on (Mondays
only)". `jobradar sweep` still checks their ads every day.

## Browser-backed fetching for a blocked `restricted` source

Plain HTTP is the default transport for `Fetcher.get()`, and every
`open`/`credentials` source should never need anything else — if one of them
starts needing a browser, that is usually a sign it should be `restricted`
instead, not a reason to reach for this.

For a `restricted` source, if the plain-HTTP path stops working — the site
starts answering with a CAPTCHA, a 403, or a page that only renders after
JavaScript runs — pass `browser="dynamic"` (a real headless browser) or
`browser="stealthy"` (adds fingerprint spoofing and Cloudflare-style
challenge solving) to that call instead of changing anything else:

```python
body = self.fetcher.get(url, params=params, browser="dynamic")
```

Both go through [Scrapling](https://github.com/D4Vinci/Scrapling), a
mandatory dependency whose browsers are a separate, one-time download
(`scrapling install`) — everything else about the call, including the cache,
the throttle and the `robots.txt` rule, stays exactly the same as the plain
path, so nothing downstream of `self.fetcher.get(...)` needs to change.

If the browser build Scrapling expects is not installed (a Playwright upgrade
is the usual cause), the fetcher tries the other Chromium builds it can find —
or the one in `JOBRADAR_CHROMIUM_PATH` — and remembers the one that worked for
the rest of the run.
Start with `"dynamic"`; it is faster and is enough for most anti-bot walls.
Reach for `"stealthy"` only for the requests that need it: LinkedIn and
Tecnoempleo are fine with `"dynamic"`, while InfoJobs answers `"dynamic"` with
a CAPTCHA (HTTP 405) on every page and Indeed does the same, so both use
`"stealthy"` throughout. Walls move: when a source that worked starts
returning nothing, the run history shows the 405 or the challenge.

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

`resolve_work_mode(job)` — the board's own work-mode label, for jobs the board
calls remote but whose text says nothing either way (the job carries
`raw["remote_unconfirmed"]`). LinkedIn overrides it to read the badge on the
ad page with one extra request, instead of leaving an alert on the job.

Structured requirements — when a board publishes the skills an ad asks for
and at what level (Manfred does), build `job.requirements` from them in
`search` and set `job.raw["structured_requirements"] = True`: enrichment then
keeps them instead of re-reading the text.

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
