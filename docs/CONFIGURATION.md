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
cv_pdf_engine: auto      # auto: print the template with Chromium, the built-in
                         # writer when it is missing; builtin: always the latter
banned_phrases: []       # phrases you never use, flagged in letters and answers

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
  weekly: []                     # sources that run only once a week…
  weekly_day: 0                  # …on this day, 0 = Monday … 6 = Sunday
  company_domains:
    - stripe.com
    - greenhouse:airbnb
  request_delay: 1.0             # seconds between requests to one host
  max_results_per_source: 100
  timeout: 20.0
  respect_robots: true           # open and credentials sources; restricted ones skip it
  cache_ttl_minutes: 60
  scrapling_real_chrome: false    # true: the restricted sources use your
                                  # own installed Chrome instead of Scrapling's
                                  # bundled browser — faster, but only sensible
                                  # on a machine you use interactively

llm:
  provider: none                 # none | anthropic | openai | gemini | openai-compatible | ollama
  model: ""
  fallback_models: null          # models tried in order when `model` is busy,
                                 # retired or out of quota; null = the provider's
                                 # own list (gemini has one), [] = none
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

mail:                            # replies in your inbox; server in .env
  enabled: false
  days_back: 30                  # how far back the first check looks
  check_after_search: true

families:                        # only your changes to resources/families.yaml
  healthcare:
    priority: 1.4                # above 1 moves the family up the board
  software_it:
    enabled: false               # never classify anything as this family
  pet_care:                      # a family of your own
    label: Pet care
    keywords: [dog groomer, peluquero canino, pet sitter]
    bands: {junior: [18000, 22000], mid: [21000, 26000], senior: [25000, 31000], lead: [29000, 36000]}
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

## Job families

Every job is put in one family — 23 ship in `resources/families.yaml`, for
any kind of work, plus *General* for what fits none. The family comes from the
words in the title (worth three points) and the first lines of the ad (one
point); a keyword ending in `*` matches a prefix. It does three things:

- it groups the Insights funnel ("do my healthcare applications get replies?");
- it sets the starting band of a salary estimate;
- with a `priority` other than 1 it moves the family up or down the board.
  The match score never changes: a priority says what you would rather do, not
  how well you fit.

Under `families`, only what you change is stored, so a family you only
re-prioritised keeps getting keyword improvements from later versions. A key
the catalogue does not have is a family of your own and needs a `label` and
`keywords`. The CV can also be shaped per family: see
[CV_TAILORING.md](CV_TAILORING.md#a-cv-per-job-family).

## Salary estimates

An ad that publishes a salary is never second-guessed. For the rest, the
estimate is built in steps, each shown in the job's salary note:

1. the family's band for the seniority the title implies;
2. × the hiring country's multiplier — the country that employs you, which
   for a remote job abroad is not yours;
3. × the kind of employer: public sector, non-profit, staffing agency or
   consultancy, large company, startup, small business;
4. × at most two signals from the ad: many years asked for, few years asked
   for, a high level of English, an unnamed client, a regulated sector;
5. rounded to thousands, and converted to your currency.

A published band in another currency that falls below your floor only
because of the exchange rate — within 10 % of it — is kept with a note to
check today's rate, instead of being dropped on a rounding.

## Replies in your inbox

With `mail.enabled` and the `JOBRADAR_IMAP_*` variables set, **Check email**
(or `jobradar mail`, or the end of each search) reads the messages received
since the last check. The mailbox is opened read-only: nothing is marked as
read, moved or deleted. Each message is matched to an application by the
sender's domain, the company named in it and the job title; a match is
classified as a *rejection*, a *next step* or an *acknowledgement* (an
automatic "we received your application", which does not count as a reply),
with the sentence it was decided on quoted. A proposed interview date and
time becomes a calendar file to add by hand.

Nothing changes an application on its own: a rejection is offered as a
button, not applied. Replies about jobs not marked as applied are listed
apart, as they are usually applications made elsewhere.

## Language model

`llm.provider` (or `JOBRADAR_LLM_PROVIDER`, which wins) picks the provider;
`none` runs everything deterministically. Gemini's free tier allows only a few
dozen requests a day **per model**, and its newest models are often refused
with "high demand": busy answers are retried with a backoff, and a model that
is still busy, retired or out of its daily quota hands over to the next one in
`llm.fallback_models` / `JOBRADAR_LLM_FALLBACK_MODELS` (Gemini ships a default
list). When every model is spent the run carries on without one. For daily
searches that read dozens of ads, lower `max_calls_per_run` or use a paid key.

## Environment variables

Copy `.env.example` to `.env`. Nothing here is stored in the database or
included in an export.

| Variable | For |
|---|---|
| `JOBRADAR_HOME` | Where the data lives (default `./data`) |
| `JOBRADAR_ALLOWED_HOSTS` | Extra host names the dashboard answers to, comma-separated (see the README's privacy section) |
| `JOBRADAR_LLM_PROVIDER`, `JOBRADAR_LLM_MODEL`, `JOBRADAR_LLM_BASE_URL` | Language model; when set, they override the provider stored in Settings |
| `JOBRADAR_LLM_FALLBACK_MODELS` | Comma-separated models tried when the chosen one is busy, retired or out of quota (`none` to switch it off) |
| `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `GEMINI_API_KEY` (or `GOOGLE_API_KEY`) | Model keys |
| `JOBRADAR_CHROMIUM_PATH` | Chromium or Chrome used for the PDF when Playwright's own browser is missing |
| `ADZUNA_APP_ID`, `ADZUNA_APP_KEY` | Adzuna |
| `JOOBLE_API_KEY` | Jooble |
| `JOBRADAR_SMTP_*` | Email digest |
| `JOBRADAR_IMAP_HOST`, `JOBRADAR_IMAP_USER`, `JOBRADAR_IMAP_PASSWORD` | Reading replies (use an app password); `JOBRADAR_IMAP_PORT` (993) and `JOBRADAR_IMAP_FOLDER` (INBOX) are optional |
| `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` | Telegram digest |

## Editable data files

**`src/jobradar/resources/skills.yaml`** — the skill taxonomy: a key, a label,
a group and the aliases matched against ad text. It ships cross-industry, but
if your field is thin, add keys here; the scorer, the validator and the linter
all pick them up automatically. Write aliases with enough context to avoid
false positives — that is why the alias for Go is `golang`, not `go`. A skill
only you need is simpler to add in **Settings → Your skills**: it is stored
with your profile and read in ads from then on.

The `_learning_difficulty` block at the end of `skills.yaml` says how long each
gap would take to close — `fast`, `medium` or `slow` — and that is what the
coloured gap chips mean. It never decides *what* is a gap (your evidence does)
and never puts anything on a CV: a "fast" gap goes on the CV once you have
actually learnt it, not before.

**`src/jobradar/resources/families.yaml`** — the job families: label, title
keywords and a salary band per seniority. Override any of it in Settings.

**`src/jobradar/resources/salary_bands.yaml`** — how an estimate is adjusted:
seniority, per-country multipliers, the kind of employer, the signals in the
ad, and the currency-conversion margin. Used only when an ad publishes
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
not. Both are kept, but **Filtered out** lists only the first kind, in a table
of their own (what they ask, how far short you are, family, salary); the rest
are counted. The split is recomputed from today's settings every time, and
saving settings that now cover an ad's years puts it straight back on the
board.

**An ad that states no minimum is never filtered on years.** Most ads state
none, and treating silence as a rejection would throw away most of the board.

## What happens to rejected ads

They are stored, not dropped. **Filtered out** shows every one with its reason,
a tally by filter and by the exact wording, and a button to put one back;
`jobradar filtered` does the same from the terminal. Restoring an ad does not
change the filter that rejected it — that is a Settings change — it just makes
the decision yours and visible.
