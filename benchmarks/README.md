# Graduate profiles

Nineteen fictitious CVs of recent graduates — no job yet, at most an
internship — across professions JobRadar should serve as well as it serves a
software engineer: law, nursing, physiotherapy, dentistry and dental hygiene,
primary teaching, psychology, social work, business, marketing, journalism,
chemistry, industrial engineering, architecture, graphic design, and
vocational trades (laboratory technician, electrician, cook, administration).

`profiles.yaml` says, for each one, what the person would search for, which
skills the CV proves, which job family a typical ad belongs to, and gives such
an ad.

## Offline: the test suite

`tests/test_graduate_profiles.py` imports every CV and checks that it is read
whole (internships as positions, education, languages), that the skills of the
field are recognised, that a graduate is not red-flagged for being new, and
that a typical junior ad is sorted into the right family, scores well and
passes the filters. It runs with `pytest`, with no network.

When one of these fails after a change, the change has left a profession
behind. When a profession is added, add its CV here and its entry in
`profiles.yaml`.

## Live: `run.py`

```bash
python benchmarks/run.py                                  # every profile, Navarra and Madrid
python benchmarks/run.py --regions madrid --profiles abogacia enfermeria
python benchmarks/run.py --sources linkedin infojobs indeed   # on a machine where they run
```

Each profile searches its own titles, only in the region's area, on-site or
hybrid, ads up to 30 days old, on EURES and the region's portals
([docs/PORTALS.md](../docs/PORTALS.md)). The report
(`reports/<date>-<regions>.md`, raw numbers in a `.json` next to it) gives,
per profile, how many offers were fetched and kept, how many of those match
the profession by title and by family, the median score and the main reason
the rest were dropped.

It reads real job boards, slowly and politely, so it is not part of the test
suite and its numbers change from day to day. Run it after changing sources,
filters or the vocabulary, and compare with the last report.
