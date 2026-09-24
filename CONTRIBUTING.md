# Contributing

Thanks for considering it. The most useful contributions are the ones that make
JobRadar work for people whose job search does not look like the maintainers'.

## Especially wanted

- **Source adapters** for boards outside western Europe and North America.
  [docs/SOURCES.md](docs/SOURCES.md) has a complete worked example; it is one
  file and one registry line.
- **Taxonomy coverage** for under-served fields in
  `src/jobradar/resources/skills.yaml`. The shipped set leans technical.
  Healthcare, education, trades, law, logistics and the public sector would all
  benefit.
- **Salary bands and countries** in `resources/salary_bands.yaml` and
  `resources/countries.yaml`, from people who know that market.
- **CV templates** — regional conventions differ a great deal.
- **Linter rules**, with a reason a reader would actually care.
- **Translations** of the section labels in `documents/render.py`.

## Setting up

```bash
git clone https://github.com/inigo99/jobradar.git
cd jobradar
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev,all]"
playwright install chromium
pytest -q
ruff check src tests
```

The suite is fully offline: every source is faked, so it needs no network, no
keys and no fixtures downloaded at test time. Keep it that way — a test that
hits a real job board will be flaky within a week and will get someone's IP
rate-limited.

## House style

- Python 3.10+, `ruff` for lint and import order, 100-column lines.
- Type hints on anything public.
- Docstrings explain **why**, not what. The what is in the code.
- Comments earn their place by saying something the code cannot: a constraint, a
  trap, a decision that looks wrong until you know the reason.

## Things to be careful about

**The anti-fabrication lock.** `promoted_prominence()` in
`pipeline/scoring.py` and everything in `documents/validator.py` are the reason
this project can claim its output is defensible. Changing them needs a very good
argument and a test.

**Politeness to job boards.** All HTTP goes through `sources.base.Fetcher`,
which rate-limits, caches and honours `robots.txt` (restricted sources, which
the user switches on deliberately, skip that one check — see
[docs/SOURCES.md](docs/SOURCES.md)). Do not bypass it, and do not lower the
defaults.

**The dashboard.** `web/templates/dashboard.html` loads plain scripts from
`web/static/` in order; they share one global scope, one file per area
(board, mail, answers, jobs, insights, wizard, settings) and `dashboard-main.js`
last. No framework, no build step, nothing loaded from outside the machine.

**The mailbox.** `mail/imap.py` opens the folder read-only and fetches with
`BODY.PEEK`. Keep it that way: reading a user's email must never mark, move or
delete anything.

**The restricted tier.** New adapters that parse pages built for human visitors
must declare `tos_tier = "restricted"` and a `tos_note` naming the actual
concern. They must never be enabled by default.

**The user's data.** The pipeline must never write to the `applications` table,
and jobs must never be deleted — only marked closed. Both rules exist because
the alternative silently destroys the user's own tracking history.

## Pull requests

One change per PR, with a test where behaviour changed. In the description, say
what a user will notice and why the change is worth making. If it touches the
scoring, the validator or a filter, say what it does to a job that used to be
kept and is now dropped, or the reverse — that is the part reviewers care about.

## Reporting a bug

Include `jobradar doctor` output, what you expected, what happened, and — for
anything about filtering — `jobradar search --explain`. Please do not paste your
CV or personal details into an issue.
