# FAQ

### Do I need an API key or a paid model?

No. With `provider: none` JobRadar searches, deduplicates, filters, prices,
scores, renders a tailored one-page CV, lints it and tracks your applications.
A model improves how ambiguous ads are read and how the summary is written; it
is not required for anything.

### Will it apply to jobs for me?

No, and it will not. The button opens the advertisement. Mass-applying is the
one thing that reliably damages a job search, and building it would make
everything else in the project less trustworthy.

### Why is my dashboard empty after a search?

Almost always a filter. Run `jobradar search --explain` — it prints the tally of
why jobs were dropped. The usual culprits are a salary floor combined with
`require_published_salary`, a `max_age_days` of 1, or `work_modes: [remote]`
with no `local_areas` in a market where most roles are hybrid.

### Why did it keep a job whose remote scope is "unknown"?

Because dropping it would lose real opportunities. Ads very often do not say
which countries a remote role may be performed from, and "remote" in a city
usually means remote within that country. JobRadar keeps the job, adds an alert,
and the generated application email asks the question.

### The salary shown is not what the ad says.

If it is marked *(estimated)*, the ad published nothing and JobRadar estimated
it: the job family's band, adjusted for the hiring country, the kind of
employer and up to two signals in the ad (see
[CONFIGURATION.md](CONFIGURATION.md#salary-estimates)). Expand the job to see
the reasoning. The bands are in **Settings → Job families** and
`resources/families.yaml`; the adjustments in `resources/salary_bands.yaml`.
The shipped numbers are a conservative starting point, not data.

### My imported CV came out wrong.

Without a language model the parser is heuristic: it finds contact details,
sections, positions and bullets, and gets dates roughly right. Fix the skills in
**Settings → Your skills**, or re-import with a model configured, which is
markedly better (your own skills, deletions and tuned ceilings are kept). Either way, review before generating anything: everything
downstream trusts the profile.

### Can it reproduce my CV's exact layout?

No, and anything claiming to from an arbitrary PDF is overselling. The
*content* is imported into a structured profile and re-rendered with one of
three templates. That is the trade worth making: a structured profile can be
tailored, scored and validated per job; a pixel-perfect copy can only be
reprinted. All three templates are single-column, real-text and machine
readable, which is what applicant tracking systems need.

### Why is my CV two pages?

The renderer shrinks type in small steps and stops at the smallest readable
size. If it still does not fit you have more content than a page holds; the
linter says so and the answer is to cut the oldest position's weakest
achievement, which is the one a reader is least likely to reach.

### Can I use a local model?

Yes. Set `provider: ollama` (or `openai-compatible` with a `base_url`) and
JobRadar talks to a local server. Combined with sources that need no key, the
whole thing runs offline.

### Is LinkedIn supported?

There is an adapter, and it is off by default. LinkedIn's User Agreement
restricts automated access, so enabling it is a decision only you can make for
yourself, under your own jurisdiction. The same applies to InfoJobs,
Tecnoempleo and Indeed. Everything in the default set is a public API or feed
meant to be read programmatically.

### I enabled LinkedIn (or Indeed) and it finds nothing.

Run `jobradar doctor`, then a search, and read the run summary: a missing
browser (`scrapling install`), a browser build that will not start, or a page
the site blocked is reported there once instead of silently returning nothing.
JobRadar falls back to any other Chromium it finds, or the one in
`JOBRADAR_CHROMIUM_PATH`. A blocked page usually clears with a longer
`request_delay`.

### Does anything leave my machine?

Requests to the job boards you enabled, to the ECB for exchange rates, to your
model provider and to your mail server if you configured them. Nothing else. The dashboard loads no
external assets and binds to `127.0.0.1`. Your CV and history stay in `data/`,
which is git-ignored.

### How do I search a specific company?

Add its domain under **Settings → Companies to watch**. JobRadar detects which
applicant tracking system it uses and reads that board's API directly — which is
both more reliable and more polite than scraping the careers page.

### It is not finding jobs in my field.

First the search terms: **Settings → What you're looking for** are sent as they
are to every source. Then the vocabulary: a skill your field needs can be added
in **Settings → Your skills**, and a job family in **Settings → Job families**
(title keywords, and a salary band in `resources/families.yaml`). For everyone,
`resources/skills.yaml` and `resources/families.yaml` are plain YAML, and a
pull request adding coverage for an under-served field is very welcome.

### Can it read replies to my applications?

Yes, if you want it to: set `JOBRADAR_IMAP_*` in `.env` (with an app password)
and switch on **Settings → Email**. It opens the mailbox read-only, matches
replies to your applications, and says whether each is a rejection, a next
step or an automatic acknowledgement, quoting the sentence. It never changes an
application's stage by itself.

### How do I get rid of a job for good?

*Not interested* keeps it, marked discarded. **Delete** removes it and
everything attached (letters, answers, notes), and a later search will not
bring the same ad back. Tick several to delete them at once. Every deletion can
be undone from the message that appears, for a week.

### What is the difference between "discarded" and "rejected"?

*Discarded* means you passed on the job. *Rejected* means they passed on you.
They are separate tabs on purpose: merging them destroys your ability to see
your actual response rate, which is the one number that tells you whether your
CV is working.

### Can I run it for more than one person?

Not in one installation. Use a separate data directory per person:
`JOBRADAR_HOME=/data/alex jobradar search`.
