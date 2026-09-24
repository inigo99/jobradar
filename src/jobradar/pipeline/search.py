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
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date, datetime, timezone

from ..config import Paths, Settings
from ..llm import LLMClient, build_client
from ..models import Job, MatchScore, Profile, SearchRun
from ..sources import SearchQuery, build_sources
from ..sources.base import Fetcher, JobSource
from ..storage import Database
from .dedupe import deduplicate, split_known
from .enrich import enrich_job
from .filters import apply_filters
from .filters import category as filter_category
from .prune import prune_stale
from .salary import ExchangeRates
from .scoring import score_job

log = logging.getLogger(__name__)


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

    # -- setup -------------------------------------------------------------

    def sources(self) -> list[JobSource]:
        if self._sources is None:
            self._sources, self._fetcher = build_sources(
                self.settings, self.database.paths.cache_dir, today=self.today)
        return self._sources

    def query(self) -> SearchQuery:
        filters = self.settings.filters
        from ..models import WorkMode

        return SearchQuery(
            titles=self.settings.search.titles,
            keywords=self.settings.search.keywords,
            countries=filters.effective_countries(),
            local_areas=filters.local_areas,
            remote_only=filters.work_modes == [WorkMode.REMOTE],
            max_age_days=filters.max_age_days,
            limit=self.settings.sources.max_results_per_source,
            languages=self.settings.search.languages,
        )

    # -- stages ------------------------------------------------------------

    def collect(self, query: SearchQuery) -> tuple[list[Job], list[str], list[str]]:
        """Ask every source, tolerating individual failures."""
        collected: list[Job] = []
        used: list[str] = []
        errors: list[str] = []
        for source in self.sources():
            try:
                found = source.search(query)
            except Exception as exc:  # one broken board must not end the run
                log.warning("Source %s failed: %s", source.id, exc)
                errors.append(f"{source.id}: {exc}")
                continue
            log.info("%s returned %d jobs", source.name, len(found))
            used.append(source.id)
            collected.extend(found)
        return collected, used, errors

    def _prefilter(
        self, jobs: list[Job]
    ) -> tuple[list[Job], dict[str, str], list[tuple[Job, str]]]:
        """Cheap rejections that need no ad body: age and known-closed ads."""
        known_closed = self.database.closed_job_ids()
        rejected: dict[str, str] = {}
        filtered: list[tuple[Job, str]] = []
        survivors: list[Job] = []
        for job in jobs:
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

    def run(self, enrich: bool = True) -> SearchResult:
        started = datetime.now(timezone.utc)
        pruned = prune_stale(self.database, self.settings.prune_after_days, self.today)
        query = self.query()

        collected, used, errors = self.collect(query)
        deduped = deduplicate(collected)
        known_on_file = self.database.list_jobs(include_closed=True)
        fresh, known_duplicates = split_known(deduped, known_on_file)
        candidates, rejected, prefiltered = self._prefilter(fresh)

        known_ids = self.database.known_job_ids()
        by_source: dict[str, dict[str, int]] = {}
        for job in collected:
            counts = by_source.setdefault(job.source or "unknown", {"fetched": 0, "kept": 0})
            counts["fetched"] += 1
        result = SearchResult(
            run=SearchRun(
                started_at=started,
                sources=used,
                fetched=len(collected),
                after_dedupe=len(deduped),
                known_duplicates=len(known_duplicates),
                pruned=len(pruned),
                errors=errors,
            ),
            rejected=rejected,
            filtered=list(prefiltered),
        )
        for job, twin in known_duplicates:
            reason = f"duplicate of a job already on file ({twin.company} — {twin.title})"
            result.rejected[job.id] = reason
            result.filtered.append((job, reason))

        # The years ceiling comes from the profile's own dates unless the user
        # typed a number, so it rises on its own instead of ageing quietly.
        profile_years = self.profile.years_of_experience(self.today) if self.profile else None

        for listed in candidates:
            job = listed
            if enrich:
                stored = self._stored_reading(listed)
                if stored is not None:
                    job = stored
                    result.run.reused += 1
                else:
                    source = self._source_for(job)
                    enrich_job(
                        job,
                        self.settings,
                        llm=self.llm,
                        rates=self.rates,
                        fetch_description=source.fetch_description if source else None,
                        resolve_work_mode=source.resolve_work_mode if source else None,
                    )

            outcome = apply_filters(
                job, self.settings.filters, self.rates, self.today, profile_years
            )
            if not outcome.keep:
                result.rejected[job.id] = outcome.reason
                result.filtered.append((job, outcome.reason))
                continue
            if outcome.warnings:
                result.warnings[job.id] = list(outcome.warnings)
                if job.alerts is None:
                    job.alerts = []
                for warning in outcome.warnings:
                    if warning not in job.alerts:
                        job.alerts.append(warning)

            result.kept.append(job)
            by_source.setdefault(job.source or "unknown", {"fetched": 0, "kept": 0})["kept"] += 1
            if job.id not in known_ids:
                result.new_jobs.append(job)

            if self.profile:
                result.scores[job.id] = score_job(job, self.profile)

        # Nothing rejected is thrown away: a filter one notch too strict is
        # invisible while its victims vanish, and the symptom — an empty
        # board — looks exactly like "there were no jobs today".
        kept_ids = {job.id for job in result.kept}
        self.database.save_filtered(
            (job, reason, filter_category(reason))
            for job, reason in result.filtered
            if job.id not in kept_ids
        )
        self.database.drop_filtered(sorted(kept_ids))

        new, _updated = self.database.upsert_jobs(result.kept)
        for job_id, score in result.scores.items():
            self.database.save_score(job_id, score)

        result.run.kept = len(result.kept)
        result.run.new = new
        result.run.by_source = by_source
        result.run.finished_at = datetime.now(timezone.utc)
        self.database.log_run(result.run)

        if self._fetcher is not None:
            self._fetcher.close()
        return result


def run_search(
    settings: Settings | None = None,
    paths: Paths | None = None,
    database: Database | None = None,
    enrich: bool = True,
    refresh: bool = False,
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
        return pipeline.run(enrich=enrich)
    finally:
        if owns_database:
            database.close()
