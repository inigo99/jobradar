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
it from `resources/salary_bands.yaml`. Expand the job to see the reasoning. Edit
that file to match your market — the shipped numbers are a conservative
starting point, not data.

### My imported CV came out wrong.

Without a language model the parser is heuristic: it finds contact details,
sections, positions and bullets, and gets dates roughly right. Fix it in
**Settings → Your profile**, or re-import with a model configured, which is
markedly better. Either way, review before generating anything: everything
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
yourself, under your own jurisdiction. The same applies to the two Spanish
boards. Everything in the default set is a public API or feed meant to be read
programmatically.

### Does anything leave my machine?

Requests to the job boards you enabled, to the ECB for exchange rates, and to
your model provider if you configured one. Nothing else. The dashboard loads no
external assets and binds to `127.0.0.1`. Your CV and history stay in `data/`,
which is git-ignored.

### How do I search a specific company?

Add its domain under **Settings → Companies to watch**. JobRadar detects which
applicant tracking system it uses and reads that board's API directly — which is
both more reliable and more polite than scraping the careers page.

### It is not finding jobs in my field.

Two files to look at. `resources/skills.yaml` is the vocabulary used to read
requirements out of an ad; if your field's vocabulary is thin there, add keys.
`resources/salary_bands.yaml` needs a family for your field so estimates are
sensible. Both are plain YAML, and a pull request adding coverage for an
under-served field is very welcome.

### What is the difference between "discarded" and "rejected"?

*Discarded* means you passed on the job. *Rejected* means they passed on you.
They are separate tabs on purpose: merging them destroys your ability to see
your actual response rate, which is the one number that tells you whether your
CV is working.

### Can I run it for more than one person?

Not in one installation. Use a separate data directory per person:
`JOBRADAR_HOME=/data/alex jobradar search`.
