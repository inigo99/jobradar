# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project uses
[semantic versioning](https://semver.org/).

## Unreleased

### Added

- **Errors that say what to do.** A new `jobradar.errors` module gives every
  failure a user can cause or fix its own exception — `ConfigError`,
  `SetupRequiredError`, `NotFoundError`, `MissingDependencyError`,
  `ProfileError`, `StorageError`, `RenderError`, `ExportError`, `LLMError` —
  with a message and a hint. The command line prints them to stderr and exits
  non-zero instead of showing a traceback (`-v` still shows it). The dashboard
  returns them as JSON with a matching HTTP status, and the page shows the hint.
- Clear messages for: a missing, non-YAML or invalid settings file (naming the
  field); an unwritable data directory; a locked, read-only or damaged
  database; corrupt stored records (one bad job is skipped, not the board);
  missing, encrypted, corrupt or unsupported CV files (`.doc`, images); an
  export path that is a folder or cannot be written; an unknown LLM provider or
  a missing API key (naming the variable); a rejected key or unknown model
  (the run stops calling the provider); SMTP and Telegram failures by cause;
  unknown source ids in `sources.enabled`; and settings that leave no source
  able to run.
- `--limit`, `--top` and `--port` reject values that make no sense.

### Fixed

- **Security: CV uploads could be written outside the uploads folder** through
  a file name such as `../../x`. Only the base name is used now, and uploads
  are capped at 10 MB.
- **Security: the dashboard returned internal error text to the browser.**
  Unexpected errors now return a generic message; the details go to the
  server log.
- Job titles kept board noise such as "(Remote)" and "(80% remote)": the
  pattern that strips it had been corrupted.
- Two anonymous ads (no company) with the same title were merged into one
  when the board sent `""` rather than `null`. Without a company or a title,
  ads are now only merged by id or URL.
- `Job` fields that boards send as `null` are normalised to `""`, `[]` or an
  unknown salary on the way in and on assignment, instead of being optional
  everywhere.
- The database closes the connections of every thread, not only the caller's.
- A cache directory or exchange-rate cache that cannot be written no longer
  stops a search.
- Restored the design notes removed from docstrings and comments.

## 1.3.0 — 2026-09-23

Most of these fixes come from a personal radar that shares its rules with
JobRadar and runs them against real ads every day; each one is a sentence or a
situation that gave a wrong answer, and each has a regression test in
`tests/test_hardening.py`.

### Fixed

- **Work mode read negations and office days wrong.** "This is not a remote
  position" came out remote, "work from home (2 days per week)" came out remote
  and "Fully remote. No hybrid" came out hybrid. Detection now matches whole
  words, understands negations and looks for office days anywhere in the text.
- **LinkedIn wiped the board's remote tag.** `detect_work_mode(...) or
  job.work_mode` never fell back, because `WorkMode.UNKNOWN` is truthy. Cards
  found through LinkedIn's remote filter are now tagged remote, and when the ad
  text says nothing about it the tag is kept with an alert instead of lost.
- **Residency sentences dropped jobs they allowed.** "Must be eligible to work
  in the EU" and "Must reside in Spain" were read as "restricted to some other
  country" and rejected. The countries or region the sentence names are now
  read out of it; a sentence that names none keeps the job, with an alert
  quoting it.
- **Years of experience.** "Más de 5 años" was not recognised and "entre 6 y 9
  años" was read as 9. Ranges now count by their lower bound, and when an ad
  states several figures the overall one (the largest) wins.
- **Keyword and company lists matched substrings.** An excluded `java` dropped
  "JavaScript Engineer" and an excluded `Alan` dropped "Talan". They now match
  whole words; end an entry with `*` for a prefix. `local_areas` follow the
  same rule and no longer look at the company name.
- **An estimated salary could reject a job.** Only a published figure can now;
  an estimate below the floor is kept with a warning. A published band is
  judged by its top, so a 36–45k band is not dropped for a 40k floor.
- **CI never ran on push**: the workflow listened to `main`, the branch is
  `master`.

### Added

- **Ads already on file are not read again.** Each run used to fetch the full
  ad (a real browser for LinkedIn/InfoJobs/Tecnoempleo) and, with a model
  configured, pay for a new reading of every job still listed. The stored
  reading is now reused; filters and score are re-applied. `jobradar search
  --refresh` forces a full re-read — run it once after upgrading so existing
  jobs get the new rules.
- **Reposts and cross-board copies of a job on file** are recognised, closed
  and aged-out jobs included, and filed under *Filtered out → duplicate* with
  the job they match. Company names lose their legal form ("Talan España,
  S.L.U." = "Talan") and titles the tags boards add ("(m/f/d)", "100% remoto",
  "Senior"); a shared URL counts only within one company.
- **`prune_after_days`** (default 45): untouched jobs older than that are
  closed before each search, without fetching anything. Jobs you applied to,
  discarded or annotated are never touched.
- **Per-run counters** in the run log and the CLI: reused, duplicates of jobs
  on file, pruned, and fetched/kept per source.
- **The dashboard refuses cross-site requests.** A `Host` allowlist (loopback
  by default, `JOBRADAR_ALLOWED_HOSTS` to extend) and an `Origin` /
  `Sec-Fetch-Site` check on every request that changes something. Before, any
  page open in the same browser could post the onboarding form and overwrite
  the profile, or start a search.
- The literal sentences behind the work-mode and residency decisions are kept
  on the job (`raw.work_mode_evidence`, `raw.remote_scope_evidence`).

### Changed

- `create_app()` takes `allowed_hosts`; `SearchPipeline` and `run_search()`
  take `refresh`; `SearchRun` gained `reused`, `known_duplicates`, `pruned` and
  `by_source`; `Settings` gained `prune_after_days`. All additive: old
  databases load unchanged.
- `__version__` now matches the package version (it had stayed at 1.1.0).

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
