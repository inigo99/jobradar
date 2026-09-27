"""The search orchestrator.

One run is: ask every enabled source for jobs, collapse duplicates, discard
anything already known or already closed, enrich what is left, filter it, score
it against the profile, and store the survivors.

Two ordering decisions are worth calling out, because both cost money and time
if you get them wrong:

* **Deduplicate before enriching.** Enrichment is the expensive step — a page
  fetch and possibly a model call per job. Collapsing the three copies of the
  same opening first cuts that bill by roughly the duplication rate, which on a
  multi-source run is substantial.
* **Filter what can be filtered before enriching too.** Age needs no ad body,
  so it runs early; work mode, geography and salary need the ad, so they run
  after. This is why :func:`_prefilter` exists separately.
* **Never read the same ad twice.** A job already on file (active, or rejected
  by a filter) keeps its stored reading: the listing is matched to it and the
  filters and the score are re-applied — both cheap, and both can change when
  the settings or the profile do — but the ad is not fetched and the model is
  not asked again. ``refresh=True`` (``jobradar search --refresh``) forces a
  full re-read, e.g. after upgrading the extraction rules.
* **A new id is not necessarily a new job.** Reposts and the same opening on
  another board are matched against everything on file, closed and aged-out
  jobs included, and set aside with the job they duplicate.
* **Store as you go.** Sources are handled one at a time, and each job is
  saved the moment it is read, filtered and scored, so the dashboard fills up
  while the run is still going instead of all at once at the end. A later
  board's copy of a job already kept this run is folded into it.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from typing import TYPE_CHECKING

from ..config import Paths, Settings
from ..errors import JobRadarError
from ..llm import LLMClient, build_client
from ..models import Job, MatchScore, Profile, SearchRun
from ..sources import SearchQuery, build_sources
from ..sources.base import Fetcher, JobSource
from ..storage import Database
from .dedupe import _merge, deduplicate, split_known
from .enrich import enrich_job
from .filters import apply_filters
from .filters import category as filter_category
from .prune import prune_stale
from .salary import ExchangeRates
from .scoring import score_job

if TYPE_CHECKING:
    from ..mail import MailReport

log = logging.getLogger(__name__)


@dataclass
class SearchProgress:
    """Where a running search is, for the dashboard's progress line."""

    sources_total: int = 0
    sources_done: int = 0
    #: The source being asked or read now.
    source: str = ""
    #: "searching" (asking the source), "reading" (its ads, one by one) or "done".
    stage: str = ""
    #: The current source's ads left after duplicates, and how many are read.
    to_read: int = 0
    read: int = 0
    kept: int = 0
    new: int = 0
    filtered: int = 0


@dataclass
class SearchResult:
    """Everything one run produced, for the CLI, the API and the digest."""

    run: SearchRun
    kept: list[Job] = field(default_factory=list)
    new_jobs: list[Job] = field(default_factory=list)
    scores: dict[str, MatchScore] = field(default_factory=dict)
    #: job id -> why it was dropped, for `jobradar search --explain`.
    rejected: dict[str, str] = field(default_factory=dict)
    #: The same rejections with the job attached, so they can be stored and
    #: read later. A rejection whose job is thrown away is a number; one that
    #: keeps the job is something the user can disagree with.
    filtered: list[tuple[Job, str]] = field(default_factory=list)
    warnings: dict[str, list[str]] = field(default_factory=dict)
    #: What the inbox check after the run found, when mail is switched on.
    mail: MailReport | None = None
    #: Why the inbox could not be checked, when it could not.
    mail_error: str = ""


class SearchPipeline:
    """Runs one search end to end.

    Constructed with everything it needs so that tests can substitute a fake
    source list, a fake clock or a null language model.
    """

    def __init__(
        self,
        settings: Settings,
        profile: Profile | None,
        database: Database,
        sources: list[JobSource] | None = None,
        llm: LLMClient | None = None,
        rates: ExchangeRates | None = None,
        today: date | None = None,
        refresh: bool = False,
    ):
        self.settings = settings
        self.profile = profile
        self.database = database
        self.llm = llm
        self.rates = rates
        self.today = today or date.today()
        self.refresh = refresh
        self._sources = sources
        self._fetcher: Fetcher | None = None
        #: Enabled sources that will not run this time, filled by sources().
        self.skipped_sources: list[dict[str, str]] = []

    # -- setup -------------------------------------------------------------

    def sources(self) -> list[JobSource]:
        if self._sources is None:
            self._sources, self._fetcher = build_sources(
                self.settings, self.database.paths.cache_dir, today=self.today,
                skipped=self.skipped_sources)
        return self._sources

    def query(self) -> SearchQuery:
        filters = self.settings.filters
        from ..models import WorkMode

        return SearchQuery(
            titles=self.settings.search.titles,
            keywords=self.settings.search.keywords,
            countries=filters.effective_countries(),
            local_areas=filters.local_areas,
            local_only=filters.local_only and bool(filters.local_areas),
            remote_only=filters.work_modes == [WorkMode.REMOTE],
            max_age_days=filters.max_age_days,
            limit=self.settings.sources.max_results_per_source,
            languages=self.settings.search.languages,
        )

    # -- stages ------------------------------------------------------------

    def _ask(self, source: JobSource, query: SearchQuery, run: SearchRun) -> list[Job] | None:
        """One source's listings, or None when it failed; one broken board must not end the run."""
        try:
            found = source.search(query)
        except Exception as exc:
            log.warning("Source %s failed: %s", source.id, exc)
            run.errors.append(f"{source.id}: {exc}")
            return None
        log.info("%s returned %d jobs", source.name, len(found))
        run.sources.append(source.id)
        return found

    def _prefilter(
        self, jobs: list[Job]
    ) -> tuple[list[Job], dict[str, str], list[tuple[Job, str]]]:
        """Cheap rejections that need no ad body: deleted, known-closed and old ads."""
        known_closed = self.database.closed_job_ids()
        deleted = self.database.deleted_job_ids()
        rejected: dict[str, str] = {}
        filtered: list[tuple[Job, str]] = []
        survivors: list[Job] = []
        for job in jobs:
            if job.id in deleted:
                # The user deleted this ad from the board; it stays gone.
                rejected[job.id] = "deleted by you"
                continue
            if job.id in known_closed:
                # Not a filter decision: the ad is gone, and it is already
                # recorded in closed_jobs. Nothing to reconsider.
                rejected[job.id] = "previously recorded as closed"
                continue
            age = job.age_days(self.today)
            if age is not None and age > self.settings.filters.max_age_days:
                reason = f"published {age} days ago (limit {self.settings.filters.max_age_days})"
                rejected[job.id] = reason
                filtered.append((job, reason))
                continue
            survivors.append(job)
        return survivors, rejected, filtered

    def _source_for(self, job: Job) -> JobSource | None:
        return next((source for source in self.sources() if source.id == job.source), None)

    def _stored_reading(self, listed: Job) -> Job | None:
        """The enriched record already on file for this id, if there is one."""
        if self.refresh:
            return None
        stored = self.database.get_job(listed.id) or self.database.get_filtered_job(listed.id)
        if stored is None or not stored.raw.get("enriched_by"):
            return None
        # What the listing knows that the stored record may not.
        stored.posted_at = stored.posted_at or listed.posted_at
        stored.apply_url = stored.apply_url or listed.apply_url
        return stored

    # -- run ---------------------------------------------------------------

    def run(
        self,
        enrich: bool = True,
        progress: Callable[[SearchProgress], None] | None = None,
        cancel: threading.Event | None = None,
    ) -> SearchResult:
        """Search every source, storing each job as soon as it is decided.

        ``progress`` is called after every step with where the run is;
        ``cancel``, once set, stops the run after the job being read — what
        was stored so far stays.
        """
        started = datetime.now(timezone.utc)
        pruned = prune_stale(self.database, self.settings.prune_after_days, self.today)
        query = self.query()
        sources = self.sources()
        result = SearchResult(run=SearchRun(started_at=started, pruned=len(pruned)))
        state = SearchProgress(sources_total=len(sources))

        def report(**changes: object) -> None:
            for name, value in changes.items():
                setattr(state, name, value)
            if progress is not None:
                try:
                    progress(state)
                except Exception:  # a broken listener must not cost the run
                    log.exception("The search progress listener failed")

        # The years ceiling comes from the profile's own dates unless the user
        # typed a number, so it rises on its own instead of ageing quietly.
        profile_years = self.profile.years_of_experience(self.today) if self.profile else None
        known_on_file = self.database.list_jobs(include_closed=True)
        known_ids = self.database.known_job_ids()
        #: Every job decided this run, by id, and the ones kept: a later
        #: board's copy of a kept job is folded into it, not read again.
        decided: dict[str, Job] = {}
        kept: dict[str, Job] = {}
        by_source: dict[str, dict[str, int]] = {}

        def cancelled() -> bool:
            return cancel is not None and cancel.is_set()

        def reject(job: Job, reason: str) -> None:
            result.rejected[job.id] = reason
            if reason in ("deleted by you", "previously recorded as closed"):
                return  # nothing to reconsider: the job is gone, not filtered
            result.filtered.append((job, reason))
            # Nothing rejected is thrown away: a filter one notch too strict is
            # invisible while its victims vanish, and the symptom — an empty
            # board — looks exactly like "there were no jobs today".
            self.database.save_filtered([(job, reason, filter_category(reason))])
            report(filtered=state.filtered + 1)

        def fold(twin: Job, copy: Job) -> None:
            """Another board's copy of a job kept this run: add what it knows."""
            _merge(twin, copy)
            self.database.upsert_jobs([twin])
            if self.profile:
                result.scores[twin.id] = score_job(twin, self.profile)
                self.database.save_score(twin.id, result.scores[twin.id])

        try:
            for index, source in enumerate(sources):
                if cancelled():
                    break
                report(source=source.name, stage="searching", to_read=0, read=0)
                found = self._ask(source, query, result.run)
                if found is not None:
                    result.run.fetched += len(found)
                    for job in found:
                        by_source.setdefault(job.source or "unknown",
                                             {"fetched": 0, "kept": 0})["fetched"] += 1
                    self._handle(found, enrich, result, known_on_file, known_ids, decided,
                                 kept, by_source, profile_years, reject, fold, report,
                                 cancelled)
                report(sources_done=index + 1)
        finally:
            # Written whatever happened, so a cancelled or crashed run still
            # leaves its line in the history next to the jobs it stored.
            result.run.cancelled = cancelled()
            result.run.kept = len(result.kept)
            result.run.new = len(result.new_jobs)
            result.run.by_source = by_source
            result.run.skipped_sources = list(self.skipped_sources)
            categories: dict[str, int] = {}
            for _job, reason in result.filtered:
                key = filter_category(reason)
                categories[key] = categories.get(key, 0) + 1
            result.run.filtered_by_category = categories
            if self._fetcher is not None:
                result.run.fetch_problems = list(self._fetcher.problems)
            result.run.finished_at = datetime.now(timezone.utc)
            self.database.log_run(result.run)
            if self._fetcher is not None:
                self._fetcher.close()
            report(stage="done")
        return result

    def _handle(self, found: list[Job], enrich: bool, result: SearchResult,
                known_on_file: list[Job], known_ids: set[str], decided: dict[str, Job],
                kept: dict[str, Job], by_source: dict[str, dict[str, int]],
                profile_years: float | None, reject: Callable[[Job, str], None],
                fold: Callable[[Job, Job], None], report: Callable[..., None],
                cancelled: Callable[[], bool]) -> None:
        """Deduplicate, read, filter, score and store one source's listings."""
        batch: list[Job] = []
        for job in deduplicate(found):
            if job.id in kept:
                fold(kept[job.id], job)
            elif job.id not in decided:
                batch.append(job)
        # The same opening on a board read earlier this run.
        batch, twins = split_known(batch, kept.values())
        for job, twin in twins:
            fold(twin, job)
        result.run.after_dedupe += len(batch)

        fresh, known_duplicates = split_known(batch, known_on_file)
        for job, twin in known_duplicates:
            decided[job.id] = job
            result.run.known_duplicates += 1
            reject(job, f"duplicate of a job already on file ({twin.company} — {twin.title})")
        candidates, rejected, prefiltered = self._prefilter(fresh)
        for job in fresh:
            if job.id in rejected:
                decided[job.id] = job
        for job, reason in prefiltered:
            reject(job, reason)
        for job_id, reason in rejected.items():
            if job_id not in result.rejected:
                result.rejected[job_id] = reason

        report(stage="reading", to_read=len(candidates), read=0)
        for number, listed in enumerate(candidates, start=1):
            if cancelled():
                return
            job = self._read(listed, enrich, result)
            decided[job.id] = job
            outcome = apply_filters(
                job, self.settings.filters, self.rates, self.today, profile_years
            )
            if not outcome.keep:
                reject(job, outcome.reason)
            elif job.id in self.database.deleted_job_ids():
                # Deleted from the board while this run was reading it.
                result.rejected[job.id] = "deleted by you"
            else:
                self._keep(job, outcome.warnings, result, known_ids, kept, by_source)
                report(kept=len(result.kept), new=len(result.new_jobs))
            report(read=number)

    def _read(self, listed: Job, enrich: bool, result: SearchResult) -> Job:
        """The job with its ad read: the stored reading if there is one."""
        if not enrich:
            return listed
        stored = self._stored_reading(listed)
        if stored is not None:
            result.run.reused += 1
            return stored
        source = self._source_for(listed)
        enrich_job(
            listed,
            self.settings,
            llm=self.llm,
            rates=self.rates,
            fetch_description=source.fetch_description if source else None,
            resolve_work_mode=source.resolve_work_mode if source else None,
        )
        return listed

    def _keep(self, job: Job, warnings: Sequence[str], result: SearchResult, known_ids: set[str],
              kept: dict[str, Job], by_source: dict[str, dict[str, int]]) -> None:
        """Store a job that passed the filters, with its score, right away."""
        if warnings:
            result.warnings[job.id] = list(warnings)
            if job.alerts is None:
                job.alerts = []
            for warning in warnings:
                if warning not in job.alerts:
                    job.alerts.append(warning)
        self.database.upsert_jobs([job])
        self.database.drop_filtered([job.id])
        kept[job.id] = job
        result.kept.append(job)
        by_source.setdefault(job.source or "unknown", {"fetched": 0, "kept": 0})["kept"] += 1
        if job.id not in known_ids:
            result.new_jobs.append(job)
        if self.profile:
            result.scores[job.id] = score_job(job, self.profile)
            self.database.save_score(job.id, result.scores[job.id])


def run_search(
    settings: Settings | None = None,
    paths: Paths | None = None,
    database: Database | None = None,
    enrich: bool = True,
    refresh: bool = False,
    progress: Callable[[SearchProgress], None] | None = None,
    cancel: threading.Event | None = None,
) -> SearchResult:
    """Convenience entry point used by the CLI, the API and scheduled runs."""
    paths = paths or Paths.resolve()
    owns_database = database is None
    database = database or Database(paths)
    settings = settings or database.load_settings()
    profile = database.load_profile()

    pipeline = SearchPipeline(
        settings=settings,
        profile=profile,
        database=database,
        llm=build_client(settings.llm),
        rates=ExchangeRates.load(paths.cache_dir),
        refresh=refresh,
    )
    try:
        result = pipeline.run(enrich=enrich, progress=progress, cancel=cancel)
        if settings.mail.enabled and settings.mail.check_after_search and not result.run.cancelled:
            # A mail problem must not cost the search its results.
            # Imported here: jobradar.mail uses this package's dedupe helpers.
            from ..mail import check_mail

            try:
                result.mail = check_mail(database, settings)
            except JobRadarError as exc:
                result.mail_error = f"{exc.message} {exc.hint}".strip()
                log.warning("Mail check skipped: %s", result.mail_error)
        return result
    finally:
        if owns_database:
            database.close()
