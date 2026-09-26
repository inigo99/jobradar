# Architecture

This document explains why JobRadar is put together the way it is. If you only
want to use it, the README is enough; read this before changing the pipeline or
adding a stage.

## The shape of the thing

```
sources/                 pipeline/                       documents/
┌──────────────┐   ┌──────────────────────────┐   ┌────────────────────────┐
│ RemoteOK     │   │ collect                  │   │ tailor  (headline,     │
│ Himalayas    │──▶│   ↓                      │   │          summary,      │
│ Arbeitnow    │   │ deduplicate              │   │          bullet order) │
│ WWR          │   │   ↓                      │   │   ↓                    │
│ ATS boards   │   │ prefilter (age, closed,  │   │ validate ◀── profile   │
│ Manfred      │   │            deleted)      │   │   ↓                    │
│ Adzuna       │   │   ↓                      │   │   │                    │
│ Jooble       │   │ enrich  ◀── llm (opt.)   │   │ render → one-page PDF  │
│ (opt-in ones)│   │   ↓                      │   │   ↓                    │
└──────────────┘   │ filter                   │   │ lint                   │
                   │   ↓                      │   └────────────────────────┘
                   │ score   ◀── profile      │
                   │   ↓                      │            web/  ·  cli.py
                   │ store                    │      both call the same code
                   └──────────────────────────┘
                              storage.py (SQLite)
```

Every arrow is a function call in `pipeline/search.py`. There is no queue, no
scheduler and no background worker: a run is a single pass that either finishes
or does not, which is the right shape for something a person runs once a day.

## Why the stages are in that order

**Deduplicate before enriching.** Enrichment is the expensive stage — a page
fetch and possibly a model call per job. On a multi-source run a substantial
share of the collected jobs are the same opening seen twice, so collapsing them
first cuts the bill by roughly the duplication rate.

**Prefilter before enriching too.** Age, previously-closed and deleted-by-you
checks need no ad body. Running them early avoids fetching ads that are
already disqualified. This is why `_prefilter` exists separately from
`apply_filters`.

**Filter after enriching.** Work mode, geography and salary can only be judged
from the full ad. The listing metadata is wrong often enough — LinkedIn's
remote tag, We Work Remotely's region tag — that trusting it defeats the point.

**Classify and price during enrichment.** The job family comes from the title
and the start of the ad (`families.classify`), and the salary estimate starts
from the family's band, so both need the enriched text but nothing after it.

**Score last.** Scoring needs the requirements that enrichment produced, and it
is cheap, so it happens once per surviving job.

After the run, if a mailbox is configured and `mail.check_after_search` is on,
`mail.check_mail` reads the replies since the last check. It is a separate
step with its own error: a mail server that is down never fails a search.

## The layers, and what each may depend on

| Layer | May import | Must not import |
|---|---|---|
| `models`, `taxonomy`, `textutils` | stdlib, pydantic | anything else in the package |
| `config`, `storage`, `families` | models, taxonomy, textutils | pipeline, documents, web |
| `sources/*` | models, config, textutils | pipeline, documents, storage |
| `pipeline/*`, `insights` | everything above, `llm` | documents, web |
| `profile/*`, `documents/*`, `lint/*`, `mail/*` | everything above | web |
| `i18n` | taxonomy | everything else |
| `web`, `cli` | everything | — |

The rule that matters: **a source never touches the database and never decides
whether a job is wanted.** It fetches and parses; the pipeline judges. That is
what lets a source be tested with no database and swapped for a fake in the
suite, and it is why the whole test suite runs offline.

## The profile is the contract

`models.Profile` is the centre of the system. The scorer measures against it,
the tailoring step draws from it, the validator refuses anything a document
says that it does not support, and the linter checks it. Three fields carry the
weight:

- `experience[].bullets` — the candidate's achievements, in their own words,
  written once and reused. Reordered per job; never rewritten.
- `evidence` — how strongly the CV proves each skill today.
- `ceiling` — how far tailoring may push each skill.

`promoted_prominence()` in `pipeline/scoring.py` is four lines long and is the
anti-fabrication lock in its entirety: evidence `0.0` returns `0.0`, always. If
you change one function in this codebase, do not change that one without
understanding what it protects.

## Two paths through everything

Any stage that benefits from judgement has a deterministic implementation and a
model-assisted one, producing the same type:

| Stage | Without a model | With one |
|---|---|---|
| Reading an ad | `taxonomy.find_skills` + section weighting | `prompts.read_job_ad` |
| Importing a CV | section-and-bullet heuristics | `prompts.parse_cv` |
| Headline and summary | template filled from the profile | `prompts.tailor_cv` |
| Letters | skeleton with bracketed gaps | `prompts.cover_letter` / `recruiter_email` |
| Form answers | a saved answer from the bank, or the best achievement plus `[pending: …]` | `prompts.form_answer` |
| A job added by hand | the same rules as any ad | `prompts.read_job_ad` |
| Replies in the inbox | rule-based, English and Spanish | — (no model: a person's reply is quoted, not interpreted) |

The deterministic path is not a stub — it is the fallback that runs whenever a
key is missing, a request fails, a budget is exhausted, or a draft fails
validation. Every call site treats a `None` from the LLM client as "carry on
without it", so a model outage degrades quality and never breaks a run.

## Storage rules

Two invariants in `storage.py` are worth knowing before you write to it:

1. **The pipeline never deletes a job.** An ad that disappears is marked
   `closed`. Deleting it would orphan the user's tracking record and the job
   would reappear as new next week. Only the user deletes a job
   (`Database.delete_jobs`), and then everything attached goes with it, the
   id is remembered so a search does not add the ad back, and a snapshot is
   kept for a week so the deletion can be undone.
2. **The pipeline never writes to `applications`.** That table is the user's.
   Search runs update job data around it; the triage state, stage and notes are
   only ever written at the user's request.

`documents_kv` holds the settings, the profile, the replies read from the
inbox, each job's form-answer thread (`answers:<job id>`), the answer bank and
the deleted-jobs list as JSON documents, so the pydantic models are the schema
of record and adding a field needs no migration.

Skills the user adds by hand (`Profile.custom_skills`) are registered with the
taxonomy every time the profile is loaded or saved
(`taxonomy.use_custom_skills`), so ads mentioning them are read like any other.

## Where to hook in

| You want to | Change |
|---|---|
| Add a job board | One file in `sources/`, one line in `sources/__init__.py`. See [SOURCES.md](SOURCES.md) |
| Add a filter rule | A `_check_*` function in `pipeline/filters.py`, added to the tuple in `apply_filters`. Rejections are stored, so give yours a reason a person can argue with |
| Change the triage order | `pipeline/focus.py`. It is computed at display time and stored nowhere, so it can never go stale |
| Say how hard a skill is to pick up | The `_learning_difficulty` block in `resources/skills.yaml` |
| Add a linter rule | A generator in `lint/rules.py`, added to `PROFILE_RULES` |
| Add a warning on letters and answers | A `check_*` function in `documents/review.py`, added to `review_text` |
| Add or reshape a job family | `resources/families.yaml` (keywords and salary bands); users override it in Settings |
| Recognise another kind of reply | The phrase lists in `mail/classify.py` |
| Add a CV template | An HTML file in `documents/templates/`; keep it one column, real text, nothing in the margins |
| Cover a new field of work | Keys in `resources/skills.yaml`; a family with its bands in `resources/families.yaml` |
| Support another country | An entry in `resources/countries.yaml` |
| Translate a new message | Browser text: `web/static/dashboard-i18n-es.js`. Server text: `resources/i18n/es.yaml`, applied at the API boundary by `web/localize.py` (stored text stays English, so a language switch never needs a migration) |
| Change what a model is asked | `llm/prompts.py` — every prompt is a plain function returning `(system, user)`, so they can be diffed and tested |

## Two things deliberately not stored

**Focus** is computed on every request from the job's age, its title and the
candidate's years. Storing it would mean a number that was true the morning it
was written and quietly wrong a week later, and staleness in a ranking is worse
than recomputing a multiplication.

**Filtered-out ads** are the mirror image: they *are* stored, including the
whole job, because the alternative is a count. A count tells you that forty
things were rejected; it does not let you look at the fourth one and realise
your salary floor is wrong.
