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
**Settings → Your profile**. Spend ten minutes there once. Only you know that
you have written Terraform twice and would rather not be asked about it.

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

Findings are advice, not edits. JobRadar tells you what a reader will notice and
leaves the judgement to you, because it is your career and the linter has never
met your industry.

## Cover letters and emails

Generated on demand, per job, never in bulk. The letter is one or two
paragraphs, names your biggest gap openly in one clause rather than hiding it,
and anchors the interest in something real from the advertisement. The email
adds a subject line, a `[name]` placeholder, one concrete achievement, one
specific reason for this company, and — if the ad hid something material, like
an unnamed client or an unstated contracting country — a question about it.

Without a language model you get a skeleton built from your profile with the
parts that need a human marked in brackets. That is deliberately obvious about
what it is; it beats a blank page and it will not be sent by accident.
