"""The command line.

Everything the dashboard can do is available here, because the interesting
runs are unattended ones: a nightly ``jobradar search`` on a laptop or a small
server, followed by a digest. The dashboard is for the parts that need a human
— setup, triage and reading.

Commands:

``init``     create the configuration, interactively or from a YAML file
``demo``     load a synthetic profile and jobs so you can look around
``search``   run the full pipeline and store what it finds
``sweep``    check active jobs and retire the ads that have closed
``tailor``   generate the tailored CV for one job, or for the best N
``lint``     run the recruiter red-flag check over your profile
``jobs``     list what is in the pipeline
``export``   write the pipeline to CSV or Excel
``notify``   send the digest of new jobs
``sources``  show every source and whether it is enabled
``serve``    start the local dashboard
``doctor``   check the installation and the configuration
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from pathlib import Path

from . import __version__
from .config import Paths, Settings, countries, load_dotenv
from .documents import render_cv, tailor
from .errors import JobRadarError, NotFoundError, SetupRequiredError
from .exporters import export_csv, export_excel
from .lint import lint_profile, lint_tailored
from .llm import build_client
from .models import ApplicationStatus, WorkMode
from .pipeline import run_search, sweep_closed
from .pipeline.filters import explain
from .pipeline.focus import focus_for
from .pipeline.scoring import score_job
from .profile import import_profile
from .sources import available as available_sources
from .storage import Database

# ---------------------------------------------------------------------------
# Output helpers — rich when it is installed, plain text when it is not.
# ---------------------------------------------------------------------------

try:
    from rich.console import Console
    from rich.table import Table
    from rich.text import Text

    console = Console()

    def out(message: str = "") -> None:
        console.print(message)

    def table(title: str, columns: list[str], rows: list[list[str]]) -> None:
        grid = Table(title=title, header_style="bold")
        for column in columns:
            grid.add_column(column, overflow="fold")
        for row in rows:
            # Cells are data, not markup: rendering them as Text stops rich
            # from eating things like "jobradar[pdf]" as a style tag.
            grid.add_row(*[Text(str(cell)) for cell in row])
        console.print(grid)

except ImportError:  # pragma: no cover - cosmetic fallback
    def out(message: str = "") -> None:
        print(_strip_markup(str(message)))

    def table(title: str, columns: list[str], rows: list[list[str]]) -> None:
        print(f"\n{title}")
        print(" | ".join(columns))
        for row in rows:
            print(" | ".join(str(cell) for cell in row))

    def _strip_markup(text: str) -> str:
        import re

        return re.sub(r"\[/?[a-z0-9 #]+\]", "", str(text or ""))


def _database(args: argparse.Namespace) -> Database:
    return Database(Paths.resolve(getattr(args, "home", None)))


def _require_onboarded(settings: Settings) -> None:
    if not settings.onboarded:
        raise SetupRequiredError(
            "Not set up yet.",
            hint="Run 'jobradar init', or 'jobradar demo' to look around with synthetic data.",
        )


def _positive_int(text: str) -> int:
    """argparse type: a whole number of at least 1."""
    try:
        value = int(text)
    except ValueError:
        raise argparse.ArgumentTypeError(f"'{text}' is not a whole number") from None
    if value < 1:
        raise argparse.ArgumentTypeError(f"must be at least 1, not {value}")
    return value


def _port(text: str) -> int:
    """argparse type: a TCP port number."""
    value = _positive_int(text)
    if value > 65535:
        raise argparse.ArgumentTypeError(f"{value} is not a valid port (1-65535)")
    return value


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------


def cmd_init(args: argparse.Namespace) -> int:
    """Create the configuration and import the CV."""
    database = _database(args)
    if args.config:
        settings = Settings.from_yaml(args.config)
        settings.onboarded = True
        database.save_settings(settings)
        out(f"Settings loaded from [bold]{args.config}[/bold].")
    else:
        settings = database.load_settings()
        out("[bold]JobRadar setup[/bold] — press Enter to accept the value in brackets.\n")
        settings.full_name = _ask("Your full name", settings.full_name)
        settings.email = _ask("Your email", settings.email)
        settings.country = _ask("Country you work from (ISO code)", settings.country).upper()
        if settings.country not in countries():
            out(f"[yellow]'{settings.country}' is not in the country registry; "
                "salary estimates will use the neutral default.[/yellow]")
        settings.filters.home_country = settings.country
        settings.filters.salary_currency = _ask(
            "Currency for the salary filter", countries().get(settings.country, {}).get("currency", "EUR")
        ).upper()
        titles = _ask("Job titles to search for (comma separated)", ", ".join(settings.search.titles))
        settings.search.titles = [t.strip() for t in titles.split(",") if t.strip()]
        modes = _ask("Acceptable ways of working (remote,hybrid,onsite)",
                     ",".join(m.value for m in settings.filters.work_modes))
        wanted = [m.strip().lower() for m in modes.split(",") if m.strip()]
        unknown = [m for m in wanted if m not in WorkMode._value2member_map_]
        if unknown:
            out(f"[yellow]Ignoring unknown work mode(s): {', '.join(unknown)} "
                "(use remote, hybrid or onsite).[/yellow]")
        chosen = [WorkMode(m) for m in wanted if m in WorkMode._value2member_map_]
        if chosen:
            settings.filters.work_modes = chosen
        else:
            out("[yellow]No valid work mode given; keeping the current ones.[/yellow]")
        areas = _ask("Areas where hybrid/on-site is fine (comma separated, optional)",
                     ", ".join(settings.filters.local_areas))
        settings.filters.local_areas = [a.strip() for a in areas.split(",") if a.strip()]
        minimum = _ask("Minimum yearly salary (blank for none)",
                       str(settings.filters.min_salary or ""))
        cleaned = minimum.strip().replace(".", "").replace(",", "").replace(" ", "")
        if cleaned and not cleaned.isdigit():
            out(f"[yellow]'{minimum}' is not a whole number; no minimum salary set.[/yellow]")
        settings.filters.min_salary = int(cleaned) if cleaned.isdigit() else None
        settings.onboarded = True
        database.save_settings(settings)

    if args.cv:
        llm = build_client(settings.llm)
        try:
            profile, notes = import_profile(Path(args.cv), llm)
        finally:
            if llm:
                llm.close()
        database.save_profile(profile)
        out(f"\nProfile imported: [bold]{profile.contact.full_name or 'unnamed'}[/bold], "
            f"{len(profile.all_bullets())} achievements, {profile.years_of_experience():g} years.")
        for note in notes:
            out(f"  [yellow]•[/yellow] {note}")
    elif database.load_profile() is None:
        out("\n[yellow]No CV imported yet.[/yellow] Add one with "
            "[bold]jobradar init --cv path/to/cv.pdf[/bold], or from the dashboard.")

    out("\nDone. Next: [bold]jobradar search[/bold] or [bold]jobradar serve[/bold].")
    database.close()
    return 0


def _ask(prompt: str, default: str = "") -> str:
    answer = input(f"{prompt} [{default}]: ").strip()
    return answer or default


def cmd_demo(args: argparse.Namespace) -> int:
    """Load the synthetic dataset."""
    from .demo import load_demo

    database = _database(args)
    count, _settings = load_demo(database, database.paths)
    out(f"Loaded a demo profile and [bold]{count}[/bold] synthetic jobs. "
        "Try [bold]jobradar jobs[/bold] or [bold]jobradar serve[/bold].")
    database.close()
    return 0


def cmd_search(args: argparse.Namespace) -> int:
    """Run the pipeline."""
    database = _database(args)
    settings = database.load_settings()
    _require_onboarded(settings)
    if args.no_llm:
        settings.llm.switched_off = True

    out("Searching…")
    result = run_search(settings=settings, paths=database.paths, database=database,
                        enrich=not args.no_enrich, refresh=args.refresh)
    run = result.run
    out(f"\n[bold]{run.kept}[/bold] jobs kept — {run.new} new — "
        f"{run.fetched} fetched from {len(run.sources)} sources "
        f"({run.after_dedupe} after deduplication).")
    out(f"  {run.reused} already on file (not re-read) · "
        f"{run.known_duplicates} reposts or duplicates of a job on file · "
        f"{run.pruned} old untouched jobs retired.")
    for source_id, counts in sorted(run.by_source.items()):
        out(f"  {source_id}: {counts.get('fetched', 0)} fetched, {counts.get('kept', 0)} kept")
    for error in run.errors:
        out(f"  [red]![/red] {error}")

    if result.new_jobs:
        table(
            "New jobs",
            ["Score", "Company", "Title", "Where", "Salary"],
            [
                [
                    f"{result.scores[job.id].tailored:.0f}%" if job.id in result.scores else "—",
                    (job.company or "")[:26],
                    (job.title or "")[:44],
                    (job.location or "")[:24],
                    f"{salary.minimum:,}–{salary.maximum or salary.minimum:,} {salary.currency}"
                    if (salary := getattr(job, "salary", None)) and salary.minimum else "—",
                ]
                for job in sorted(
                    result.new_jobs,
                    key=lambda j: -(result.scores[j.id].tailored if j.id in result.scores else 0),
                )[:30]
            ],
        )

    if args.explain and result.rejected:
        table("Why jobs were dropped", ["Reason", "Count"],
              [[reason, str(count)] for reason, count in explain(result.rejected)])
        out("Nothing was thrown away: see them with [bold]jobradar filtered[/bold].")

    if args.notify:
        from .notify import send_digest

        sent = send_digest(result.new_jobs, result.scores, settings.notifications)
        for channel, ok in sent.items():
            out(f"Digest via {channel}: {'sent' if ok else 'failed'}")

    database.close()
    return 0


def cmd_sweep(args: argparse.Namespace) -> int:
    """Retire ads that have closed."""
    database = _database(args)
    report = sweep_closed(database, limit=args.limit)
    out(f"Sweep: {report.summary()}")
    for _job_id, description, reason in report.closed:
        out(f"  [yellow]closed[/yellow] {description} — {reason}")
    database.close()
    return 0


def cmd_tailor(args: argparse.Namespace) -> int:
    """Generate the tailored CV for one job or for the best N."""
    database = _database(args)
    settings = database.load_settings()
    _require_onboarded(settings)
    profile = database.load_profile()
    if profile is None:
        raise SetupRequiredError("No profile yet.",
                                 hint="Import a CV first: jobradar init --cv path/to/cv.pdf")
    if args.no_llm:
        settings.llm.switched_off = True

    if args.job_id:
        job = database.get_job(args.job_id)
        if job is None:
            raise NotFoundError(f"No job with id {args.job_id}.",
                                hint="List the ids with 'jobradar jobs --all'.")
        jobs = [job]
    else:
        scores = database.all_scores()
        applications = database.all_applications()
        candidates = [
            job for job in database.list_jobs()
            if (applications[job.id].status if job.id in applications else ApplicationStatus.ACTIVE)
            != ApplicationStatus.DISCARDED
        ]
        candidates.sort(key=lambda job: -(scores[job.id].tailored if job.id in scores else 0))
        jobs = candidates[: args.top]

    llm = build_client(settings.llm)
    try:
        for job in jobs:
            score = database.get_score(job.id) or score_job(job, profile)
            tailored = tailor(profile, job, score, settings, llm)
            result = render_cv(profile, tailored, job, database.paths, settings)
            lint = lint_tailored(profile, tailored, result.pages, settings.cv_max_pages)
            out(f"\n[bold]{job.company or 'Unnamed'} — {job.title}[/bold]")
            out(f"  {result.pdf_path or result.html_path}")
            out(f"  {result.pages or '?'} page(s), type scale {result.scale}, "
                f"written by {tailored.generated_by}")
            out(f"  Red-flag check: {lint.summary()}")
            for finding in lint.errors[:5]:
                out(f"    [red]•[/red] {finding.message}")
            for warning in result.warnings:
                out(f"    [yellow]•[/yellow] {warning}")

            from datetime import datetime, timezone

            from .models import GeneratedDocument

            database.save_document(GeneratedDocument(
                job_id=job.id, kind="cv", language=tailored.language,
                path=str(result.pdf_path or result.html_path),
                generated_at=datetime.now(timezone.utc),
                llm_generated=tailored.generated_by == "llm",
            ))
    finally:
        if llm:
            llm.close()
        database.close()
    return 0


def cmd_lint(args: argparse.Namespace) -> int:
    """Run the red-flag check over the profile."""
    database = _database(args)
    profile = database.load_profile()
    if profile is None:
        raise SetupRequiredError("No profile to check.",
                                 hint="Import a CV first: jobradar init --cv path/to/cv.pdf")
    result = lint_profile(profile, args.language)
    out(f"[bold]{result.summary()}[/bold]\n")
    for finding in result.findings:
        colour = {"error": "red", "warning": "yellow", "info": "cyan"}[finding.severity.value]
        out(f"[{colour}]{finding.severity.value.upper():<8}[/{colour}] {finding.message}")
        if finding.hint:
            out(f"         [dim]{finding.hint}[/dim]")
    database.close()
    return 0 if not result.errors else 1


def cmd_jobs(args: argparse.Namespace) -> int:
    """List the pipeline, in focus order."""
    database = _database(args)
    scores = database.all_scores()
    applications = database.all_applications()
    profile = database.load_profile()
    years = profile.years_of_experience() if profile else None
    rows: list[tuple[float, list[str]]] = []
    for job in database.list_jobs(include_closed=args.all):
        application = applications.get(job.id)
        status = application.status.value if application else "active"
        if args.status and status != args.status:
            continue
        score = scores.get(job.id)
        focus, _reason = focus_for(job, score, max_years=years)
        rows.append((focus, [
            f"{focus:.0f}",
            f"{score.tailored:.0f}%" if score else "—",
            status,
            (job.company or "")[:24],
            (job.title or "")[:40],
            (job.location or "")[:22],
            f"{salary.minimum:,}" if (salary := getattr(job, "salary", None)) and salary.minimum else "—",
            job.id,
        ]))
    rows.sort(key=lambda row: -row[0])
    table(f"{len(rows)} jobs",
          ["Focus", "Match", "Status", "Company", "Title", "Where", "Salary", "Id"],
          [cells for _focus, cells in rows[: args.limit]])
    database.close()
    return 0


def cmd_filtered(args: argparse.Namespace) -> int:
    """Show what the filters rejected — and optionally put one back.

    This is the command that answers "why is my board empty". The tally says
    which filter to reach for; the list says what it actually cost.
    """
    database = _database(args)
    if args.restore:
        job = database.restore_filtered(args.restore)
        if job is None:
            database.close()
            raise NotFoundError(f"{args.restore} is not in the filtered list.",
                                hint="See the ids with 'jobradar filtered'.")
        profile = database.load_profile()
        if profile is not None:
            database.save_score(job.id, score_job(job, profile))
        out(f"Restored [bold]{job.company or 'Unnamed'} — {job.title}[/bold]. "
            "The filter that rejected it is still on; change it in Settings if you meant to.")
        database.close()
        return 0

    if args.clear:
        database.clear_filtered()
        out("Filtered list emptied. The ads come back on the next search.")
        database.close()
        return 0

    entries = database.list_filtered(limit=args.limit)
    tally = database.filtered_tally()
    if not entries:
        out("Nothing has been filtered out.")
        database.close()
        return 0

    total = sum(count for _, count in tally["by_category"])
    table("What each filter is rejecting", ["Filter", "Jobs", "Share"],
          [[str(name), str(count), f"{100 * count / total:.0f}%"] for name, count in tally["by_category"]])
    table("The commonest reasons, verbatim", ["Reason (numbers as N)", "Count"],
          [[str(shape), str(count)] for shape, count in tally["by_shape"]])
    table(f"{len(entries)} filtered ads", ["Company", "Title", "Reason", "Id"],
                    [[str(e.get("company") or "")[:24], str(e.get("title") or "")[:38],
                        str(e.get("reason") or "")[:52], str(e.get("id") or "")] for e in entries])
    out("Put one back with [bold]jobradar filtered --restore <id>[/bold].")
    database.close()
    return 0


def cmd_export(args: argparse.Namespace) -> int:
    """Write the pipeline to a file."""
    database = _database(args)
    destination = Path(args.output) if args.output else (
        database.paths.exports_dir / f"jobradar.{'xlsx' if args.format == 'excel' else 'csv'}"
    )
    try:
        path = export_excel(database, destination) if args.format == "excel" else export_csv(database, destination)
    finally:
        database.close()
    out(f"Written to [bold]{path}[/bold]")
    return 0


def cmd_notify(args: argparse.Namespace) -> int:
    """Send a digest of the most recent jobs."""
    from .notify import build_digest, send_digest

    database = _database(args)
    settings = database.load_settings()
    jobs = database.list_jobs()[: args.limit]
    scores = database.all_scores()
    if args.dry_run:
        subject, body = build_digest(jobs, scores, min_score=settings.notifications.min_score)
        out(f"[bold]{subject}[/bold]\n\n{body}")
    else:
        sent = send_digest(jobs, scores, settings.notifications)
        out(json.dumps(sent) if sent else "No channel is enabled in settings.")
    database.close()
    return 0


def cmd_sources(args: argparse.Namespace) -> int:
    """Show every source and its status."""
    database = _database(args)
    settings = database.load_settings()
    from .sources import resolve_enabled

    enabled = set(resolve_enabled(settings.sources))
    rows = []
    for source in available_sources():
        missing = [name for name in source["required_env"] if not os.environ.get(name)]
        state = "on" if source["id"] in enabled else "off"
        if missing:
            state = f"needs {', '.join(missing)}"
        rows.append([source["id"], source["name"], source["tos_tier"], state])
    table("Sources", ["Id", "Name", "Tier", "Status"], rows)
    out("\n[dim]Restricted sources read pages built for people, not programs. They are off "
        "unless you enable them by name, and doing so is your call under the site's terms.[/dim]")
    database.close()
    return 0


def cmd_serve(args: argparse.Namespace) -> int:
    """Start the dashboard."""
    from .web import serve

    paths = Paths.resolve(getattr(args, "home", None))
    out(f"Dashboard on [bold]http://{args.host}:{args.port}[/bold] — data in {paths.home}")
    serve(host=args.host, port=args.port, paths=paths)
    return 0


def _scrapling_browsers_installed() -> bool:
    """Whether ``scrapling install`` has been run.

    ``scrapling[fetchers]`` itself is a required dependency, so it always
    imports; what it needs separately is its own one-time browser download.
    Scrapling's own ``install`` command marks completion with this exact
    file, so reading it is more honest than a browser launch attempt, which
    would make `doctor` slow and would itself need a browser to fail with.
    """
    try:
        from pathlib import Path

        import scrapling

        return (Path(scrapling.__file__).parent / ".scrapling_dependencies_installed").exists()
    except ImportError:
        return False


def _pdf_browser_check() -> tuple[str, bool, str]:
    """Whether a Chromium is there to print the CV, and which one."""
    from .documents.browser import (
        CHROMIUM_PATH_VARIABLE,
        expected_executable,
        fallback_executables,
    )

    label = "Browser for the PDF"
    expected = expected_executable()
    if expected is None:
        return label, False, "install Playwright first (see PDF rendering)"
    fallbacks = fallback_executables()
    if os.environ.get(CHROMIUM_PATH_VARIABLE) or not expected.exists():
        if fallbacks and fallbacks[0].exists():
            return f"{label} ({fallbacks[0]})", True, ""
        return label, False, (f"run 'playwright install chromium', or set {CHROMIUM_PATH_VARIABLE} "
                              "to a Chromium or Chrome executable")
    return label, True, ""


def cmd_doctor(args: argparse.Namespace) -> int:
    """Check the installation and report what is missing."""
    database = _database(args)
    settings = database.load_settings()
    profile = database.load_profile()
    checks: list[tuple[str, bool, str]] = []

    checks.append(("Configuration", settings.onboarded, "run 'jobradar init'"))
    checks.append(("Profile imported", profile is not None, "run 'jobradar init --cv <file>'"))
    checks.append(("Search titles set", bool(settings.search.titles), "add titles in settings"))

    for module, label, hint in (
        ("playwright", "PDF rendering", "pip install 'jobradar[pdf]' && playwright install chromium"),
        ("pypdf", "PDF CV import", "pip install 'jobradar[parse]'"),
        ("docx", "Word CV import", "pip install 'jobradar[parse]'"),
        ("openpyxl", "Excel export", "pip install 'jobradar[excel]'"),
    ):
        try:
            __import__(module)
            checks.append((label, True, ""))
        except ImportError:
            checks.append((label, False, hint))

    checks.append(_pdf_browser_check())

    checks.append((
        "Scrapling browsers (LinkedIn / InfoJobs / Tecnoempleo)",
        _scrapling_browsers_installed(),
        "run 'scrapling install' — only needed if you enable one of those three sources",
    ))

    llm = build_client(settings.llm)
    checks.append((f"Language model ({settings.llm.effective().provider})", llm is not None,
                   "optional — everything works without one"))
    if llm:
        llm.close()

    table("Checks", ["What", "State", "If not"],
          [[name, "ok" if ok else "missing", hint] for name, ok, hint in checks])
    out(f"\nData directory: [bold]{database.paths.home}[/bold]")
    database.close()
    return 0


# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="jobradar",
        description="Search job boards, score openings against your CV, and tailor an honest CV for each.",
    )
    parser.add_argument("--version", action="version", version=f"JobRadar {__version__}")
    parser.add_argument("--home", help="Data directory (default: ./data or $JOBRADAR_HOME)")
    parser.add_argument("-v", "--verbose", action="store_true", help="Log what the pipeline is doing")
    sub = parser.add_subparsers(dest="command", required=True)

    init = sub.add_parser("init", help="Create the configuration and import your CV")
    init.add_argument("--cv", help="Path to your current CV (PDF, DOCX or text)")
    init.add_argument("--config", help="Load settings from a YAML file instead of asking")
    init.set_defaults(func=cmd_init)

    demo = sub.add_parser("demo", help="Load a synthetic profile and jobs")
    demo.set_defaults(func=cmd_demo)

    search = sub.add_parser("search", help="Run the search pipeline")
    search.add_argument("--no-enrich", action="store_true", help="Skip fetching full ad text")
    search.add_argument(
        "--refresh", action="store_true",
        help="Re-read every ad, including ones already on file (slower; use after upgrading)",
    )
    search.add_argument("--no-llm", action="store_true", help="Force the deterministic path")
    search.add_argument("--explain", action="store_true", help="Show why jobs were dropped")
    search.add_argument("--notify", action="store_true", help="Send the digest afterwards")
    search.set_defaults(func=cmd_search)

    sweep = sub.add_parser("sweep", help="Retire ads that have closed")
    sweep.add_argument("--limit", type=_positive_int, default=None, help="Check at most N jobs")
    sweep.set_defaults(func=cmd_sweep)

    tailor_cmd = sub.add_parser("tailor", help="Generate tailored CVs")
    tailor_cmd.add_argument("job_id", nargs="?", help="Job id; omit to use --top")
    tailor_cmd.add_argument("--top", type=_positive_int, default=5, help="Generate for the best N jobs")
    tailor_cmd.add_argument("--no-llm", action="store_true")
    tailor_cmd.set_defaults(func=cmd_tailor)

    lint_cmd = sub.add_parser("lint", help="Run the recruiter red-flag check")
    lint_cmd.add_argument("--language", default=None)
    lint_cmd.set_defaults(func=cmd_lint)

    jobs = sub.add_parser("jobs", help="List the pipeline")
    jobs.add_argument("--status", choices=["active", "applied", "discarded"])
    jobs.add_argument("--all", action="store_true", help="Include closed ads")
    jobs.add_argument("--limit", type=_positive_int, default=40)
    jobs.set_defaults(func=cmd_jobs)

    filtered = sub.add_parser("filtered", help="Show what the filters rejected")
    filtered.add_argument("--limit", type=_positive_int, default=60)
    filtered.add_argument("--restore", metavar="JOB_ID",
                          help="Put one rejected ad back on the board")
    filtered.add_argument("--clear", action="store_true",
                          help="Empty the list; the ads return on the next search")
    filtered.set_defaults(func=cmd_filtered)

    export = sub.add_parser("export", help="Export to CSV or Excel")
    export.add_argument("--format", choices=["csv", "excel"], default="csv")
    export.add_argument("--output", help="Destination file")
    export.set_defaults(func=cmd_export)

    notify = sub.add_parser("notify", help="Send the digest")
    notify.add_argument("--limit", type=_positive_int, default=15)
    notify.add_argument("--dry-run", action="store_true", help="Print it instead of sending")
    notify.set_defaults(func=cmd_notify)

    sources = sub.add_parser("sources", help="Show every source and its status")
    sources.set_defaults(func=cmd_sources)

    serve_cmd = sub.add_parser("serve", help="Start the local dashboard")
    serve_cmd.add_argument("--host", default="127.0.0.1")
    serve_cmd.add_argument("--port", type=_port, default=8000)
    serve_cmd.set_defaults(func=cmd_serve)

    doctor = sub.add_parser("doctor", help="Check the installation")
    doctor.set_defaults(func=cmd_doctor)

    return parser


def main(argv: list[str] | None = None) -> int:
    load_dotenv()
    parser = build_parser()
    args = parser.parse_args(argv)
    logging.basicConfig(
        level=logging.INFO if args.verbose else logging.WARNING,
        format="%(levelname)s %(name)s: %(message)s",
    )
    try:
        return args.func(args)
    except KeyboardInterrupt:
        out("\nInterrupted.")
        return 130
    except EOFError:
        # ``input()`` with stdin closed: ``jobradar init`` run unattended.
        _report("No answer could be read: standard input is closed.",
                "Run 'jobradar init' in a terminal, or pass --config settings.yaml.")
        return 2
    except JobRadarError as exc:
        if args.verbose:
            logging.getLogger("jobradar").exception("%s", type(exc).__name__)
        _report(exc.message, exc.hint)
        return exc.exit_code
    except Exception as exc:  # a bug: say so plainly instead of dumping a traceback
        if args.verbose:
            logging.getLogger("jobradar").exception("Unexpected error")
        detail = "the traceback above" if args.verbose else "the traceback from a rerun with -v"
        _report(
            f"Unexpected error ({type(exc).__name__}): {exc}",
            f"This is a bug in JobRadar; please report it with {detail} at "
            "https://github.com/inigo99/jobradar/issues",
        )
        return 1


def _report(message: str, hint: str = "") -> None:
    """Print an error to stderr, where scripts and cron mail look for it."""
    try:
        from rich.console import Console
        from rich.markup import escape
    except ImportError:  # pragma: no cover - rich is a dependency
        print(f"Error: {message}", file=sys.stderr)
        if hint:
            print(f"Hint: {hint}", file=sys.stderr)
        return
    err = Console(stderr=True, soft_wrap=True)  # never break a path mid-line
    err.print(f"[bold red]Error:[/bold red] {escape(message)}")
    if hint:
        err.print(f"[yellow]Hint:[/yellow] {escape(hint)}")

if __name__ == "__main__":
    sys.exit(main())
