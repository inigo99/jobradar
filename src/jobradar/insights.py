"""Is the search working? The application funnel and the run history.

Two questions the board cannot answer on its own:

*The funnel* — of the applications sent, which get a human reply, and where
do those come from? Grouped by source (is this board worth searching?), by
job family, and by match-score band (does the score predict anything, or do
60 % matches reply as often as 95 % ones?). Also: the median days to a reply,
companies that swallow applications without answering, and the applications
waiting longest, to decide whether to follow up.

*The run history* — per source, how much each search fetched and kept, how
often a source failed or was skipped, what the filters removed and how long
runs take: enough to decide with numbers whether a source is worth keeping.

Definitions, so the numbers mean something:

* an *application* is a job marked as applied;
* a *reply* is a person moving: a rejection or a next step read from the
  inbox, or the user moving the stage past "applied". An automatic
  acknowledgement is not a reply — an applicant-tracking system sends it;
* a rate is only shown for groups of at least :data:`MIN_SAMPLE`
  applications: 1 reply out of 2 is not a 50 % response rate.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from statistics import median

from .families import Family, label_for
from .models import (
    Application,
    ApplicationStage,
    ApplicationStatus,
    Job,
    MailKind,
    MailNews,
    MatchScore,
    SearchRun,
)
from .pipeline.dedupe import company_key

MIN_SAMPLE = 5
#: Match-score bands: (lower bound inclusive, upper exclusive, label).
SCORE_BANDS = ((0, 60, "under 60 %"), (60, 75, "60–75 %"), (75, 90, "75–90 %"),
               (90, 101, "90 % or more"))
#: A company is "saturated" from this many ads on the board, or applications.
SATURATED_ADS, SATURATED_APPLICATIONS = 4, 3


@dataclass
class Group:
    """Counts for one slice of the applications."""

    applications: int = 0
    replies: int = 0
    rejections: int = 0
    advances: int = 0
    acknowledged: int = 0
    alive: int = 0

    @property
    def response_rate(self) -> float | None:
        if self.applications < MIN_SAMPLE:
            return None
        return round(100.0 * self.replies / self.applications, 1)

    def as_dict(self) -> dict:
        return {**self.__dict__, "response_rate": self.response_rate}


@dataclass
class Funnel:
    total: Group = field(default_factory=Group)
    by_source: dict[str, Group] = field(default_factory=dict)
    by_family: dict[str, Group] = field(default_factory=dict)
    by_score: dict[str, Group] = field(default_factory=dict)
    median_days_to_reply: float | None = None
    saturated: list[dict] = field(default_factory=list)
    waiting: list[dict] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "total": self.total.as_dict(),
            "by_source": {k: g.as_dict() for k, g in self.by_source.items()},
            "by_family": {k: g.as_dict() for k, g in self.by_family.items()},
            "by_score": {k: g.as_dict() for k, g in self.by_score.items()},
            "median_days_to_reply": self.median_days_to_reply,
            "saturated": self.saturated,
            "waiting": self.waiting,
            "min_sample": MIN_SAMPLE,
        }


def score_band(score: float) -> str:
    for low, high, label in SCORE_BANDS:
        if low <= score < high:
            return label
    return SCORE_BANDS[-1][2]


def _replied(application: Application, news: MailNews | None) -> bool:
    moved = application.stage not in (None, ApplicationStage.APPLIED)
    return moved or (news is not None and news.kind in (MailKind.ADVANCE, MailKind.REJECTION))


def _rejected(application: Application, news: MailNews | None) -> bool:
    return application.stage == ApplicationStage.REJECTED or (
        news is not None and news.kind == MailKind.REJECTION)


def _add(group: Group, application: Application, news: MailNews | None) -> None:
    group.applications += 1
    if _replied(application, news):
        group.replies += 1
    if _rejected(application, news):
        group.rejections += 1
    elif application.stage in (ApplicationStage.SCREENING, ApplicationStage.INTERVIEW,
                               ApplicationStage.OFFER) or (
            news is not None and news.kind == MailKind.ADVANCE):
        group.advances += 1
    if news is not None and news.kind == MailKind.ACKNOWLEDGEMENT:
        group.acknowledged += 1
    if not _rejected(application, news):
        group.alive += 1


def funnel(
    jobs: list[Job],
    applications: dict[str, Application],
    scores: dict[str, MatchScore],
    mail: dict[str, MailNews],
    families: dict[str, Family],
    today: date | None = None,
) -> Funnel:
    """The funnel over every job marked as applied."""
    today = today or date.today()
    by_id = {job.id: job for job in jobs}
    result = Funnel()
    days_to_reply: list[int] = []
    for job_id, application in applications.items():
        if application.status != ApplicationStatus.APPLIED:
            continue
        job = by_id.get(job_id)
        news = mail.get(job_id)
        score = scores.get(job_id)
        _add(result.total, application, news)
        source = job.source if job else "unknown"
        family = label_for(job.family, families) if job and job.family else "General"
        _add(result.by_source.setdefault(source, Group()), application, news)
        _add(result.by_family.setdefault(family, Group()), application, news)
        _add(result.by_score.setdefault(score_band(score.tailored if score else 0.0), Group()),
             application, news)
        applied_on = application.applied_on
        if applied_on and news and news.kind in (MailKind.ADVANCE, MailKind.REJECTION):
            days_to_reply.append(max(0, (news.received_at.date() - applied_on).days))
        elif applied_on and not _replied(application, news):
            result.waiting.append({
                "id": job_id,
                "company": job.company if job else "",
                "title": job.title if job else "",
                "applied_on": applied_on.isoformat(),
                "days": (today - applied_on).days,
            })
    result.median_days_to_reply = float(median(days_to_reply)) if days_to_reply else None
    result.waiting.sort(key=lambda w: -w["days"])
    result.waiting = result.waiting[:10]
    result.by_score = {label: result.by_score[label] for _, _, label in SCORE_BANDS
                       if label in result.by_score}
    result.saturated = _saturated(jobs, applications, mail)
    return result


def _saturated(jobs: list[Job], applications: dict[str, Application],
               mail: dict[str, MailNews]) -> list[dict]:
    """Companies with many ads or applications and no human reply."""
    companies: dict[str, dict] = {}
    for job in jobs:
        key = company_key(job.company or "")
        if not key:
            continue
        entry = companies.setdefault(key, {"company": job.company, "on_board": 0,
                                           "applied": 0, "replies": 0})
        entry["on_board"] += 1
        application = applications.get(job.id)
        if application and application.status == ApplicationStatus.APPLIED:
            entry["applied"] += 1
            if _replied(application, mail.get(job.id)):
                entry["replies"] += 1
    busy = [e for e in companies.values()
            if (e["on_board"] >= SATURATED_ADS or e["applied"] >= SATURATED_APPLICATIONS)
            and e["replies"] == 0]
    busy.sort(key=lambda e: (-e["applied"], -e["on_board"]))
    return busy[:12]


# ---------------------------------------------------------------------------
# Run history
# ---------------------------------------------------------------------------


def history(runs: list[SearchRun]) -> dict:
    """Totals and per-source figures over ``runs`` (newest first, as stored)."""
    per_source: dict[str, dict] = {}
    filtered: dict[str, int] = {}
    durations = [r.duration_seconds for r in runs if r.duration_seconds is not None]
    for run in runs:
        for source, counts in run.by_source.items():
            entry = per_source.setdefault(source, {"runs": 0, "fetched": 0, "kept": 0,
                                                   "failed": 0, "skipped": 0})
            entry["runs"] += 1
            entry["fetched"] += counts.get("fetched", 0)
            entry["kept"] += counts.get("kept", 0)
        for error in run.errors:
            source = error.split(":", 1)[0].strip()
            per_source.setdefault(source, {"runs": 0, "fetched": 0, "kept": 0,
                                           "failed": 0, "skipped": 0})["failed"] += 1
        for skip in run.skipped_sources:
            per_source.setdefault(skip.get("source", "?"), {"runs": 0, "fetched": 0, "kept": 0,
                                                            "failed": 0, "skipped": 0})[
                "skipped"] += 1
        for category, count in run.filtered_by_category.items():
            filtered[category] = filtered.get(category, 0) + count
    for entry in per_source.values():
        entry["kept_share"] = round(100.0 * entry["kept"] / entry["fetched"], 1) \
            if entry["fetched"] else None
    fetched = sum(r.fetched for r in runs)
    duplicates = sum((r.fetched - r.after_dedupe) + r.known_duplicates for r in runs)
    return {
        "runs": len(runs),
        "since": runs[-1].started_at.date().isoformat() if runs else None,
        "fetched": fetched,
        "kept": sum(r.kept for r in runs),
        "new": sum(r.new for r in runs),
        "duplicate_share": round(100.0 * duplicates / fetched, 1) if fetched else None,
        "median_minutes": round(median(durations) / 60.0, 1) if durations else None,
        "by_source": dict(sorted(per_source.items(), key=lambda item: -item[1]["kept"])),
        "filtered_by_category": dict(sorted(filtered.items(), key=lambda item: -item[1])),
        "recent": [
            {
                "started_at": r.started_at.isoformat(timespec="minutes"),
                "minutes": round(r.duration_seconds / 60.0, 1)
                if r.duration_seconds is not None else None,
                "fetched": r.fetched, "kept": r.kept, "new": r.new,
                "errors": len(r.errors) + len(r.fetch_problems),
            }
            for r in runs[:15]
        ],
    }
