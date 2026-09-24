# JobRadar

**A self-hosted job radar that searches job boards, scores every opening against your CV, and writes a tailored one-page CV for each one — without inventing a single thing about you.**

JobRadar runs on your machine, keeps your CV and your job search in a local SQLite file, and works with or without a language model. It is not tied to any industry: the profile, the filters, the skill taxonomy and the salary tables are all data you can edit.

```bash
pip install -e ".[all]"
playwright install chromium     # optional: the HTML templates' typography in the PDF
scrapling install               # only needed if you enable LinkedIn/InfoJobs/Tecnoempleo/Indeed
jobradar demo                   # synthetic data, no network calls
jobradar serve                  # dashboard on http://127.0.0.1:8000
```

![The JobRadar dashboard](docs/images/dashboard.png)

---

## Contents

- [What it does](#what-it-does)
- [Why the CV part is different](#why-the-cv-part-is-different)
- [Install](#install)
- [Quick start](#quick-start)
- [The dashboard](#the-dashboard)
- [Command line](#command-line)
- [Configuration](#configuration)
- [Job sources](#job-sources)
- [Using a language model (optional)](#using-a-language-model-optional)
- [Running it on a schedule](#running-it-on-a-schedule)
- [Repository layout](#repository-layout)
- [Privacy and data](#privacy-and-data)
- [Limitations, honestly](#limitations-honestly)
- [Contributing](#contributing)
- [Licence](#licence)

---

## What it does

**1. Searches.** Every enabled source is queried for your target job titles. Public APIs and feeds are on by default; national boards that need care are opt-in (see [Job sources](#job-sources)). You can also list companies to watch — give it `stripe.com` and it works out which hiring system that company uses and reads its job board directly.

**2. Deduplicates.** The same opening appears on three boards at once and once more through an agency. Duplicates are collapsed on the job id, on a normalised company-and-title fingerprint, and on token overlap in the title — never on substring matching, which is how a radar decides you know *Alan* because the company is called *Talan*.

**3. Reads the fine print.** Each ad is fetched in full and re-read: work mode (an ad that says "remote" three times and then mentions two office days is hybrid), which countries a remote role may actually be performed from, minimum years of experience, and any published salary.

**4. Filters.** Work mode, geography, salary floor with live currency conversion, seniority, recency, keywords, blocked companies. Missing information is never treated as a rejection: a job with an unclear remote scope is kept and flagged, because the alternative is losing good jobs to bad metadata. **Nothing rejected is thrown away**: every dropped ad is kept with its reason under *Filtered out*, where the tally says which filter is doing the damage and one button puts an ad back. A filter one notch too strict is invisible when its victims vanish, and "the board is empty" looks exactly like "there were no jobs today".

The years filter takes its ceiling from your CV's own dates, so it rises on its own instead of ageing quietly, and it separates the ads you miss by a hair from the ones far out of reach. An ad that states no minimum is never filtered on years at all — most state none.

**5. Sorts and prices.** Every job is put in a **job family** — healthcare, logistics, hospitality, software, finance and twenty more, for any kind of work, editable in Settings — and a family can be given a priority to move it up or down the board. Around two thirds of ads publish no salary, so JobRadar estimates a band: the family's reference band, adjusted for the kind of employer (public sector, staffing agency, large company…), the country that actually hires, and at most two signals from the ad (many years asked for, an unnamed client, a regulated sector). It is always marked as an estimate and shows the reasoning.

**6. Scores, then triages.** Each job gets two scores: what your CV proves *today*, and what it would prove if the relevant skills were pulled out of your skills list and into an achievement. The difference is what tailoring is worth. Gaps are listed explicitly, worst first, each marked with how long it would realistically take to close before an interview.

Match score answers "could I do this job". It stops discriminating once your profile covers most of what the ads ask for — everything clusters near the top, and sorting by match becomes sorting by noise. So the board is ordered by **focus**: the match score less what is already known to go nowhere (ads that have aged past the point of a reply, titles pitched above your years), plus a nudge for ads that publish a band. Every job carries one sentence saying why it sits where it does, and the honest match number is one click away. **Today** is the first tab: six jobs in focus order and a weekly counter, because a board of two hundred jobs does not say where to start.

**7. Tailors and writes.** For any job, JobRadar writes a headline and a professional summary, reorders your achievements by relevance, reorders your skill groups, and renders a one-page PDF — shrinking the type in small steps until it fits rather than cutting your content. A **CV per job family** fixes the headline, which achievements lead or are left out and which skill groups come first for, say, every warehouse job. The PDF needs no browser: when Chromium is missing the built-in writer prints it. Cover letters and application emails are editable and download as PDF, and a **form-answers** thread per job answers the free-text questions of application forms within the form's own length limit, with an **answer bank** so a good answer can be adapted the next time a similar question comes up.

**8. Checks.** Every generated CV is validated against your profile, and linted for the things a senior recruiter spots in ten seconds. Letters, emails and form answers get warnings that never block anything: figures that are neither in your CV nor in the ad, years you do not have, skills you cannot show, template phrases, a company never named, parts still to fill in.

**9. Tracks.** Active, applied, rejected, discarded — with stages, dates and notes. *Discarded* (you passed) and *rejected* (they passed) are kept distinct, because merging them destroys your response-rate statistics. Applications are never submitted for you: the button opens the ad. A job found elsewhere is added by hand and read like any other; a job you never want to see again is deleted (with a week to undo).

**10. Reads your replies.** With a mailbox configured, JobRadar reads (never changes) your email over IMAP and puts each reply next to its application: a rejection, a next step, or an automatic acknowledgement, quoting the sentence it went by. A proposed interview time becomes a calendar file. It never changes an application's stage on its own.

**11. Says whether it is working.** *Insights* shows the funnel — replies by source, by job family and by match score, the median wait, companies that never answer — and each source's record over past runs, so keeping or dropping a board is a decision made with numbers.

---

## Why the CV part is different

Most CV tools optimise for a keyword match. That produces a CV you cannot defend in an interview, which is worse than no CV at all.

JobRadar has three mechanisms to stop that, and they are the reason the project exists.

### 1. Evidence and ceilings

Each skill in your profile carries two numbers:

| | Meaning |
|---|---|
| **Evidence** | How strongly your CV proves it *today*. `1.0` = argued for inside an achievement with a result attached. `0.5` = listed in a skills section. `0.0` = you do not have it. |
| **Ceiling** | How far a tailored CV may push it — that is, how well you could defend it under twenty minutes of questioning. |

A tailored CV can raise a skill from its evidence to its ceiling by moving it into a bullet or the summary. **A skill with evidence `0.0` has no ceiling and never rises.** That single rule is the lock: no amount of tailoring can invent experience, so the improvement in the score always reflects better presentation of things that are already true.

Both numbers are proposed automatically when your CV is imported and are editable in the dashboard, because only you know which of your listed tools you could survive a technical interview on. Under **Settings → Your skills** you can add, edit and delete skills and the groups your CV lists them in. A skill JobRadar does not know yet becomes one of yours — with any other names it goes by in ads — and is read in ads from then on. A skill you delete stays deleted, even through a new CV import.

### 2. Your achievements are never rewritten

The tailoring step reorders achievements within a position. It does not rewrite them, merge them, move them between jobs, or reorder the positions themselves. Your bullets are written once, in your own words, and the CV that gets you the call says exactly what your profile says.

Achievements follow Google's XYZ formula — *accomplished **X**, as measured by **Y**, by doing **Z*** — and the linter tells you which of yours are missing the Y.

### 3. Everything generated is verified

Generated text is compared mechanically against your profile before it reaches a PDF:

- **Invented skills** — a technology named in the document that your profile has no evidence for. Rejected.
- **Invented figures** — a number that appears nowhere in your profile. Models are fond of rounding 47% up to 50%. Rejected.
- **Inflated seniority** — more years claimed than your own dates support. Rejected.

When a draft fails, JobRadar keeps the deterministic version and tells you what was rejected and why. The check runs whether or not a language model was involved.

### 4. The red-flag linter

`jobradar lint` reports what a reader will notice in the first pass:

<details>
<summary>The full rule list</summary>

| Rule | Severity | What it catches |
|---|---|---|
| `too-long` | error | More than one page |
| `missing-name`, `missing-email` | error | No way to contact you |
| `missing-dates` | error | An undated position |
| `chronology` | error | Positions not in reverse-chronological order |
| `no-achievements` | error | A CV of job titles with nothing under them |
| `impossible-ceiling` | error / warning | A ceiling on a skill with no evidence, or below its evidence |
| `position-without-achievements` | warning | One position with nothing under it |
| `unproven-evidence` | warning | A skill marked as demonstrated that no achievement shows |
| `employment-gap` | warning | An unexplained gap over five months |
| `few-metrics` | warning | Fewer than half the achievements carry a number |
| `duty-language` | warning | "Responsible for…", "Worked on…" |
| `long-bullet` | warning | An achievement over 300 characters |
| `empty-phrase` | warning | "Results-driven", "team player", "detail-oriented" |
| `skill-stuffing` | warning | More than 40 listed skills |
| `acronym-soup` | warning | A summary that is mostly acronyms |
| `no-summary`, `long-summary` | warning | No summary, or one nobody will read |
| `thin-contact` | warning | Email only, no phone or LinkedIn |
| `too-many-bullets` | info | More than six achievements in one role |
| `mixed-tense` | info | "-ing" and past-tense openings in the same role |
| `first-person` | info | Bullets starting with "I" |
| `orphan-skills` | info | Many skills listed but never demonstrated |
| `repeated-keyword` | info | The same term repeated for ATS ranking that does not work |
| `summary-without-evidence` | info | A summary with no concrete figure |
| `unknown-listed-skills` | info | Listed skills that matching does not know, so they never count |

Rules that would encode a cultural preference are deliberately absent. Whether a CV should carry a photo or a date of birth varies enormously by country, and a linter that flags a German CV for following German convention is worse than no linter.
</details>

### 5. The output survives an ATS

Every template is a single column of real, selectable text, in a standard font, with nothing in the page margins — no tables, no sidebars, no icons, no text inside images. Those are the four things that make a CV come out of an applicant tracking system scrambled.

---

## Install

Requires Python 3.10 or newer.

```bash
git clone https://github.com/inigo99/jobradar.git
cd jobradar
python -m venv .venv && source .venv/bin/activate    # Windows: .venv\Scripts\activate
pip install -e ".[all]"
playwright install chromium
scrapling install
```

Or install only what you need:

```bash
pip install -e .                # search, filter, score, dashboard, HTML CVs
pip install -e ".[pdf]"         # + the templates' own PDF typography (headless Chromium)
pip install -e ".[parse]"       # + importing a PDF or DOCX CV
pip install -e ".[excel]"       # + .xlsx export
```

Without Playwright the CV is still a PDF: a built-in writer lays it out more
plainly and needs no browser (choose it permanently with *CV PDF* in
Settings). With it, run `playwright install chromium` again after upgrading
Playwright: each version expects its own browser build. If it cannot download
one, JobRadar prints the PDF with any other Chromium it finds (an older
Playwright build or a system Chromium/Chrome), or the one named in
`JOBRADAR_CHROMIUM_PATH`.

Either way, `pip install` alone is enough for every `open`/`credentials`
source. **`scrapling install`** is the one extra, one-time step, and it only
matters if you plan to switch on LinkedIn, InfoJobs, Tecnoempleo or Indeed:
it downloads the browsers those adapters fetch through (a few hundred MB).
Skip it and everything else still works; those adapters just have nothing to
fetch with until you run it.

`jobradar doctor` tells you what is installed and what each missing piece would give you.

---

## Quick start

### Look around first

```bash
jobradar demo      # a synthetic profile and ten synthetic jobs; no network
jobradar serve
```

The demo jobs are chosen to exercise the interesting cases: a US-only "remote" role, an EMEA one, an agency posting that hides its client, an ad with no salary, and an on-site job outside your areas.

### Set it up for yourself

Either open the dashboard and let the wizard walk you through it:

```bash
jobradar serve      # the setup wizard opens on first run
```

…or do it from the terminal:

```bash
jobradar init --cv ~/Documents/my-cv.pdf
jobradar search --explain
jobradar tailor --top 5
jobradar serve
```

---

## The dashboard

`jobradar serve` starts a local page on `http://127.0.0.1:8000`.

**First run** collects, in order: who you are and where you work from; your CV (upload or paste); the job titles you are looking for; your filters; and which sources to search. All of it is saved and never asked again — the same values are editable afterwards under **Settings**.

**The board** has eight tabs — Today, Active, Applied, Rejected, Discarded, Closed ads, Filtered out and Insights — with a search box and sorting by focus, match, date or salary. Each job shows both scores, its family, your strongest overlaps, your genuine gaps, the salary with its provenance, the latest reply from your inbox, and anything you should clarify before applying. *Filtered out* lists the ads just short on years in a table of their own; the ones far out of reach are only counted.

**Per job**: open the ad, tailor the CV, write a cover letter or the application email (editable, with warnings, downloadable as PDF), answer the application form's questions, mark it, or delete it. Letters are written on demand, one job at a time, because writing them for every job found is the slowest and most expensive part of any job-search automation and you want them for a handful of jobs. Tick several jobs to delete them at once; every deletion can be undone for a week. **+ Job** adds a job you found yourself.

**Settings** covers everything: your details, target titles, every filter, which sources run and which only on one weekday, the job families and their priority, the mailbox check, the language-model provider, phrases you never use, your skills with their evidence and ceiling, and the CV for each job family.

![Settings](docs/images/settings.png)

---

## Command line

| Command | What it does |
|---|---|
| `jobradar init [--cv FILE] [--config FILE]` | Set up, interactively or from YAML |
| `jobradar demo` | Load the synthetic dataset |
| `jobradar search [--explain] [--no-llm] [--notify] [--refresh]` | Run the pipeline. Ads already on file are not fetched or re-read; `--refresh` forces it |
| `jobradar mail [--days N]` | Read replies to your applications from your inbox (read-only IMAP) |
| `jobradar insights [--runs N]` | The application funnel and each source's record |
| `jobradar sweep [--limit N]` | Retire ads that have closed |
| `jobradar tailor [JOB_ID] [--top N]` | Generate tailored CVs |
| `jobradar lint` | Run the red-flag check on your profile |
| `jobradar jobs [--status ...] [--all]` | List the pipeline, in focus order |
| `jobradar filtered [--restore ID] [--clear]` | What the filters rejected, and why |
| `jobradar export [--format csv\|excel]` | Export everything, including your notes |
| `jobradar notify [--dry-run]` | Send the digest of new jobs |
| `jobradar sources` | Show every source and whether it is on |
| `jobradar serve [--host --port]` | Start the dashboard |
| `jobradar doctor` | Check the installation |

Global flags: `--home DIR` (where the data lives, default `./data`) and `-v` for logging.

---

## Configuration

Everything is stored in `data/jobradar.sqlite3` and edited from the dashboard or `jobradar init`. For unattended installs, `jobradar init --config settings.yaml` loads it from a file instead. Full reference: **[docs/CONFIGURATION.md](docs/CONFIGURATION.md)**.

The filters, briefly:

| Setting | Effect |
|---|---|
| `work_modes` | Which of remote / hybrid / on-site you will take |
| `local_areas` | Places where hybrid and on-site are fine anyway — this is how "remote anywhere, plus an office job in my own city" is expressed |
| `home_country`, `eligible_countries` | Where you may legally be employed |
| `allow_international_remote` | Accept remote roles from abroad when the ad actually permits it |
| `min_salary`, `salary_currency` | The floor, applied to the published figure (top of the band) after conversion at ECB rates; an estimate never drops a job |
| `require_published_salary` | Drop anything whose salary is only an estimate |
| `max_years_experience` | A fixed ceiling. Leave it empty and let the next one work |
| `use_profile_years`, `years_margin` | Take the ceiling from your CV's dates instead, and how far past it still counts as "just short" |
| `weekly_goal` | Applications a week — drives the Today queue |
| `required_keywords`, `excluded_keywords`, `excluded_companies` | Whole words (`java` ≠ "JavaScript"); end with `*` for a prefix |
| `max_age_days`, `keep_undated` | Freshness |
| `prune_after_days` | Close untouched jobs older than this before each search (default 45) |

Three data files hold the shipped vocabulary; most of it is also editable from the dashboard:

- **`src/jobradar/resources/skills.yaml`** — the skill taxonomy. Cross-industry; a skill your field needs can be added in Settings → Your skills, or here for everyone.
- **`src/jobradar/resources/families.yaml`** — the job families, their title keywords and salary bands. Families can be renamed, re-worded, given a priority, switched off or added in Settings.
- **`src/jobradar/resources/salary_bands.yaml`** — how an estimate is adjusted: by seniority, country, kind of employer and a few signals in the ad. Deliberately conservative; treat it as a starting point for your market, not as data.

The `_learning_difficulty` block at the end of `skills.yaml` says how long each gap would take to close — `fast`, `medium` or `slow` — and that is what the coloured gap chips mean. It never decides *what* is a gap (your evidence does that) and it never puts anything on a CV: a "fast" gap goes on the CV once you have actually learnt it, not before.

Secrets live in `.env` (copy `.env.example`) and are never written to the database.

---

## Job sources

Run `jobradar sources` to see the current state. Each adapter declares a tier:

| Tier | Meaning | Default |
|---|---|---|
| **open** | A documented public API or feed intended for programmatic use | On |
| **credentials** | A public API needing a free key you obtain yourself | On once the key is set |
| **restricted** | Reached by parsing pages built for human visitors | **Off** |

Shipped adapters:

| Source | Tier | Notes |
|---|---|---|
| RemoteOK | open | Public JSON feed, remote-only |
| We Work Remotely | open | Category RSS. Its "Anywhere in the World" tag is unreliable, so the ad body always wins |
| Himalayas | open | Publishes structured geographic restrictions — the field that decides whether an international remote job is real for you |
| Arbeitnow | open | Free documented API, strong in the German-speaking market |
| Company career boards | open | Greenhouse, Lever, Ashby, Workable, Recruitee, SmartRecruiters, Personio — auto-detected from a domain |
| Manfred (Spain) | open | Public JSON of a tech board; publishes salary, remote percentage and each skill's required level |
| Adzuna | credentials | ~20 countries, indexes local boards. [Free key](https://developer.adzuna.com/) |
| Jooble | credentials | Worldwide. [Free key](https://jooble.org/api/about) |
| LinkedIn (guest endpoint) | restricted | Highest volume by a distance |
| InfoJobs (Spain) | restricted | Publishes salary, minimum years and required skills |
| Tecnoempleo (Spain) | restricted | Tech-only, labels work mode in the listing |
| Indeed | restricted | Every sector, 25 countries; read through Scrapling's stealth browser |

A source that publishes little can run only once a week (**Settings → Sources → weekly**, and the weekday); every other day it rests.

**About the restricted tier.** These read pages that were built for people, not programs, and the sites' terms may not permit automated access. They are off unless you switch them on by name, having read the warning the dashboard shows. Whether that is acceptable is a decision for the person running the software, under their own jurisdiction and the site's terms — not a default this project should make for you. If you enable one, keep the request delay generous and use it at the volume of a person doing their own job search.

These four are also the only sources that fetch through a real browser (via [Scrapling](https://github.com/D4Vinci/Scrapling)) instead of a plain HTTP request — LinkedIn and Tecnoempleo answer a plain browser fine; InfoJobs' ad page and Indeed need Scrapling's stealth mode to get past the challenge they put up. That needs `scrapling install` once (see [Install](#install)) and is slower per request than plain HTTP, which is exactly why the other sources do not use it: they do not need to. If the browser build Scrapling expects is missing, another installed Chromium is used, and a blocked page or a missing browser is reported once per run instead of silently returning nothing. `scrapling_real_chrome` (off by default) launches your own installed Chrome instead of Scrapling's bundled one, if you want the speed and are running this somewhere interactive rather than on a server.

**The polite defaults apply to every source, browser-fetched or not**: one request per second per host, responses cached for an hour, exponential backoff on 429, and a user agent that says what the software is. `robots.txt` is honoured by every open and credentials source. The restricted sources do not consult it: those sites disallow every automated visitor in it, so honouring it would mean the adapters you deliberately switched on never fetch anything — switching one on is the decision the file would otherwise make for you.

Adding a source is one file and one registry line — see **[docs/SOURCES.md](docs/SOURCES.md)**.

---

## Using a language model (optional)

Everything works without one. With `provider = "none"` JobRadar reads ads with a keyword taxonomy, writes summaries from a template filled with your own material, and produces letter skeletons with the parts that need a human marked in brackets.

A model improves five things: reading an ambiguous ad (including one you add by hand), importing a CV into a structured profile, writing the tailored summary, writing letters, and answering application-form questions. Without one, a form question gets your most relevant achievement or a saved answer from the bank as a starting point. It is spoken to over plain HTTP, so enabling it adds no Python dependency.

```bash
JOBRADAR_LLM_PROVIDER=anthropic          # or openai, gemini, openai-compatible, ollama
JOBRADAR_LLM_MODEL=claude-sonnet-4-5
ANTHROPIC_API_KEY=...
```

For Google Gemini, get a key from Google AI Studio and set:

```bash
JOBRADAR_LLM_PROVIDER=gemini
JOBRADAR_LLM_MODEL=                      # blank = gemini-3.5-flash
GEMINI_API_KEY=...
```

The provider can also be picked in the dashboard's Settings; variables set in
`.env` win over it. `jobradar doctor` shows which provider is in use and
whether it is usable.

Gemini's free tier allows only a few dozen requests a day **per model**, and
its newest models are often refused with "high demand". JobRadar retries busy
answers, and when a model is still busy, retired or out of its daily quota it
moves on to the next one in `JOBRADAR_LLM_FALLBACK_MODELS` (by default
`gemini-3.6-flash`, `gemini-3.5-flash-lite`, `gemini-3.1-flash-lite`). When
every model is spent the run carries on without one. For daily searches that
read dozens of ads, lower `max_calls_per_run` or use a paid key.

`ollama` and `openai-compatible` point at a local server, so you can run the whole thing offline. `max_calls_per_run` caps the spend of an unattended run; `jobradar search --no-llm` forces the deterministic path for one run.

Whatever the model writes still goes through the validator. A draft that invents anything is discarded, not shipped.

---

## Running it on a schedule

The point of a scheduled search is not having to check anything, so it only works if the run can reach you. Configure a digest (email or Telegram) in `.env`, enable it in Settings, and run:

```bash
jobradar sweep && jobradar search --notify
```

Nothing is sent when there is nothing new — a daily "0 new jobs" message is one you learn to ignore, and then you miss the one that matters. Recipes for cron, systemd, Windows Task Scheduler and GitHub Actions are in **[docs/SCHEDULING.md](docs/SCHEDULING.md)**.

---

## Repository layout

```
src/jobradar/
├── models.py            Shared data structures
├── config.py            Settings, filters, filesystem layout
├── storage.py           SQLite persistence
├── taxonomy.py          The skill vocabulary
├── textutils.py         Reading facts out of ad text, no model needed
├── sources/             One file per job board
│   ├── base.py          The plugin contract + the polite HTTP client
│   └── optional/        Opt-in adapters, off by default
├── families.py          Job families: classification, priority, salary band
├── insights.py          The application funnel and the run history
├── pipeline/            search · dedupe · filters · salary · scoring · sweep
├── profile/             CV import, evidence and ceiling derivation, skill edits
├── documents/           Tailoring, rendering, the built-in PDF writer, letters,
│                        form answers, the validator and the text review
│   └── templates/       CV templates (single column, ATS-safe)
├── lint/                The recruiter red-flag rules
├── llm/                 Provider-agnostic client and every prompt
├── web/                 FastAPI dashboard: one page, plain scripts in static/, no CDN
├── exporters/           CSV and Excel
├── mail/                Reading replies over IMAP (read-only) and matching them
├── notify/              Email and Telegram digests
└── resources/           skills.yaml · families.yaml · countries.yaml · salary_bands.yaml · demo data
```

**[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)** explains why the pipeline is ordered the way it is and where to hook in.

---

## Privacy and data

- Everything lives in `data/`, which is git-ignored. Your CV, contact details and job-search history never leave your machine.
- The dashboard binds to `127.0.0.1`. Exposing it takes an explicit `--host`, and you should think before doing so: there is no login.
- Binding to loopback does not stop a web page open in the same browser from posting to it, so the server also refuses requests whose `Host` is not a name it was started for (defeats DNS rebinding) and any change coming from another origin. The CLI and scripts, which send no `Origin`, are unaffected. With `--host 0.0.0.0` the host check is off unless you set `JOBRADAR_ALLOWED_HOSTS`.
- The page loads no external assets — no CDN, no fonts, no analytics. It works offline.
- Outbound requests go to the job boards you enabled, the ECB (for exchange rates), your language-model provider and your mail server if you configured them. Nothing else.
- The mailbox is opened read-only: messages are never marked as read, moved or deleted, and only the replies matched to an application (sender, subject, one quoted sentence) are stored.
- API keys are read from the environment and are never written to the database or included in an export.

---

## Limitations, honestly

- **Your CV's layout is not reproduced pixel for pixel.** Its *content* is imported into a structured profile and re-rendered with a template. That is the trade: a structured profile can be tailored, scored and validated per job; a pixel-perfect copy can only be reprinted. Anything claiming otherwise from an arbitrary PDF is overselling.
- **Importing without a language model is approximate.** The heuristic parser finds your contact details, sections, positions and bullets, and gets dates roughly right. Review it before generating anything — the dashboard tells you exactly this after an import.
- **Salary estimates are estimates.** They come from an editable table, not from market data. They are always labelled.
- **Restricted sources can break.** They read pages that change without notice. That is part of why they are opt-in. Fetching them through a real browser (Scrapling) is markedly more resilient than a plain HTTP request, but it is not a guarantee — a site can still change what it blocks.
- **The score is a triage aid, not a verdict.** It measures overlap between an ad's stated requirements and your evidenced skills. It knows nothing about whether you would enjoy the job.

---

## Contributing

New source adapters, taxonomy entries for under-covered fields, salary bands for more countries, CV templates and linter rules are all welcome. **[CONTRIBUTING.md](CONTRIBUTING.md)** has the details; the test suite is fully offline, so `pytest` needs no network and no keys.

## Licence

MIT — see [LICENSE](LICENSE).
