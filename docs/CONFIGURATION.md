# Configuration reference

Settings live in `data/jobradar.sqlite3` and are edited from the dashboard
(**Settings**) or with `jobradar init`. For unattended installs, write them as
YAML and load them once:

```bash
jobradar init --config settings.yaml --cv ~/Documents/cv.pdf
```

## A complete settings.yaml

```yaml
onboarded: true
full_name: Alex Morgan
email: alex.morgan@example.com
country: ES              # ISO-3166 alpha-2; picks currency and default sources
default_language: en     # used when the ad's language cannot be determined
cv_template: classic     # classic | compact | modern
cv_max_pages: 1

search:
  titles:                # sent verbatim to every source as a query
    - Machine Learning Engineer
    - Backend Engineer
  keywords:              # extra terms ORed into the queries
    - Python
  languages: [en, es]

filters:
  work_modes: [remote]           # remote | hybrid | onsite
  local_areas: [Valencia]        # hybrid/on-site accepted here regardless
  home_country: ES
  eligible_countries: []         # extra countries you may be employed in
  allow_international_remote: true
  min_salary: 35000
  salary_currency: EUR
  require_published_salary: false
  max_years_experience:          # empty: take the ceiling from your CV's dates
  use_profile_years: true        # …which is what this does, and it rises on its own
  years_margin: 1.0              # years past yours that still count as "just short"
  required_keywords: []
  excluded_keywords: [unpaid, commission only]   # whole words; end with * for a prefix
  excluded_companies: []
  max_age_days: 7
  keep_undated: true

weekly_goal: 10                  # applications a week; drives the Today queue
today_queue_size: 6              # how many jobs that queue shows at once
prune_after_days: 45             # close untouched jobs older than this; empty = off

sources:
  enabled: []                    # empty == every non-restricted source
  disabled: []
  company_domains:
    - stripe.com
    - greenhouse:airbnb
  request_delay: 1.0             # seconds between requests to one host
  max_results_per_source: 100
  timeout: 20.0
  respect_robots: true
  cache_ttl_minutes: 60
  scrapling_real_chrome: false    # true: LinkedIn/InfoJobs/Tecnoempleo use your
                                  # own installed Chrome instead of Scrapling's
                                  # bundled browser — faster, but only sensible
                                  # on a machine you use interactively

llm:
  provider: none                 # none | anthropic | openai | openai-compatible | ollama
  model: ""
  base_url: ""
  max_calls_per_run: 60
  temperature: 0.2
  enrich_jobs: true
  tailor_cv: true
  write_letters: true

notifications:
  email_enabled: false
  telegram_enabled: false
  min_score: 55                  # only notify about jobs scoring this well
```

## The filters in detail

**`work_modes` and `local_areas` together.** The most common real preference is
"fully remote anywhere, but I would also take an office job in my own city".
That is `work_modes: [remote]` plus `local_areas: [Valencia]`. A hybrid or
on-site job whose location matches one of your areas is kept even though the
mode is not in your list.

**Geography.** For on-site and hybrid roles the office must be in one of your
areas or in an eligible country. For remote roles the question is what the ad's
restriction allows:

| The ad's remote scope | Kept? |
|---|---|
| worldwide | yes |
| region (EMEA, EU, …) | yes if your country falls inside it |
| country, and the ad names it | yes only if that country is one of yours |
| country, but the ad names none ("must be eligible to work in the country") | yes, with an alert quoting the sentence |
| unknown | yes, with an alert telling you to confirm |

The countries are read out of the ad's own residency sentence ("must reside in
Spain", "eligible to work in the EU"), and they win over the board's metadata.
The same sentence can restrict or open up, so when it names no place the job is
kept rather than dropped on a guess.

**Work mode.** Decided from the ad's own words, with negations understood ("not
a remote position") and office days counted wherever they are mentioned ("work
from home 2 days per week" is hybrid). When the text says nothing, the board's
tag is kept and flagged — silence is not a contradiction. The sentences the
decision came from are stored with the job.

That last row matters. A "remote" job in London usually means remote *within
the UK*, and ads very often do not say. Dropping them would lose real
opportunities; keeping them silently would waste your time. So they are kept
and flagged, and the generated application email asks the question.

**Salary.** Only a salary the ad publishes can drop a job, and a published band
is judged by its top after conversion at ECB reference rates: a 36–45k band may
well pay 40k, and rejecting it for its lower end punishes the ads that are
transparent. An *estimate* below your floor is kept with a warning — it comes
from a reference band, not from the ad. A job with no salary at all is kept too,
unless `require_published_salary` is on. Around two thirds of ads publish
nothing, so a floor that dropped them would drop most of the market.

**Keyword and company lists.** Matched as whole words, never as substrings:
`java` does not exclude "JavaScript", and `Alan` does not exclude "Talan". End
an entry with `*` to match a prefix (`practic*` matches "prácticas" and
"practicante"). `local_areas` follow the same rule and are read from the job's
location only.

**Old jobs.** `prune_after_days` closes jobs published longer ago than that
which you have not touched (applied, discarded, annotated), before each search
and without fetching anything. They stay readable as closed, and a repost of
one under a new id is recognised as a duplicate rather than shown as new.

**Freshness.** `keep_undated: true` matters more than it looks: most aggregators
omit the publication date entirely, and a strict reading would discard them all.

## Environment variables

Copy `.env.example` to `.env`. Nothing here is stored in the database or
included in an export.

| Variable | For |
|---|---|
| `JOBRADAR_HOME` | Where the data lives (default `./data`) |
| `JOBRADAR_ALLOWED_HOSTS` | Extra host names the dashboard answers to, comma-separated (see the README's privacy section) |
| `JOBRADAR_LLM_PROVIDER`, `JOBRADAR_LLM_MODEL`, `JOBRADAR_LLM_BASE_URL` | Language model |
| `ANTHROPIC_API_KEY`, `OPENAI_API_KEY` | Model keys |
| `ADZUNA_APP_ID`, `ADZUNA_APP_KEY` | Adzuna |
| `JOOBLE_API_KEY` | Jooble |
| `JOBRADAR_SMTP_*` | Email digest |
| `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` | Telegram digest |

## Editable data files

**`src/jobradar/resources/skills.yaml`** — the skill taxonomy: a key, a label,
a group and the aliases matched against ad text. It ships cross-industry, but
if your field is thin, add keys here; the scorer, the validator and the linter
all pick them up automatically. Write aliases with enough context to avoid
false positives — that is why the alias for Go is `golang`, not `go`.

**`src/jobradar/resources/salary_bands.yaml`** — reference bands by role family
and seniority, plus a per-country multiplier. Used only when an ad publishes
nothing, always labelled as an estimate. The shipped numbers are conservative
and are meant to be replaced with what you know about your market.

**`src/jobradar/resources/countries.yaml`** — currency, common ad languages,
the Adzuna country code and which national sources are relevant. Adding a
country is an entry here and nothing else.

## Years of experience

Three settings, and the order matters.

`max_years_experience` is a hard ceiling you type yourself. It wins whenever it
is set, because a number somebody typed was meant. Its problem is that nobody
remembers to raise it, so a year later it is quietly rejecting jobs you could
now do.

`use_profile_years` (on by default) takes the ceiling from the dates in your own
profile instead. It goes up on its own as time passes, which is the only version
of this number that stays true without maintenance.

`years_margin` splits the rejections in two. An ad asking for one year more than
you have is worth a direct email naming the gap; an ad asking for six more is
not. Both are kept under **Filtered out** either way, labelled differently.

**An ad that states no minimum is never filtered on years.** Most ads state
none, and treating silence as a rejection would throw away most of the board.

## What happens to rejected ads

They are stored, not dropped. **Filtered out** shows every one with its reason,
a tally by filter and by the exact wording, and a button to put one back;
`jobradar filtered` does the same from the terminal. Restoring an ad does not
change the filter that rejected it — that is a Settings change — it just makes
the decision yours and visible.
