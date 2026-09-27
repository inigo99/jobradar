"""Search for real with each sample graduate profile, region by region, and
write a report of what came back.

    python benchmarks/run.py                       # every profile, Navarra and Madrid
    python benchmarks/run.py --regions madrid --profiles abogacia enfermeria
    python benchmarks/run.py --sources linkedin infojobs indeed   # add restricted ones

Each profile searches its own titles (``profiles.yaml``) with "only in my
areas" on, on-site and hybrid, ads up to 30 days old. The sources are EURES
and the portals listed for the region below, plus any ``--sources`` you add.

This hits real job boards, politely and slowly (one request a second per
host, an hour of cache shared between profiles): it is not part of the test
suite, and results change from day to day. The report goes to
``benchmarks/reports/<date>-<regions>.md``, with the raw numbers in a
``.json`` next to it.
"""

from __future__ import annotations

import argparse
import json
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
from jobradar.storage import Database
from jobradar.textutils import title_matches

HERE = Path(__file__).resolve().parent
SNE = ("https://www.sistemanacionalempleo.es/OfertaDifusionWEB/busquedaOfertas.do"
       "?modo=continuar&palabraBusqueda={query}&botonNavegacion=Enviar")

#: Where to search, and which portals cover it (docs/PORTALS.md).
REGIONS: dict[str, dict] = {
    "navarra": {
        "area": "Pamplona",
        "portals": [
            ("Sistema Nacional de Empleo", SNE),
            ("Infoempleo Navarra", "https://www.infoempleo.com/trabajo/en_navarra/"),
            ("Servicio Navarro de Empleo",
             "https://administracionelectronica.navarra.es/EmpleoIntermediacion/listadodeofertas"),
        ],
    },
    "madrid": {
        "area": "Madrid",
        "portals": [
            ("Sistema Nacional de Empleo", SNE),
            ("Infoempleo Madrid", "https://www.infoempleo.com/trabajo/en_madrid/"),
        ],
    },
}


def settings_for(spec: dict, region: dict, extra_sources: list[str]) -> Settings:
    settings = Settings(onboarded=True, full_name="Benchmark", country="ES", default_language="es")
    settings.search.titles = list(spec["titles"])
    settings.search.languages = ["es"]
    filters = settings.filters
    filters.work_modes = [WorkMode.ONSITE, WorkMode.HYBRID]
    filters.local_areas = [region["area"]]
    filters.local_only = True
    filters.home_country = "ES"
    filters.max_age_days = 30
    settings.sources.enabled = ["eures", "portals", *extra_sources]
    settings.sources.portals = [Portal(name=name, url=url) for name, url in region["portals"]]
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
    by_title = [job for job in kept if title_matches(job.title, spec["titles"])]
    by_family = [job for job in kept if job.family == spec["family"]]
    scores = [result.scores[job.id].tailored for job in kept if job.id in result.scores]
    reasons = Counter(reason.split(" (")[0] for reason in result.rejected.values())
    return {
        "profile": key, "region": region_key, "seconds": round(seconds),
        "fetched": result.run.fetched, "kept": len(kept),
        "kept_by_source": {s: c.get("kept", 0) for s, c in result.run.by_source.items()},
        "fetched_by_source": {s: c.get("fetched", 0) for s, c in result.run.by_source.items()},
        "title_matches": len(by_title), "family_matches": len(by_family),
        "median_score": round(statistics.median(scores)) if scores else None,
        "rejected": dict(reasons.most_common(5)),
        "problems": result.run.fetch_problems[:3] + result.run.errors[:3],
        "jobs": [{"title": job.title, "company": job.company, "location": job.location,
                  "family": job.family, "source": job.source,
                  "score": round(result.scores[job.id].tailored) if job.id in result.scores else None,
                  "url": job.url}
                 for job in sorted(kept, key=lambda j: -(result.scores[j.id].tailored
                                                         if j.id in result.scores else 0))],
    }


def report(rows: list[dict], profiles: dict, regions: list[str]) -> str:
    lines = [f"# JobRadar with graduate profiles — {date.today():%d %B %Y}", "",
             f"Regions: {', '.join(regions)}. Only in the region's area, on-site or hybrid, "
             "ads up to 30 days old. Sources: EURES and the region's portals.", "",
             "**Kept** passed every filter. **By title** is how many of those have a title "
             "matching one the profile searched; **by family**, how many are in the profession's "
             "family. The gap between them and *kept* is noise.", ""]
    for region in regions:
        region_rows = [r for r in rows if r["region"] == region]
        lines += [f"## {region.title()}", "",
                  "| Profile | Fetched | Kept | By title | By family | Median score | Main reason dropped |",
                  "|---|---:|---:|---:|---:|---:|---|"]
        for r in region_rows:
            reason = next(iter(r["rejected"]), "—")
            lines.append(f"| {profiles[r['profile']]['label']} | {r['fetched']} | {r['kept']} | "
                         f"{r['title_matches']} | {r['family_matches']} | "
                         f"{r['median_score'] if r['median_score'] is not None else '—'} | {reason} |")
        empty = [profiles[r["profile"]]["label"] for r in region_rows if not r["kept"]]
        lines += ["", f"Nothing kept: {', '.join(empty) or 'none'}.", ""]
        for r in region_rows:
            if not r["jobs"]:
                continue
            lines.append(f"<details><summary>{profiles[r['profile']]['label']} — "
                         f"{r['kept']} kept</summary>\n")
            for job in r["jobs"][:10]:
                lines.append(f"- {job['score'] if job['score'] is not None else '—'}% · "
                             f"[{job['title']}]({job['url']}) · {job['location'] or '?'} · "
                             f"{job['family']} · {job['source']}")
            lines.append("\n</details>\n")
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    profiles = yaml.safe_load((HERE / "profiles.yaml").read_text(encoding="utf-8"))
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--regions", nargs="+", default=list(REGIONS), choices=list(REGIONS))
    parser.add_argument("--profiles", nargs="+", default=list(profiles), choices=list(profiles))
    parser.add_argument("--sources", nargs="*", default=[],
                        help="extra source ids, e.g. linkedin infojobs indeed")
    parser.add_argument("--out", type=Path, default=HERE / "reports")
    args = parser.parse_args(argv)

    args.out.mkdir(parents=True, exist_ok=True)
    cache = args.out / ".cache"
    cache.mkdir(exist_ok=True)
    rows = []
    for region in args.regions:
        for key in args.profiles:
            print(f"{region} · {key}…", file=sys.stderr, flush=True)
            row = run_one(key, profiles[key], region, args.sources, cache)
            print(f"  {row['kept']} kept of {row['fetched']} ({row['seconds']} s)",
                  file=sys.stderr, flush=True)
            rows.append(row)

    stem = args.out / f"{date.today():%Y-%m-%d}-{'-'.join(args.regions)}"
    stem.with_suffix(".json").write_text(json.dumps(rows, ensure_ascii=False, indent=1),
                                         encoding="utf-8")
    stem.with_suffix(".md").write_text(report(rows, profiles, args.regions), encoding="utf-8")
    print(f"Report: {stem.with_suffix('.md')}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
