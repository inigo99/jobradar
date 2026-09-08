# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project uses
[semantic versioning](https://semver.org/).

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
