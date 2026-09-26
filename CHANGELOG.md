# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project uses
[semantic versioning](https://semver.org/).

## Unreleased

## 1.4.0 — 2026-09-26

### Added

- **`pip install jobradar-cv`**: the package is published on PyPI when a
  version is tagged, and tested on Linux, Windows and macOS. The command is
  still `jobradar`; `jobradar` itself was too close to an existing project.
- **SECURITY.md**: how to report a vulnerability privately.
- **Docker**: `docker compose up -d` runs the dashboard with its data in a
  volume, as a non-root user, on the host's loopback only.
- **The dashboard in Spanish.** Every screen, message, alert, filter reason,
  linter finding and error is shown in English or Spanish — the browser's
  language by default, or the one chosen under Settings → Interface language.
  What you or an employer wrote (your CV, notes, ads, emails) is never
  translated.
- **Bundesagentur für Arbeit** (Germany's public employment service, every
  sector) as an open source; it runs only when Germany is one of your
  countries.
- **A vocabulary for every sector.** The skill taxonomy grows from 146 to
  over 250 skills: in-depth healthcare (nursing, triage, ICU, emergency care,
  theatre, midwifery, physiotherapy, pharmacy…), law (litigation, civil,
  criminal, corporate/M&A, tax, public procurement, data protection, bar
  admission…), education (primary and secondary teaching, TEFL/CELTA, CLIL,
  vocational training, tutoring…), care and social work, hospitality,
  retail, office, finance and insurance, logistics, trades and construction,
  public services, agriculture, science and management — with English and
  Spanish aliases.
- **Accent-insensitive matching**: "atencion" and "atención" are the same
  skill, in ads, CVs and skill names.
- **Demo profiles for other kinds of work**: `jobradar demo --profile nurse`,
  `lawyer` or `teacher` (Spanish and English CVs and ads), besides `data`.
- **Board filters**: text, work mode, where (your areas, your country, abroad,
  not stated), job family, source, language, minimum salary (midpoint of the
  band) and minimum match, with a count of what is shown and one button to
  clear them. They only narrow the view — nothing is rejected — and are
  remembered in the browser.
- **Job families for any kind of work.** 23 families (healthcare, care,
  education, logistics, hospitality, retail, trades, construction, finance,
  software and more, plus *General*) in `resources/families.yaml`, assigned
  from the title and the start of the ad. Rename, re-word, switch off or add
  families in Settings, and give one a priority to move it up or down the
  board (the match score never changes).
- **Salary estimates that know who is hiring.** The family's band × the
  hiring country (not yours, for a remote job abroad) × the kind of employer
  (public sector, non-profit, staffing agency, large company, startup, small
  business) × at most two signals from the ad; rounded to thousands. A
  published band that misses the floor only through the exchange rate (within
  10 %) is kept with a note.
- **Replies in your inbox** (`jobradar mail`, *Check email*, or after each
  search): read-only IMAP, each reply matched to its application and classed
  as rejection, next step or automatic acknowledgement, with the sentence it
  was decided on. Proposed interview times become a calendar file. Replies to
  jobs not marked as applied are listed apart. Nothing changes a stage on its
  own. Configure with `JOBRADAR_IMAP_*`.
- **Insights** tab and `jobradar insights`: replies by source, job family and
  match-score band (rates from five applications up), median wait for a
  reply, companies that never answer, the longest waits; per source over past
  runs, what was fetched, kept, failed and skipped, what the filters removed
  and how long runs take.
- **Sources**: Manfred (open, public JSON with each skill's required level)
  and Indeed (restricted, 25 countries, through Scrapling's stealth browser).
  Any source can run **once a week** on a chosen day. LinkedIn reads the
  work-mode badge of ads whose text does not settle it, and pages through
  results ten at a time as the guest endpoint does.
- **A CV per job family**: a fixed headline, which achievements lead or are
  left out, which skill groups come first or are left out, and extra skills —
  only selecting and ordering what the profile holds. An "Also" line names up
  to four skills the ad asks for that the profile proves and the groups shown
  omit.
- **A PDF without a browser.** A built-in PDF writer prints the CV (with the
  same shrink-to-fit) when Chromium is missing or fails, or always with
  `cv_pdf_engine: builtin`. Cover letters and emails are editable, saved, and
  download as PDF.
- **Form answers and the answer bank.** A thread per job for the free-text
  questions of application forms: the form's limit in characters or words,
  refinements in the same thread, `[pending: …]` instead of invented figures,
  hand edits. Saved answers come back as precedents for similar questions at
  other companies.
- **Warnings on letters, emails and answers** (never blocking, re-checked
  whenever a saved text is shown): figures in neither the profile nor the ad,
  inflated years, unproven skills, template phrases plus your own
  (`banned_phrases`), a company never named, an email without subject or
  `[name]`, brackets still to fill, answers over the limit.
- **+ Job**: add a job found elsewhere; it is read like a board's ad, scored,
  and tracked with a starting status, stage and notes.
- **Delete jobs**, one or a selection: everything attached goes, a search
  does not bring the ad back, and it can be undone for a week.
- **Just short on years**: *Filtered out* lists ads within your years margin
  in their own table, recomputed live; the ones far out of reach are only
  counted. Saving settings that now cover an ad's years puts it back at once.
- **Your skills in Settings**: edit the CV's skill groups; add, edit and
  delete skills with their evidence and ceiling. Unknown names become your own
  skills (with other names they go by in ads) and are read in ads from then
  on. Deleted skills stay deleted, even through a new CV import, which also
  keeps your own skills, tuned ceilings and CVs per job family.
- **Linter rules on the evidence model**: `position-without-achievements`,
  `unproven-evidence`, `impossible-ceiling`, `unknown-listed-skills`.
- `MailError` joins the exception hierarchy.
- **Google Gemini as a language model**, selectable in the dashboard's
  Settings or with `JOBRADAR_LLM_PROVIDER=gemini` and `GEMINI_API_KEY` (or
  `GOOGLE_API_KEY`). The default model is `gemini-3.5-flash`. Thinking is
  kept low so it cannot use up the output budget and leave the answer empty;
  JSON is requested natively when importing a CV or reading an ad; blocked,
  cut-off and invalid-key answers are reported (Gemini signals a bad key with
  HTTP 400, which now stops the run from calling it again).
- **The PDF no longer needs Playwright's exact browser build.** When the
  build a Playwright version expects is missing, the CV is printed with
  another installed Chromium (an older or newer Playwright build, or a system
  Chromium/Chrome), or the one named in `JOBRADAR_CHROMIUM_PATH`.
  `jobradar doctor` reports which browser will be used.
- **Language-model calls survive a busy or rationed provider.** Rate limits
  and 5xx answers are retried with a backoff (honouring `Retry-After` and
  Google's `RetryInfo`). A model that is still busy, retired (404) or out of
  its daily quota hands over to the next one in `llm.fallback_models` /
  `JOBRADAR_LLM_FALLBACK_MODELS`; Gemini ships a default list, because its
  free tier gives each model only a small daily quota.
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

### Removed

- The `llm` install extra, and `anthropic` / `openai` from `all`: no code used
  them. Every language-model provider is called over plain HTTP.

### Fixed

- **LinkedIn, InfoJobs and Indeed returned no jobs.** Three causes stacked:
  Scrapling rejected `retries=0`, their `robots.txt` disallows every
  automated visitor (restricted sources, which the user switches on
  deliberately, no longer consult it), and a Playwright upgrade left Scrapling
  without the browser build it expects (another installed Chromium is now
  used). A blocked page or a missing browser is reported once per run instead
  of an empty result.
- The CV's education section: dates and notes on their own line are joined to
  the entry above; an undated entry no longer reads "present"; a
  certification's year is no longer printed twice; "CI/CD" in a skills list
  stays one skill.
- A generated CV or letter vanished from the job card as soon as the board
  refreshed. Clicking *Cover letter* again rewrote the letter over your edits;
  it now opens the saved one.
- The office-suite skill matched the plain words "word" and "outlook".
- Data attributes and ARIA attributes on dashboard elements were set as
  properties and lost, so the evidence and ceiling editor saved nothing.
- **A CV imported with a language model had no usable skills.** The prompt
  did not say which skill keys exist, so a model named its own
  (`languages`, `data-ml`); nothing matched any ad, scores were wrong, and
  every generated summary and letter was rejected as "invented". Evidence is
  now always derived from the CV text, the prompt lists the valid keys, and
  the model's numbers only refine skills the taxonomy recognises.
- **Honest letters were rejected.** "I have not worked with MLOps" counted as
  claiming MLOps. A skill now counts as claimed only in a clause that does not
  deny it ("not only" still counts as a claim).
- A Gemini answer cut off at the output limit is discarded instead of used
  half-written, and Gemini gets extra output room for its thinking, which
  counts against the same limit.
- `JOBRADAR_LLM_PROVIDER`, `JOBRADAR_LLM_MODEL` and `JOBRADAR_LLM_BASE_URL`
  were documented but never read. They now override the provider stored in
  Settings (empty or `none` leaves it alone); `--no-llm` still wins over them.
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
