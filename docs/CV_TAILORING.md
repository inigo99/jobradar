# Tailoring, honestly

This is the part of JobRadar worth reading before you use it, because it is the
part where the tempting shortcut is the one that costs you the job.

## The failure this is built to avoid

The obvious way to build a CV tool is to compare the ad against the CV and add
whatever is missing. It scores brilliantly. Then the interview happens, someone
asks a second question about Kubernetes, and the answer runs out after one
sentence. That is not a lost opportunity; it is a lost reference, because
everyone in the room now knows the CV was written by something that does not
care whether it is true.

So JobRadar's rule is that tailoring may only change **which true things are
prominent**, never what is true.

## Evidence and ceilings

Each skill carries two numbers.

**Evidence** — how strongly your CV proves it as it stands:

| Value | Means |
|---|---|
| `1.0` | Argued for inside an achievement, with a result attached |
| `0.5` | Listed in a skills section and nowhere else |
| `0.0` | You do not have it |

**Ceiling** — how far a tailored CV may push it. Not "how much do you want this
job", but: *could you hold twenty minutes of questioning on it?*

A tailored CV moves a relevant skill from its evidence to its ceiling by pulling
it into a bullet or the summary. And:

> **A skill with evidence `0.0` has no ceiling. It never rises.**

That is four lines of code in `pipeline/scoring.py` and it is the whole of the
lock. It means the difference between your base score and your tailored score
is always the value of better presentation, and never the value of a lie.

Both numbers are proposed when your CV is imported — demonstrated skills get
`1.0`, listed ones `0.5` with a ceiling of `0.9` — and are editable in
**Settings → Your skills**. Spend ten minutes there once. Only you know that
you have written Terraform twice and would rather not be asked about it.

The same place lets you add, edit and delete skills and the groups your CV
lists them in:

- a skill JobRadar knows (by any of its names) is linked to it; one it does
  not know becomes one of yours, with other names it goes by in ads, and is
  read in ads from then on;
- a skill typed into a group is added with the evidence of a listed skill;
- a skill you delete, or set to evidence `0`, stays deleted — it is not read
  back from your CV's text, not even when you import a new CV. Your own
  skills, tuned ceilings and CVs per job family survive a new import too.

## What actually changes per job

| Changes | Never changes |
|---|---|
| The headline under your name | The achievements themselves |
| The professional summary | The positions and their dates |
| The order of achievements *within* a position | The order of the positions |
| The order of the skill groups | Which achievement belongs to which job |
| The language (it follows the ad) | Your education, certifications, contact details |

Reordering positions to lead with the most relevant employer is one of the
fastest things for a recruiter to notice, and rewriting an achievement per job
is how people end up unable to answer a question about their own CV. Neither
happens here.

The headline is also checked: if the ad says "Principal Engineer" and your dates
add up to three years, the word "Principal" is removed. Claiming seniority you
do not have is not tailoring — it is the first thing that gets a CV binned.

A skills block also gets a short "Also" line naming up to four skills the ad
asks for, that your profile proves, and that the groups shown would otherwise
leave out — typically one proven only inside an achievement.

## A CV per job family

Someone applying to warehouse jobs and to delivery-driver jobs wants two
different CVs, not one CV re-sorted per ad. **Settings → CV per job family**
sets, for each family:

- a fixed **headline** ("Warehouse team lead") instead of the ad's own title;
- which **achievements lead** their position and which are **left out**;
- which **skill groups** come first and which are left out;
- up to four **extra skills** to name under "Also".

A variant only selects and orders what the profile already holds. It cannot
add anything: an extra skill your profile does not prove is not printed. The
variant is your explicit choice, so it wins over the automatic ranking and
over a model's proposed order.

## The PDF

With Playwright and a Chromium installed, the HTML template is printed as it
looks in the browser, shrinking the type step by step until it fits
`cv_max_pages`. Without them — or when printing fails, or with `cv_pdf_engine:
builtin` — a built-in writer lays the same content out in Helvetica, with the
same shrink-to-fit, and needs nothing installed. It is plainer, and just as
readable by an applicant tracking system: one column of real text.

## The XYZ formula

Achievements should read *accomplished **X**, as measured by **Y**, by doing
**Z***:

> Cut production-reported errors in a critical ERP module by **nearly 50%** by
> implementing a unit and integration testing framework with structured
> debugging workflows.

X is the outcome, Y is the number, Z is what you actually did. Compare:

> Responsible for testing and quality in the ERP module.

Same work. The first tells a reader what changed because you were there; the
second tells them what your job description said. `jobradar lint` flags the
second shape (`duty-language`) and tells you when fewer than half of your
achievements carry a number (`few-metrics`).

If you do not have exact figures, an estimate you can defend is fine —
"roughly a third", "around 40 hours a month". An estimate you can explain beats
a precise number you invented, and beats no number at all by a wide margin.

## Verification

Every generated document is compared against your profile before it is
rendered:

| Check | Severity | Catches |
|---|---|---|
| `invented-skill` | error | A technology the profile has no evidence for |
| `invented-figure` | error | A number that appears nowhere in the profile |
| `inflated-seniority` | error | More years claimed than your dates support |
| `unknown-organisation` | warning | A company not in your profile (fine in a letter addressed to them) |

Failing drafts are discarded and the deterministic version is used instead; the
dashboard shows you what was rejected. This runs whether or not a language model
was involved, because the check is on the output, not on who wrote it.

Cover letters relax the number check only — they legitimately quote figures from
the advertisement — and the invented-skill check still applies.

## The ten-second scan

A senior recruiter's first pass is not reading, it is scanning for reasons to
stop. `jobradar lint` reports what that pass will find: length over one page,
unexplained gaps, missing dates, positions out of order, achievements without
results, duty language, empty phrases ("results-driven", "team player"), keyword
stuffing, acronym soup, and a summary with nothing concrete in it.

The full rule list:

| Rule | Severity | What it catches |
|---|---|---|
| `too-long` | error | More than one page |
| `missing-name`, `missing-email` | error | No way to contact you |
| `missing-dates` | error | An undated position |
| `chronology` | error | Positions not in reverse-chronological order |
| `no-achievements` | error | A CV of job titles with nothing under them |
| `impossible-ceiling` | error / warning | A ceiling on a skill with no evidence, or below its evidence |
| `position-without-achievements` | warning | One position with nothing under it |
| `unproven-evidence` | warning | A skill marked as demonstrated that no achievement shows |
| `employment-gap` | warning | An unexplained gap over five months |
| `few-metrics` | warning | Fewer than half the achievements carry a number |
| `duty-language` | warning | "Responsible for…", "Worked on…" |
| `long-bullet` | warning | An achievement over 300 characters |
| `empty-phrase` | warning | "Results-driven", "team player", "detail-oriented" |
| `skill-stuffing` | warning | More than 40 listed skills |
| `acronym-soup` | warning | A summary that is mostly acronyms |
| `no-summary`, `long-summary` | warning | No summary, or one nobody will read |
| `thin-contact` | warning | Email only, no phone or LinkedIn |
| `too-many-bullets` | info | More than six achievements in one role |
| `mixed-tense` | info | "-ing" and past-tense openings in the same role |
| `first-person` | info | Bullets starting with "I" |
| `orphan-skills` | info | Many skills listed but never demonstrated |
| `repeated-keyword` | info | The same term repeated for ATS ranking that does not work |
| `summary-without-evidence` | info | A summary with no concrete figure |
| `unknown-listed-skills` | info | Listed skills that matching does not know, so they never count |

Rules that would encode a cultural preference are deliberately absent. Whether
a CV should carry a photo or a date of birth varies enormously by country, and
a linter that flags a German CV for following German convention is worse than
no linter.

Findings are advice, not edits. JobRadar tells you what a reader will notice and
leaves the judgement to you, because it is your career and the linter has never
met your industry.

## Cover letters and emails

Generated on demand, per job, never in bulk. Once written they are yours: edit
them in place, save, copy, or download them as a PDF (built without a
browser). Opening one again shows your saved text; writing it again asks
first. The letter is one or two
paragraphs, names your biggest gap openly in one clause rather than hiding it,
and anchors the interest in something real from the advertisement. The email
adds a subject line, a `[name]` placeholder, one concrete achievement, one
specific reason for this company, and — if the ad hid something material, like
an unnamed client or an unstated contracting country — a question about it.

Without a language model you get a skeleton built from your profile with the
parts that need a human marked in brackets. That is deliberately obvious about
what it is; it beats a blank page and it will not be sent by accident.

### Warnings on what you send

Letters, emails and form answers are yours to edit, so nothing blocks them.
Instead every save, and every time a saved text is shown, lists what might
hurt:

| Warning | Catches |
|---|---|
| `unsupported-figure` | A number that is neither in your profile nor in the ad (the ad's own figures, its published salary and this year are fine) |
| `inflated-seniority` | More years claimed than your dates support — unless the sentence is about what the ad asks for |
| `unsupported-skill` | A skill claimed that your profile has no evidence for; naming it as a gap is fine |
| `boilerplate` | Template phrases ("to whom it may concern", "team player"), plus any in **Settings → Phrases you never use** |
| `company-not-named` | A letter or email that would fit any company |
| `no-subject`, `no-greeting-name` | An email without a `Subject:` line or a `[name]` placeholder |
| `still-to-fill` | Parts in brackets not yet written |
| `over-limit` | A form answer longer than the form accepts |

## Application-form questions

Most applications ask three or four free-text questions — why us, a project
you are proud of, expected salary. **Form answers** on a job opens a thread for
them:

- paste the question as the form asks it; the answer is drawn from your
  profile and the ad, in the ad's language, without greeting or sign-off;
- set the form's limit (characters or words): the answer is asked to respect
  it and, if it still runs over, is shortened once more; the counter turns red
  when it is over;
- say what to change in the same thread ("shorter", "less formal", "in
  English") instead of starting again;
- a figure or date your profile does not have (expected salary, availability,
  start date) comes back as `[pending: …]` for you to fill in, never invented;
- edit any answer by hand.

**The answer bank.** Save an answer you like and it is kept with its question.
When another job asks something similar — measured by the words the two
questions share, ignoring the ones every question has ("why", "your",
"describe") — your saved answer is given to the model as a precedent to
adapt, never to copy, and the thread says which one it started from. Without a
model, the saved answer itself is offered as the starting point. Saved answers
can be edited or deleted from the bank.
