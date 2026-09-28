"""Search for real with each sample graduate profile, region by region, and
write a report of what came back.

    python benchmarks/run.py                       # every profile, Navarra and Madrid
    python benchmarks/run.py --regions europe usa  # wider: all of Europe, the United States
    python benchmarks/run.py --regions madrid --profiles abogacia enfermeria
    python benchmarks/run.py --sources linkedin infojobs indeed   # add restricted ones

Each profile searches as docs/STARTER_CONFIGS.md suggests (``profiles.yaml``
holds the same titles, areas and work modes), ads up to 30 days old.

* **Navarra, Madrid**: the Spanish titles, "only in my areas" on; EURES, the
  Sistema Nacional de Empleo and Infoempleo's pages for the profile's areas
  in the province.
* **Europe**: the English titles, on-site, hybrid or remote anywhere in the
  countries EURES covers, no area; EURES and the remote boards.
* **United States**: the English titles, anywhere in the country; Adzuna and
  the remote boards. Adzuna needs ``ADZUNA_APP_ID`` and ``ADZUNA_APP_KEY``
  (free keys); without them the region is skipped.

Plus any ``--sources`` you add.

This hits real job boards, politely and slowly (one request every two
seconds per host, at most 30 offers per source, an hour of cache shared
between profiles), and still makes hundreds of requests: do not run it twice
in a row. It is not part of the test
suite, and results change from day to day. The report goes to
``benchmarks/reports/<date>-<regions>.md``, with the raw numbers in a
``.json`` next to it.
"""

from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
import tempfile
import time
from collections import Counter
from datetime import date
from pathlib import Path

import yaml

from jobradar.config import Paths, Portal, Settings
from jobradar.models import WorkMode
from jobradar.pipeline.search import run_search
from jobradar.profile import import_profile
from jobradar.sources.eures import COVERED as EURES_COUNTRIES
from jobradar.storage import Database
from jobradar.textutils import title_matches

HERE = Path(__file__).resolve().parent
SNE = ("https://www.sistemanacionalempleo.es/OfertaDifusionWEB/busquedaOfertas.do"
       "?modo=continuar&palabraBusqueda={query}&botonNavegacion=Enviar")

INFOEMPLEO = "https://www.infoempleo.com/trabajo/area-de-empresa_{area}/en_{province}/"

#: Where to search: the town for "only in my areas" and the province as
#: Infoempleo writes it. Each profile reads the Sistema Nacional de Empleo and
#: the Infoempleo pages of its own areas there, as docs/STARTER_CONFIGS.md
#: suggests.
REGIONS: dict[str, dict] = {
    "navarra": {"area": "Pamplona", "infoempleo": "navarra"},
    "madrid": {"area": "Madrid", "infoempleo": "madrid"},
    # Wide regions: English titles, no area, the country list as the limit.
    "europe": {"countries": sorted(EURES_COUNTRIES), "home": "ES",
               "sources": ["eures", "remoteok", "weworkremotely", "himalayas"]},
    "usa": {"countries": ["US"], "home": "US", "needs": ["ADZUNA_APP_ID", "ADZUNA_APP_KEY"],
            "sources": ["adzuna", "remoteok", "weworkremotely", "himalayas"]},
}


LABELS = {"navarra": "Navarra", "madrid": "Madrid", "europe": "Europe", "usa": "United States"}


def is_wide(region: dict) -> bool:
    return "countries" in region


def titles_for(spec: dict, region: dict) -> list[str]:
    """English titles for the wide regions, Spanish ones for Spain's."""
    return list(spec["titles_en"] if is_wide(region) else spec["titles"])


def portals_for(spec: dict, region: dict) -> list[Portal]:
    portals = [Portal(name="Sistema Nacional de Empleo", url=SNE)]
    for area in spec.get("areas", []):
        url = INFOEMPLEO.format(area=area, province=region["infoempleo"])
        portals.append(Portal(name=f"Infoempleo {area} ({region['infoempleo']})", url=url))
    return portals


def settings_for(spec: dict, region: dict, extra_sources: list[str]) -> Settings:
    settings = Settings(onboarded=True, full_name="Benchmark", country="ES", default_language="es")
    settings.search.titles = titles_for(spec, region)
    filters = settings.filters
    filters.max_age_days = 30
    if is_wide(region):
        settings.search.languages = ["en"]
        filters.work_modes = [WorkMode.ONSITE, WorkMode.HYBRID, WorkMode.REMOTE]
        filters.home_country = region["home"]
        filters.eligible_countries = [c for c in region["countries"] if c != region["home"]]
        settings.sources.enabled = [*region["sources"], *extra_sources]
    else:
        settings.search.languages = ["es"]
        filters.work_modes = [WorkMode(mode) for mode in spec.get("work_modes", ["onsite", "hybrid"])]
        filters.local_areas = [region["area"]]
        filters.local_only = True
        filters.home_country = "ES"
        settings.sources.enabled = ["eures", "portals", *extra_sources]
        settings.sources.portals = portals_for(spec, region)
    # Gentler than the defaults: two full runs back to back got the Sistema
    # Nacional de Empleo to refuse this machine for a while.
    settings.sources.request_delay = 2.0
    settings.sources.max_results_per_source = 30
    settings.llm.provider = "none"
    return settings


def run_one(key: str, spec: dict, region_key: str, extra: list[str], cache: Path) -> dict:
    region = REGIONS[region_key]
    with tempfile.TemporaryDirectory(prefix=f"jr-{key}-") as home:
        paths = Paths(home=Path(home)).ensure()
        paths.cache_dir.rmdir()
        paths.cache_dir.symlink_to(cache, target_is_directory=True)  # shared politeness cache
        database = Database(paths)
        try:
            profile, _ = import_profile(HERE / "profiles" / f"{key}.txt")
            database.save_profile(profile)
            settings = settings_for(spec, region, extra)
            database.save_settings(settings)
            started = time.monotonic()
            result = run_search(settings=settings, paths=paths, database=database)
            seconds = time.monotonic() - started
        finally:
            database.close()

    kept = result.kept
    by_title = [job for job in kept if title_matches(job.title, titles_for(spec, region))]
    by_family = [job for job in kept if job.family == spec["family"]]
    def score(job):  # None for an ad JobRadar could not score (no skill it knows)
        found = result.scores.get(job.id)
        return round(found.tailored) if found and found.scored else None

    scores = [s for s in map(score, kept) if s is not None]
    reasons = Counter(reason.split(" (")[0] for reason in result.rejected.values())
    return {
        "profile": key, "region": region_key, "seconds": round(seconds),
        "fetched": result.run.fetched, "kept": len(kept),
        "kept_by_source": {s: c.get("kept", 0) for s, c in result.run.by_source.items()},
        "fetched_by_source": {s: c.get("fetched", 0) for s, c in result.run.by_source.items()},
        "title_matches": len(by_title), "family_matches": len(by_family),
        "median_score": round(statistics.median(scores)) if scores else None,
        "unscored": sum(1 for job in kept if score(job) is None),
        "rejected": dict(reasons.most_common(5)),
        "problems": result.run.fetch_problems[:3] + result.run.errors[:3],
        "jobs": [{"title": job.title, "company": job.company, "location": job.location,
                  "family": job.family, "source": job.source,
                  "score": score(job), "url": job.url}
                 for job in sorted(kept, key=lambda j: -(score(j) or -1))],
    }


def report(rows: list[dict], profiles: dict, regions: list[str]) -> str:
    lines = [f"# JobRadar with graduate profiles — {date.today():%d %B %Y}", "",
             f"Regions: {', '.join(regions)}. Ads up to 30 days old. Navarra and Madrid: Spanish "
             "titles, only in the region's area; EURES, the Sistema Nacional de Empleo and "
             "Infoempleo. Europe: English titles, any work mode, the EURES countries; EURES and "
             "the remote boards. United States: English titles; Adzuna and the remote boards.",
             "",
             "**Kept** passed every filter. **By title** is how many of those have a title "
             "matching one the profile searched; **by family**, how many are in the profession's "
             "family. The gap between them and *kept* is noise.", ""]
    for region in regions:
        region_rows = [r for r in rows if r["region"] == region]
        lines += [f"## {LABELS.get(region, region.title())}", "",
                  "| Profile | Fetched | Kept | By title | By family | Median score | Not scored "
                  "| Main reason dropped |",
                  "|---|---:|---:|---:|---:|---:|---:|---|"]
        for r in region_rows:
            reason = next(iter(r["rejected"]), "—")
            lines.append(f"| {profiles[r['profile']]['label']} | {r['fetched']} | {r['kept']} | "
                         f"{r['title_matches']} | {r['family_matches']} | "
                         f"{r['median_score'] if r['median_score'] is not None else '—'} | "
                         f"{r['unscored']} | {reason} |")
        empty = [profiles[r["profile"]]["label"] for r in region_rows if not r["kept"]]
        lines += ["", f"Nothing kept: {', '.join(empty) or 'none'}.", ""]
        refused = sorted({p for r in region_rows for p in r["problems"] if "access-denied" in p})
        if refused:
            lines += ["**Sites that refused requests or failed during the run** (their offers are "
                      "missing, the numbers above are low):", "",
                      *[f"- {p}" for p in refused], ""]
        for r in region_rows:
            if not r["jobs"]:
                continue
            lines.append(f"<details><summary>{profiles[r['profile']]['label']} — "
                         f"{r['kept']} kept</summary>\n")
            for job in r["jobs"][:10]:
                shown = f"{job['score']}%" if job["score"] is not None else "—"
                lines.append(f"- {shown} · "
                             f"[{job['title']}]({job['url']}) · {job['location'] or '?'} · "
                             f"{job['family']} · {job['source']}")
            lines.append("\n</details>\n")
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    profiles = yaml.safe_load((HERE / "profiles.yaml").read_text(encoding="utf-8"))
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--regions", nargs="+", default=["navarra", "madrid"],
                        choices=list(REGIONS))
    parser.add_argument("--profiles", nargs="+", default=list(profiles), choices=list(profiles))
    parser.add_argument("--sources", nargs="*", default=[],
                        help="extra source ids, e.g. linkedin infojobs indeed")
    parser.add_argument("--out", type=Path, default=HERE / "reports")
    args = parser.parse_args(argv)

    args.out.mkdir(parents=True, exist_ok=True)
    cache = args.out / ".cache"
    cache.mkdir(exist_ok=True)
    rows = []
    regions = []
    for region in args.regions:
        missing = [name for name in REGIONS[region].get("needs", []) if not os.environ.get(name)]
        if missing:
            print(f"Skipping {region}: set {', '.join(missing)} to search it.", file=sys.stderr)
            continue
        regions.append(region)
        for key in args.profiles:
            print(f"{region} · {key}…", file=sys.stderr, flush=True)
            row = run_one(key, profiles[key], region, args.sources, cache)
            print(f"  {row['kept']} kept of {row['fetched']} ({row['seconds']} s)",
                  file=sys.stderr, flush=True)
            rows.append(row)

    if not regions:
        return 1
    stem = args.out / f"{date.today():%Y-%m-%d}-{'-'.join(regions)}"
    stem.with_suffix(".json").write_text(json.dumps(rows, ensure_ascii=False, indent=1),
                                         encoding="utf-8")
    stem.with_suffix(".md").write_text(report(rows, profiles, regions), encoding="utf-8")
    print(f"Report: {stem.with_suffix('.md')}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
