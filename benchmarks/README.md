# Graduate profiles

Nineteen fictitious CVs of recent graduates — no job yet, at most an
internship — across professions JobRadar should serve as well as it serves a
software engineer: law, nursing, physiotherapy, dentistry and dental hygiene,
primary teaching, psychology, social work, business, marketing, journalism,
chemistry, industrial engineering, architecture, graphic design, and
vocational trades (laboratory technician, electrician, cook, administration).

`profiles.yaml` says, for each one, what the person would search for (the
starter configuration from [docs/STARTER_CONFIGS.md](../docs/STARTER_CONFIGS.md)),
real ad titles those searches must find and lookalikes they must not, which
skills the CV proves, which job family a typical ad belongs to, and such an ad.

## Offline: the test suite

`tests/test_graduate_profiles.py` imports every CV and checks that it is read
whole (internships as positions, education, languages), that the skills of the
field are recognised, that a graduate is not red-flagged for being new, that
a typical junior ad is sorted into the right family, scores well and passes
the filters, that the titles find the real ads of the profession, and that
the starter guide still suggests the same titles and areas. It runs with `pytest`, with no network.

When one of these fails after a change, the change has left a profession
behind. When a profession is added, add its CV here and its entry in
`profiles.yaml`.

## Live: `run.py`

```bash
python benchmarks/run.py                                  # every profile, Navarra and Madrid
python benchmarks/run.py --regions europe usa             # wider: all of Europe, the United States
python benchmarks/run.py --regions madrid --profiles abogacia enfermeria
python benchmarks/run.py --sources linkedin infojobs indeed   # on a machine where they run
```

Each profile searches as [docs/STARTER_CONFIGS.md](../docs/STARTER_CONFIGS.md)
suggests, ads up to 30 days old:

| Region | Titles | Where | Sources |
|---|---|---|---|
| `navarra`, `madrid` | Spanish | only the region's area, the profession's work modes | EURES, Sistema Nacional de Empleo, Infoempleo's pages for the field in the province |
| `europe` | English | any of the countries EURES covers, any work mode | EURES, RemoteOK, We Work Remotely, Himalayas |
| `usa` | English | anywhere in the United States, any work mode | Adzuna, RemoteOK, We Work Remotely, Himalayas |

`usa` needs Adzuna's free keys in `ADZUNA_APP_ID` and `ADZUNA_APP_KEY`;
without them it is skipped with a message. The report
(`reports/<date>-<regions>.md`, raw numbers in a `.json` next to it; the
folder is git-ignored, reports are not committed) gives,
per profile, how many offers were fetched and kept, how many of those match
the profession by title and by family, the median score and the main reason
the rest were dropped.

It reads real job boards, slowly and politely, so it is not part of the test
suite and its numbers change from day to day. Run it after changing sources,
filters or the vocabulary, and compare with the last report. It still makes
hundreds of requests: **do not run it twice in a row** — two full runs back
to back got the Sistema Nacional de Empleo to refuse requests for a while.
The report lists any site that refused them.
