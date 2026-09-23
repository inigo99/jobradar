# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project uses
[semantic versioning](https://semver.org/).

## 1.2.0 — 2026-09-23

### Added

- **The `restricted` sources now fetch through a real browser.** LinkedIn,
  InfoJobs and Tecnoempleo route their requests through
  [Scrapling](https://github.com/D4Vinci/Scrapling) (`Fetcher.get(...,
  browser="dynamic" | "stealthy")`) instead of a plain HTTP request, which is
  what a page built for a browser actually expects. InfoJobs' ad page
  specifically needs `"stealthy"` — it answers a plain browser with an HTTP
  405 behind a CAPTCHA challenge that stealth mode gets past. The other six
  sources are unaffected and keep using plain HTTP, which is faster and is
  all they need.
- `scrapling[fetchers]` is a new core dependency. Its browsers are a separate,
  one-time download: `scrapling install`, needed only if you enable one of
  the three sources above — see the README's [Install](README.md#install)
  and [Job sources](README.md#job-sources) sections.
- `SourceSettings.scrapling_real_chrome` (off by default) launches your own
  installed Chrome for those three sources instead of Scrapling's bundled
  browser, for anyone running JobRadar interactively who wants the speed.

## 1.1.0 — 2026-09-11

### Added

- **Filtered out.** Rejected ads are kept with their reason instead of being
  discarded, with a tally by filter and by the exact wording, and a button to
  put one back. A filter one notch too strict used to be invisible: its victims
  vanished, and an empty board looked the same as a quiet day.
  `jobradar filtered` does the same from the terminal.
- **Focus ordering.** The board and `jobradar jobs` are ordered by focus: the
  match score less what is already known to go nowhere — ads that have aged
  past the point of a reply, titles pitched above the candidate's years — plus
  a nudge for ads that publish a band. Every job carries one sentence saying
  why. Nothing is stored, so it cannot go stale, and `score.tailored` is
  untouched.
- **Today.** A six-job queue in focus order with a weekly application counter
  and goal (`weekly_goal`, `today_queue_size`).
- **Learning difficulty.** Every gap is marked `fast`, `medium` or `slow` —
  how realistic it is to close before an interview. Configured in the
  `_learning_difficulty` block of `skills.yaml`. It never decides what counts
  as a gap and never puts anything on a CV.
- **The years ceiling comes from the CV.** `use_profile_years` (on by default)
  takes it from the profile's own dates, so it rises on its own instead of
  ageing quietly; `years_margin` separates the ads missed by a hair from the
  ones far out of reach. An explicit `max_years_experience` still wins, and an
  ad that states no minimum is still never filtered on years.

### Changed

- `apply_filters` takes an optional `profile_years`.
- `MatchScore` gained `gap_details`; `JobView` gained `focus`, `focus_reason`
  and `gap_details`. Both are additive: old databases load unchanged.

## [1.0.0] — 2026-09-08

First public release.

### Added

- **Search pipeline** across ten source adapters: RemoteOK, We Work Remotely,
  Himalayas, Arbeitnow and company career boards (Greenhouse, Lever, Ashby,
  Workable, Recruitee, SmartRecruiters, Personio) by default; Adzuna and Jooble
  once a free key is present; LinkedIn, InfoJobs and Tecnoempleo as opt-in
  adapters that are never enabled automatically.
- **Deduplication** on job id, company-and-title fingerprint and token overlap,
  keeping the most informative record of each opening.
- **Filter chain** for work mode, geography, salary, seniority, recency,
  keywords and companies, with a reason recorded for every rejection and
  `--explain` to summarise them.
- **Salary handling**: published figures parsed from ad text, estimates from an
  editable reference table when nothing is published, and conversion at ECB
  reference rates.
- **Match scoring** with the evidence/ceiling model, including the
  anti-fabrication lock: a skill with no evidence can never be promoted.
- **CV import** from PDF, DOCX or plain text, with a heuristic parser that needs
  no language model and a better model-assisted path when one is configured.
- **Per-job tailoring**: headline, summary, achievement order and skill-group
  order, rendered to a one-page PDF that shrinks type to fit rather than cutting
  content. Three ATS-safe single-column templates.
- **Anti-fabrication validator** catching invented skills, invented figures and
  inflated seniority in any generated text.
- **Recruiter red-flag linter** with twenty rules across structure, history,
  achievement writing, the summary and the skills block.
- **Cover letters and application emails**, generated on demand per job.
- **Local dashboard**: first-run wizard, settings panel, five tracking tabs,
  per-job document generation. One self-contained page, no external assets.
- **Command line** covering the whole pipeline for unattended runs.
- **Application tracking** with status, stage, dates and notes, kept strictly
  separate from pipeline-owned data.
- **Closed-ad sweep** that never retires a job the user has touched.
- **Exports** to CSV and Excel, and digests over email and Telegram.
- **Optional language model** support for Anthropic, OpenAI, any
  OpenAI-compatible endpoint and Ollama, over plain HTTP with no extra
  dependency and a hard per-run call budget.
- Documentation: architecture, configuration, sources, tailoring, scheduling and
  an FAQ.
