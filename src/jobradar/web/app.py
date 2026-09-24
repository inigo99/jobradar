"""The dashboard server.

Routes are thin: every one of them loads state from SQLite, calls into the
pipeline or the documents package, and returns JSON. All the behaviour lives in
those packages, which is what makes the same operations available from the CLI.

The server binds to ``127.0.0.1`` by default. The database contains the user's
CV, contact details and job-search history; putting that on a public interface
would be a poor default, so exposing it takes an explicit ``--host``.

Binding to loopback is not enough on its own. Any web page open in the same
browser can send a form POST to ``http://127.0.0.1:8000`` (no CORS preflight is
involved for a form), and a DNS-rebinding page can make the browser treat the
server as its own origin. Two checks close both:

* the ``Host`` header must be one of the names the server was started for
  (loopback by default), which defeats rebinding;
* requests that change something must not come from another origin: a
  cross-origin ``Origin`` header or ``Sec-Fetch-Site: cross-site`` is refused.
  Requests without either header (the CLI, curl, scripts) are unaffected.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
from collections.abc import Iterable
from contextlib import asynccontextmanager
from datetime import date, datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

from fastapi import FastAPI, File, Form, HTTPException, Query, UploadFile
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import ValidationError
from starlette.requests import Request

from .. import __version__
from ..config import Paths, countries, load_dotenv, validation_summary
from ..documents import generate_cover_letter, generate_email, render_cv, tailor
from ..documents.answers import add_turn, answer, to_bank
from ..documents.letters import contact_line
from ..documents.pdfwriter import letter_pdf
from ..documents.review import measure, review_text
from ..errors import JobRadarError, ProfileError, StorageError, describe_os_error
from ..families import Family, catalogue_view, families_for
from ..families import classify as classify_family
from ..families import label_for as family_label
from ..insights import funnel, history
from ..lint import lint_profile, lint_tailored
from ..llm import build_client
from ..mail import check_mail, interview_ics
from ..mail.imap import configured as mail_configured
from ..models import (
    AnswerThread,
    Application,
    ApplicationStatus,
    CvVariant,
    GeneratedDocument,
    Job,
    MatchScore,
    Profile,
    Salary,
    SalaryOrigin,
    SkillGroup,
    localized,
)
from ..pipeline import run_search, sweep_closed
from ..pipeline.enrich import enrich_job
from ..pipeline.filters import check_experience, experience_ceiling
from ..pipeline.focus import focus_for
from ..pipeline.salary import ExchangeRates
from ..pipeline.scoring import score_job
from ..profile import import_profile
from ..profile.vocabulary import SkillEdit, apply_skill_edits, carry_over
from ..sources import available as available_sources
from ..storage import Database
from ..textutils import slugify
from .api import (
    AnswerLimitPayload,
    ApplicationPayload,
    BankEditPayload,
    DocumentTextPayload,
    FilteredView,
    JobIdsPayload,
    JobView,
    ManualJobPayload,
    OnboardingPayload,
    ProfilePatch,
    QuestionPayload,
    SettingsPayload,
    SkillsPayload,
)

log = logging.getLogger(__name__)

TEMPLATES = Path(__file__).parent / "templates"
STATIC = Path(__file__).parent / "static"

#: Largest CV upload accepted. A CV is a few hundred KB; anything near this
#: is not a CV, and reading it would only fill the disk.
MAX_UPLOAD_BYTES = 10 * 1024 * 1024
#: Documents written as plain text (the CV is rendered to a file instead).
LETTER_KINDS = ("cover_letter", "email")


async def save_upload(upload: UploadFile, directory: Path) -> Path:
    """Store an uploaded CV under ``directory`` and return its path.

    Only the base name of the client's file name is used: a name such as
    ``../../.bashrc`` must not write outside the uploads folder.
    """
    name = Path((upload.filename or "").replace("\\", "/")).name.strip()
    if not name or name.startswith("."):
        raise ProfileError("The uploaded file has no usable name.",
                           hint="Rename the file (e.g. cv.pdf) and upload it again.")
    content = await upload.read(MAX_UPLOAD_BYTES + 1)
    if not content:
        raise ProfileError(f"{name} is empty.", hint="Upload the CV file itself.")
    if len(content) > MAX_UPLOAD_BYTES:
        raise ProfileError(f"{name} is larger than {MAX_UPLOAD_BYTES // (1024 * 1024)} MB.",
                           hint="Upload a smaller export of your CV (PDF or DOCX).")
    target = directory / name
    try:
        directory.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
    except OSError as exc:
        raise StorageError(f"Cannot save the upload: {describe_os_error(exc)}.",
                           hint="Check that the data directory is writable.") from exc
    return target


def _job_view(job: Job, score: MatchScore | None, application: Application,
              documents: dict, profile_years: float | None = None,
              families: dict[str, Family] | None = None) -> JobView:
    if families and not job.family:
        # Jobs stored before families existed are classified on the fly.
        job.family = classify_family(job, families)
    focus, focus_reason = focus_for(job, score, max_years=profile_years, families=families)
    salary = job.salary
    return JobView(
        id=job.id,
        title=job.title or "",
        company=job.company or "",
        location=job.location or "",
        work_mode=job.work_mode.value,
        remote_scope=job.remote_scope.value,
        source=job.source,
        url=job.link,
        language=job.language,
        posted_at=job.posted_at,
        salary_min=salary.minimum if salary else None,
        salary_max=salary.maximum if salary else None,
        salary_currency=salary.currency or "" if salary else "",
        salary_origin=salary.origin.value if salary and salary.origin else "",
        salary_basis=salary.basis or "" if salary else "",
        min_years_experience=job.min_years_experience,
        alerts=job.alerts or [],
        requirements=[f"{r.label} ({r.weight})" for r in sorted(job.requirements or [], key=lambda r: -r.weight)[:12]],
        score_base=score.base if score else 0.0,
        score_tailored=score.tailored if score else 0.0,
        score_delta=score.delta if score else 0.0,
        gaps=score.gaps if score else [],
        gap_details=score.gap_details if score else [],
        strengths=score.strengths if score else [],
        family=job.family,
        family_label=family_label(job.family, families or {}),
        focus=focus,
        focus_reason=focus_reason,
        status=application.status.value,
        stage=application.stage.value if application.stage else None,
        applied_on=application.applied_on,
        notes=application.notes,
        closed=job.closed,
        has_cv="cv" in documents,
        has_cover_letter="cover_letter" in documents,
        has_email="email" in documents,
    )


#: Host names the dashboard answers to unless told otherwise.
LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})
_UNSAFE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})


def _hostname(host_header: str) -> str:
    """``[::1]:8000`` -> ``::1``, ``localhost:8000`` -> ``localhost``."""
    value = (host_header or "").strip().lower()
    if value.startswith("["):
        return value[1:].split("]", 1)[0]
    return value.rsplit(":", 1)[0] if value.count(":") == 1 else value


def request_refusal(method: str, headers, allowed_hosts: frozenset[str] | None) -> str | None:
    """Why a request must be refused, or ``None``. Pure, so it is testable."""
    host = headers.get("host", "")
    if allowed_hosts is not None and _hostname(host) not in allowed_hosts:
        return "Host not allowed"
    if method.upper() not in _UNSAFE_METHODS:
        return None
    if (headers.get("sec-fetch-site") or "").lower() == "cross-site":
        return "Cross-site request refused"
    origin = headers.get("origin")
    if origin is not None:
        if origin == "null" or urlsplit(origin).netloc.lower() != host.lower():
            return "Cross-origin request refused"
    return None


def create_app(paths: Paths | None = None, allowed_hosts: Iterable[str] | None = LOOPBACK_HOSTS) -> FastAPI:
    """Build the application. ``paths`` is injectable so tests get a temp home.

    ``allowed_hosts`` are the host names accepted in the ``Host`` header;
    ``None`` disables that check (only sensible behind a proxy that does it).
    """
    load_dotenv()
    paths = (paths or Paths.resolve()).ensure()
    # One Database object for the whole app: it keeps one SQLite connection
    # per thread, so a search running in a worker thread cannot interleave
    # its transactions with the page's reads, and settings the CLI wrote are
    # immediately visible.
    database = Database(paths)

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        yield
        database.close()

    app = FastAPI(title="JobRadar", version=__version__, docs_url="/api/docs", lifespan=lifespan)
    hosts = None if allowed_hosts is None else frozenset(h.lower() for h in allowed_hosts)

    @app.exception_handler(JobRadarError)
    async def expected_error(request: Request, exc: JobRadarError):
        """A failure JobRadar knows how to explain: say what it is and what to do."""
        log.warning("%s %s failed: %s", request.method, request.url.path, exc.message)
        return JSONResponse(status_code=exc.status_code, content=exc.to_dict())

    @app.exception_handler(RequestValidationError)
    async def invalid_request(request: Request, exc: RequestValidationError):
        # FastAPI's default body is a list the page cannot show; keep it and
        # add a sentence that it can.
        parts = []
        for error in exc.errors()[:3]:
            location = ".".join(str(p) for p in error.get("loc", ()) if p != "body")
            parts.append(f"{location or 'request'}: {error.get('msg', 'invalid')}")
        return JSONResponse(status_code=422, content={
            "detail": "Invalid request — " + "; ".join(parts),
            "error": "ValidationError",
            "errors": jsonable_encoder(exc.errors()),
        })

    @app.exception_handler(ValidationError)
    async def invalid_payload(request: Request, exc: ValidationError):
        return JSONResponse(status_code=422, content={
            "detail": f"Invalid data — {validation_summary(exc)}",
            "error": "ValidationError",
        })

    @app.exception_handler(Exception)
    async def unexpected_error(request: Request, exc: Exception):
        """A bug. The traceback goes to the server log, never to the browser."""
        log.exception("Unexpected error on %s %s", request.method, request.url.path)
        return JSONResponse(status_code=500, content={
            "detail": "Something went wrong on the server. The details are in the "
                      "terminal running 'jobradar serve'.",
            "error": "InternalError",
        })

    @app.middleware("http")
    async def refuse_foreign_requests(request: Request, call_next):
        refusal = request_refusal(request.method, request.headers, hosts)
        if refusal:
            return JSONResponse({"detail": refusal}, status_code=403)
        return await call_next(request)

    templates = Jinja2Templates(directory=str(TEMPLATES))
    if STATIC.exists():
        app.mount("/static", StaticFiles(directory=str(STATIC)), name="static")

    app.state.database = database
    app.state.paths = paths
    app.state.running = {"search": False, "sweep": False}
    app.state.last_run = None

    # -- helpers ----------------------------------------------------------

    def require_profile() -> Profile:
        profile = database.load_profile()
        if profile is None:
            raise HTTPException(status_code=409, detail="No profile yet — finish the setup first.")
        return profile

    def job_or_404(job_id: str) -> Job:
        job = database.get_job(job_id)
        if job is None:
            raise HTTPException(status_code=404,
                                detail="That job is not on the board any more; reload the page.")
        return job

    def score_for(job: Job, profile: Profile) -> MatchScore:
        score = database.get_score(job.id)
        if score is None:
            score = score_job(job, profile)
            database.save_score(job.id, score)
        return score

    # -- page -------------------------------------------------------------

    @app.get("/", response_class=HTMLResponse)
    def index(request: Request):
        settings = database.load_settings()
        return templates.TemplateResponse(
            request=request,
            name="dashboard.html",
            context={"onboarded": settings.onboarded, "version": __version__},
        )

    # -- state ------------------------------------------------------------

    @app.get("/api/state")
    def state(
        limit: int = Query(500, ge=1, le=5000, description="Max jobs to load"),
        offset: int = Query(0, ge=0),
    ):
        """Everything the page needs in one request.

        ``limit`` protects browser memory once the database grows large: the
        most recently seen jobs are loaded first.
        """
        settings = database.load_settings()
        profile = database.load_profile()
        scores = database.all_scores()
        applications = database.all_applications()
        families = families_for(settings)
        profile_years = profile.years_of_experience() if profile else None
        jobs = []
        for job in database.list_jobs(include_closed=True, limit=limit, offset=offset):
            application = applications.get(job.id) or Application(job_id=job.id)
            documents = database.documents_for(job.id)
            jobs.append(
                _job_view(job, scores.get(job.id), application, documents, profile_years,
                          families)
                .model_dump(mode="json")
            )
        # Focus order by default: once a profile covers most of what the ads
        # ask for, sorting by match score is sorting by noise.
        jobs.sort(key=lambda item: (-item["focus"], -item["score_tailored"], item["company"]))

        runs = [run.model_dump(mode="json") for run in database.recent_runs(5)]
        return {
            "onboarded": settings.onboarded,
            "settings": settings.model_dump(mode="json"),
            "profile": _profile_summary(profile),
            "jobs": jobs,
            "sources": available_sources(),
            "families": catalogue_view(settings),
            "mail": {job_id: news.model_dump(mode="json")
                     for job_id, news in database.mail_news().items()},
            "mail_orphans": [news.model_dump(mode="json") for news in database.mail_orphans()],
            "mail_configured": mail_configured(),
            "countries": {code: entry.get("name", code) for code, entry in countries().items()},
            "runs": runs,
            "filtered": [FilteredView(**entry, family_label=family_label(entry.get("family", ""),
                                                                          families)
                                      if entry.get("family") else "").model_dump(mode="json")
                         for entry in database.list_filtered()],
            # For the "just short on years" table, recomputed live so a
            # change of margin shows at once.
            "experience": {"held": experience_ceiling(settings.filters, profile_years),
                           "margin": settings.filters.years_margin},
            "filtered_tally": database.filtered_tally(),
            "running": app.state.running,
            "version": __version__,
        }

    def _profile_summary(profile: Profile | None) -> dict | None:
        if profile is None:
            return None
        lint = lint_profile(profile)
        return {
            "full_name": profile.contact.full_name,
            "email": profile.contact.email,
            "summary": profile.summary,
            "experience": [
                {
                    "id": experience.id,
                    "organization": experience.organization,
                    "title": localized(experience.title, profile.default_language),
                    "start": experience.start,
                    "end": experience.end,
                    "bullets": [{"id": b.id, "text": localized(b.text, profile.default_language)}
                                for b in experience.bullets],
                }
                for experience in profile.experience
            ],
            "skills": [
                {"key": key, "label": profile.label_for(key),
                 "evidence": value, "ceiling": profile.ceiling.get(key, value),
                 "custom": key in profile.custom_skills,
                 "aliases": profile.custom_skills.get(key, [])}
                for key, value in sorted(profile.evidence.items(),
                                         key=lambda item: (-item[1], profile.label_for(item[0])))
            ],
            "skill_groups": [
                {"key": group.key, "label": localized(group.label, profile.default_language),
                 "items": group.items}
                for group in profile.skills
            ],
            "family_variants": {family: variant.model_dump(mode="json")
                                for family, variant in profile.family_variants.items()},
            "years": profile.years_of_experience(),
            "lint": {
                "score": lint.score(),
                "summary": lint.summary(),
                "findings": [f.model_dump(mode="json") for f in lint.findings],
            },
        }

    # -- onboarding -------------------------------------------------------

    @app.post("/api/onboarding")
    async def onboarding(
        payload: str = Form(...),
        cv_file: UploadFile | None = File(default=None),
    ):
        """Create the profile and settings from the first-run wizard.

        Runs once; afterwards the same values are edited through
        ``/api/settings`` and ``/api/profile``.
        """
        data = OnboardingPayload.model_validate_json(payload)
        settings = database.load_settings()
        settings.full_name = data.full_name
        settings.email = data.email
        settings.country = data.country.upper()
        settings.default_language = data.default_language
        settings.cv_template = data.cv_template
        settings.search.titles = [t for t in data.titles if t.strip()]
        settings.search.keywords = [k for k in data.keywords if k.strip()]
        settings.filters = data.filters
        settings.filters.home_country = settings.country
        settings.sources.company_domains = data.company_domains
        if data.enabled_sources:
            settings.sources.enabled = data.enabled_sources

        notes: list[str] = []
        source: str | Path | None = None
        if cv_file is not None and cv_file.filename:
            source = await save_upload(cv_file, paths.uploads_dir)
        elif data.cv_text.strip():
            source = data.cv_text

        if source is not None:
            llm = build_client(settings.llm)
            try:
                profile, notes = import_profile(source, llm)
            finally:
                if llm:
                    llm.close()
        else:
            from ..profile import profile_from_form

            profile = profile_from_form(
                {"full_name": data.full_name, "email": data.email, "country": data.country},
                data.default_language,
            )
            notes = ["No CV was provided — add your experience and achievements before generating documents."]

        if not profile.contact.full_name:
            profile.contact.full_name = data.full_name
        if not profile.contact.email:
            profile.contact.email = data.email

        settings.onboarded = True
        database.save_profile(profile)
        database.save_settings(settings)
        return {"ok": True, "notes": notes, "profile": _profile_summary(profile)}

    # -- settings and profile ---------------------------------------------

    @app.put("/api/settings")
    def update_settings(payload: SettingsPayload):
        settings = payload.settings
        settings.onboarded = True
        settings.filters.home_country = settings.country
        database.save_settings(settings)
        return {"ok": True, "settings": settings.model_dump(mode="json"),
                "restored": restore_now_in_reach(settings)}

    def restore_now_in_reach(settings) -> int:
        """Put back ads set aside for years that the new settings now allow.

        Raising the years (or the ceiling rising with the CV's dates) should
        bring those ads back at once, not on the next search.
        """
        profile = database.load_profile()
        years = profile.years_of_experience() if profile else None
        restored = 0
        for entry in database.list_filtered():
            if entry["category"] != "experience":
                continue
            job = database.get_filtered_job(entry["id"])
            if job is not None and check_experience(job, settings.filters, years) is None:
                database.restore_filtered(job.id)
                restored += 1
        return restored

    @app.put("/api/profile")
    def update_profile(patch: ProfilePatch):
        """Edit the parts of the profile that change how documents come out."""
        profile = require_profile()
        if patch.summary is not None:
            profile.summary = {profile.default_language: patch.summary}
        if patch.evidence is not None:
            profile.evidence.update({k: max(0.0, min(1.0, v)) for k, v in patch.evidence.items()})
        if patch.ceiling is not None:
            if profile.ceiling is None:
                profile.ceiling = {}
            for key, value in patch.ceiling.items():
                base = profile.evidence.get(key, 0.0)
                if base > 0.0:  # a skill with no evidence can never gain a ceiling
                    profile.ceiling[key] = max(base, min(1.0, value))
        if patch.family_variants is not None:
            profile.family_variants = {
                family: variant for family, variant in patch.family_variants.items()
                if variant != CvVariant()  # an untouched variant is no variant
            }
        database.save_profile(profile)
        return {"ok": True, "profile": _profile_summary(profile)}

    @app.put("/api/profile/skills")
    def update_skills(payload: SkillsPayload):
        """Add, edit and delete skills; the listed groups, evidence and ceilings."""
        profile = require_profile()
        language = profile.default_language
        groups = [
            SkillGroup(key=group.key or slugify(group.label, 20) or f"group{index}",
                       label={language: group.label.strip()},
                       items=[item.strip() for item in group.items if item.strip()])
            for index, group in enumerate(payload.groups)
        ]
        rows = [SkillEdit(name=row.name, evidence=row.evidence, ceiling=row.ceiling,
                          key=row.key, aliases=tuple(row.aliases)) for row in payload.skills]
        apply_skill_edits(profile, groups, rows, payload.deleted)
        database.save_profile(profile)
        return {"ok": True, "profile": _profile_summary(profile)}

    @app.post("/api/profile/reimport")
    async def reimport(cv_file: UploadFile = File(...)):
        """Replace the profile from a new CV file."""
        if not cv_file.filename:
            raise HTTPException(status_code=400,
                                detail="No file was attached; choose your CV file first.")
        settings = database.load_settings()
        target = await save_upload(cv_file, paths.uploads_dir)
        llm = build_client(settings.llm)
        try:
            profile, notes = import_profile(target, llm)
        finally:
            if llm:
                llm.close()
        previous = database.load_profile()
        if previous is not None:
            carry_over(previous, profile)
        database.save_profile(profile)
        return {"ok": True, "notes": notes, "profile": _profile_summary(profile)}

    # -- tracking ---------------------------------------------------------

    @app.put("/api/jobs/{job_id}/application")
    def update_application(job_id: str, payload: ApplicationPayload):
        job_or_404(job_id)
        database.save_application(
            Application(
                job_id=job_id,
                status=payload.status,
                stage=payload.stage,
                applied_on=payload.applied_on,
                notes=payload.notes,
                updated_at=datetime.now(timezone.utc),
            )
        )
        return {"ok": True}

    # -- adding and deleting jobs by hand -------------------------------------

    @app.post("/api/jobs")
    def add_job(payload: ManualJobPayload):
        """Put a job the user found elsewhere on the board, read like any other."""
        settings = database.load_settings()
        key = payload.url.strip() or f"{payload.company}|{payload.title}|{payload.description[:200]}"
        job = Job(
            source="manual",
            native_id=hashlib.sha1(key.strip().lower().encode("utf-8")).hexdigest()[:12],
            title=payload.title.strip(),
            company=payload.company.strip(),
            url=payload.url.strip(),
            location=payload.location.strip(),
            work_mode=payload.work_mode,
            description=payload.description.strip(),
            posted_at=date.today(),
        )
        job.ensure_id()
        if payload.salary_min or payload.salary_max:
            job.salary = Salary(minimum=payload.salary_min or payload.salary_max,
                                maximum=payload.salary_max or payload.salary_min,
                                currency=payload.salary_currency.upper() or "EUR",
                                origin=SalaryOrigin.PUBLISHED, basis="typed in by you")
        if payload.family:
            if payload.family not in families_for(settings):
                raise HTTPException(
                    status_code=400,
                    detail=f"Unknown job family '{payload.family}'. Pick one from the list, or "
                           "add it in Settings → Job families.")
            job.family = payload.family
            job.raw["family_set_by_user"] = True
        llm = build_client(settings.llm)
        try:
            enrich_job(job, settings, llm=llm, rates=ExchangeRates.load(paths.cache_dir))
        finally:
            if llm:
                llm.close()
        database.restore_deleted([job.id])  # adding it again undoes an earlier deletion
        database.upsert_jobs([job])
        profile = database.load_profile()
        if profile is not None:
            database.save_score(job.id, score_job(job, profile))
        if payload.status != ApplicationStatus.ACTIVE or payload.notes or payload.stage:
            database.save_application(Application(
                job_id=job.id, status=payload.status, stage=payload.stage,
                applied_on=payload.applied_on or (date.today() if payload.status ==
                                                  ApplicationStatus.APPLIED else None),
                notes=payload.notes, updated_at=datetime.now(timezone.utc)))
        return {"ok": True, "id": job.id, "family": job.family}

    @app.post("/api/jobs/delete")
    def delete_jobs(payload: JobIdsPayload):
        """Take jobs off the board for good (they can be brought back for a week)."""
        deleted = database.delete_jobs(payload.ids)
        return {"ok": True, "deleted": deleted, "undo_days": database.UNDO_DAYS}

    @app.post("/api/jobs/undelete")
    def undelete_jobs(payload: JobIdsPayload):
        restored = database.restore_deleted(payload.ids)
        return {"ok": True, "restored": restored}

    # -- documents --------------------------------------------------------

    @app.post("/api/jobs/{job_id}/cv")
    def build_cv(job_id: str):
        """Tailor and render the CV for one job, and lint the result."""
        job = job_or_404(job_id)
        profile = require_profile()
        settings = database.load_settings()
        llm = build_client(settings.llm)
        try:
            score = score_for(job, profile)
            tailored = tailor(profile, job, score, settings, llm)
            result = render_cv(profile, tailored, job, paths, settings)
        finally:
            if llm:
                llm.close()

        database.save_document(
            GeneratedDocument(
                job_id=job_id,
                kind="cv",
                language=tailored.language,
                path=str(result.pdf_path or result.html_path),
                generated_at=datetime.now(timezone.utc),
                llm_generated=tailored.generated_by == "llm",
            )
        )
        lint = lint_tailored(profile, tailored, result.pages, settings.cv_max_pages)
        return {
            "ok": True,
            "headline": tailored.headline,
            "summary": tailored.summary,
            "generated_by": tailored.generated_by,
            "pages": result.pages,
            "scale": result.scale,
            "warnings": result.warnings,
            "validation_notes": tailored.validation_notes,
            "lint": {
                "score": lint.score(),
                "summary": lint.summary(),
                "findings": [f.model_dump(mode="json") for f in lint.findings],
            },
        }

    @app.get("/api/jobs/{job_id}/cv/download")
    def download_cv(job_id: str):
        document = database.get_document(job_id, "cv")
        if not document or not document.path:
            raise HTTPException(
                status_code=404,
                detail="No CV has been generated for this job yet; press Tailor CV first.")
        path = Path(document.path)
        if not path.is_file():
            raise HTTPException(status_code=404,
                                detail="The CV file is gone from disk — generate it again")
        return FileResponse(path, filename=path.name)

    @app.post("/api/jobs/{job_id}/documents/{kind}")
    def build_letter(job_id: str, kind: str):
        """Write the cover letter or the application email for one job."""
        if kind not in LETTER_KINDS:
            raise HTTPException(status_code=400,
                                detail=f"Unknown document type '{kind}'; use cover_letter or email.")
        job = job_or_404(job_id)
        profile = require_profile()
        settings = database.load_settings()
        llm = build_client(settings.llm)
        try:
            score = score_for(job, profile)
            builder = generate_cover_letter if kind == "cover_letter" else generate_email
            document = builder(profile, job, score, settings, llm)
        finally:
            if llm:
                llm.close()
        database.save_document(document)
        return {"ok": True, "document": document_view(document, job)}

    def letter_or_404(job_id: str, kind: str) -> GeneratedDocument:
        if kind not in LETTER_KINDS:
            raise HTTPException(status_code=400,
                                detail=f"Unknown document type '{kind}'; use cover_letter or email.")
        document = database.get_document(job_id, kind)
        if not document:
            raise HTTPException(
                status_code=404,
                detail="That document has not been written yet; press Cover letter or "
                       "Application email first.")
        return document

    @app.put("/api/jobs/{job_id}/documents/{kind}")
    def save_letter(job_id: str, kind: str, payload: DocumentTextPayload):
        """Keep the user's edits to a cover letter or email."""
        job_or_404(job_id)
        document = letter_or_404(job_id, kind)
        document.text = payload.text.strip()
        database.save_document(document)
        return {"ok": True, "document": document_view(document, database.get_job(job_id))}

    @app.get("/api/jobs/{job_id}/documents/{kind}/pdf")
    def download_letter(job_id: str, kind: str):
        """The saved letter or email as a PDF, built without a browser."""
        job = job_or_404(job_id)
        document = letter_or_404(job_id, kind)
        profile = require_profile()
        language = document.language
        pdf = letter_pdf(
            sender=profile.contact.name_for(language),
            contact_line=contact_line(profile, language),
            recipient=job.company,
            kind=kind,
            language=language,
            date_text=date.today().isoformat(),
            body=document.text,
        )
        name = f"{kind.replace('_', '-')}-{slugify(job.company or job.title)}.pdf"
        return Response(pdf, media_type="application/pdf",
                        headers={"Content-Disposition": f'attachment; filename="{name}"'})

    @app.get("/api/jobs/{job_id}/documents")
    def list_documents(job_id: str):
        """Saved documents, letters re-checked so older drafts get today's warnings."""
        job = database.get_job(job_id)
        return {kind: document_view(document, job)
                for kind, document in database.documents_for(job_id).items()}

    def document_view(document: GeneratedDocument, job: Job | None) -> dict:
        view = document.model_dump(mode="json")
        profile = database.load_profile()
        if document.kind in LETTER_KINDS and profile is not None:
            view["warnings"] = [f.model_dump(mode="json") for f in review_text(
                document.text, profile, job, document.kind,
                extra_phrases=database.load_settings().banned_phrases)]
        return view

    # -- form answers and the answer bank ------------------------------------

    def thread_view(job: Job, thread: AnswerThread) -> dict:
        """The thread with each answer's length, warnings and bank status."""
        profile = require_profile()
        banned = database.load_settings().banned_phrases
        banked = {entry.answer for entry in database.answer_bank()}
        messages = []
        for message in thread.messages:
            view = message.model_dump(mode="json")
            if message.role == "answer":
                view["length"] = measure(message.text, thread.unit)
                view["in_bank"] = message.text in banked
                view["warnings"] = [f.model_dump(mode="json") for f in review_text(
                    message.text, profile, job, "answer", extra_phrases=banned,
                    limit=thread.limit, unit=thread.unit)]
            messages.append(view)
        return {"limit": thread.limit, "unit": thread.unit.value, "messages": messages}

    def answer_index_or_404(thread: AnswerThread, index: int) -> None:
        if not 0 <= index < len(thread.messages) or thread.messages[index].role != "answer":
            raise HTTPException(
                status_code=404,
                detail="There is no answer at that position in this job's thread; reload it.")

    @app.get("/api/jobs/{job_id}/answers")
    def get_answers(job_id: str):
        job = job_or_404(job_id)
        return thread_view(job, database.answer_thread(job_id))

    @app.post("/api/jobs/{job_id}/answers")
    def ask(job_id: str, payload: QuestionPayload):
        """Answer a form question (or refine the last answer) in the job's thread."""
        job = job_or_404(job_id)
        profile = require_profile()
        settings = database.load_settings()
        thread = database.answer_thread(job_id)
        llm = build_client(settings.llm)
        try:
            text, by_model, precedents = answer(profile, job, thread, payload.question.strip(),
                                                database.answer_bank(), settings, llm)
        finally:
            if llm:
                llm.close()
        add_turn(thread, "question", payload.question.strip())
        add_turn(thread, "answer", text)
        database.save_answer_thread(thread)
        view = thread_view(job, thread)
        view["llm_generated"] = by_model
        view["precedents"] = [{"question": p.entry.question, "company": p.entry.company}
                              for p in precedents]
        return view

    @app.put("/api/jobs/{job_id}/answers/limit")
    def set_answer_limit(job_id: str, payload: AnswerLimitPayload):
        job = job_or_404(job_id)
        thread = database.answer_thread(job_id)
        thread.limit, thread.unit = payload.limit, payload.unit
        database.save_answer_thread(thread)
        return thread_view(job, thread)

    @app.put("/api/jobs/{job_id}/answers/{index}")
    def edit_answer(job_id: str, index: int, payload: DocumentTextPayload):
        """Keep a hand edit to one answer. The bank keeps its own copy."""
        job = job_or_404(job_id)
        thread = database.answer_thread(job_id)
        answer_index_or_404(thread, index)
        if not payload.text.strip():
            raise HTTPException(status_code=400,
                                detail="An answer cannot be empty; write something or delete the "
                                       "thread.")
        message = thread.messages[index]
        message.text, message.edited_at = payload.text.strip(), datetime.now(timezone.utc)
        database.save_answer_thread(thread)
        return thread_view(job, thread)

    @app.delete("/api/jobs/{job_id}/answers")
    def clear_answers(job_id: str):
        job_or_404(job_id)
        database.delete_answer_thread(job_id)
        return {"ok": True}

    @app.post("/api/jobs/{job_id}/answers/{index}/bank")
    def bank_answer(job_id: str, index: int):
        """Save one answer, with the question it replies to, in the answer bank."""
        job = job_or_404(job_id)
        thread = database.answer_thread(job_id)
        answer_index_or_404(thread, index)
        entry = to_bank(thread, index, job, job.language or database.load_settings().default_language)
        bank = [e for e in database.answer_bank() if e.id != entry.id]
        database.save_answer_bank([entry, *bank])
        return {"ok": True, "entry": entry.model_dump(mode="json")}

    @app.get("/api/answer-bank")
    def get_bank():
        return {"entries": [e.model_dump(mode="json") for e in database.answer_bank()]}

    @app.put("/api/answer-bank/{entry_id}")
    def edit_bank(entry_id: str, payload: BankEditPayload):
        bank = database.answer_bank()
        entry = next((e for e in bank if e.id == entry_id), None)
        if entry is None:
            raise HTTPException(
                status_code=404,
                detail="That answer is no longer in the bank; reload the page.")
        # The id stays, even if the question is reworded, so it is still the same entry.
        entry.question, entry.answer = payload.question.strip(), payload.answer.strip()
        entry.edited_at = datetime.now(timezone.utc)
        database.save_answer_bank(bank)
        return {"ok": True, "entry": entry.model_dump(mode="json")}

    @app.delete("/api/answer-bank/{entry_id}")
    def delete_bank(entry_id: str):
        bank = database.answer_bank()
        remaining = [e for e in bank if e.id != entry_id]
        if len(remaining) == len(bank):
            raise HTTPException(
                status_code=404,
                detail="That answer is no longer in the bank; reload the page.")
        database.save_answer_bank(remaining)
        return {"ok": True}

    # -- pipeline ---------------------------------------------------------

    @app.post("/api/search")
    async def search():
        """Run a full search. Long, so it runs in a worker thread."""
        if app.state.running["search"]:
            return JSONResponse({"ok": False, "detail": "A search is already running"}, status_code=409)
        settings = database.load_settings()
        if not settings.onboarded:
            raise HTTPException(status_code=409, detail="Finish the setup first")

        app.state.running["search"] = True

        def work():
            try:
                return run_search(settings=settings, paths=paths, database=database)
            finally:
                app.state.running["search"] = False

        result = await asyncio.to_thread(work)
        app.state.last_run = result.run.model_dump(mode="json")
        return {
            "ok": True,
            "run": app.state.last_run,
            "new": [f"{job.company} — {job.title}" for job in result.new_jobs][:50],
            "rejected": len(result.rejected),
        }

    @app.get("/api/insights")
    def insights(runs: int = Query(30, ge=1, le=365)):
        """The application funnel and the run history, for the Insights tab."""
        settings = database.load_settings()
        report = funnel(database.list_jobs(include_closed=True), database.all_applications(),
                        database.all_scores(), database.mail_news(), families_for(settings))
        return {"funnel": report.as_dict(), "history": history(database.recent_runs(runs))}

    @app.post("/api/mail/check")
    async def mail_check():
        """Read new replies from the inbox. Read-only on the mail server."""
        settings = database.load_settings()
        report = await asyncio.to_thread(check_mail, database, settings)
        return {"ok": True, "summary": report.summary(), "replies": len(report.news),
                "orphans": len(report.orphans)}

    @app.get("/api/jobs/{job_id}/interview.ics")
    def interview_calendar(job_id: str):
        """A calendar event for an interview proposed by email, to import by hand."""
        news = database.mail_news().get(job_id)
        if news is None or news.interview_at is None:
            raise HTTPException(status_code=404, detail="No interview time was found for this job")
        body = interview_ics(news, database.get_job(job_id))
        return Response(body, media_type="text/calendar",
                        headers={"Content-Disposition": 'attachment; filename="interview.ics"'})

    @app.post("/api/sweep")
    async def sweep():
        """Check the active jobs and retire the ads that have closed."""
        if app.state.running["sweep"]:
            return JSONResponse({"ok": False, "detail": "A sweep is already running"}, status_code=409)
        app.state.running["sweep"] = True

        def work():
            try:
                return sweep_closed(database)
            finally:
                app.state.running["sweep"] = False

        report = await asyncio.to_thread(work)
        return {
            "ok": True,
            "summary": report.summary(),
            "closed": [{"id": i, "job": j, "reason": r} for i, j, r in report.closed],
        }

    @app.post("/api/filtered/{job_id}/restore")
    def restore_filtered(job_id: str):
        """Put a rejected ad back on the board.

        The filter that rejected it is still there and a later run would reject
        it again — that is fine. What changes is that the decision is the
        user's and visible, instead of a drop nobody could see.
        """
        job = database.restore_filtered(job_id)
        if job is None:
            raise HTTPException(
                status_code=404,
                detail="That ad is no longer in the filtered list; reload the page.")
        profile = database.load_profile()
        if profile is not None:
            database.save_score(job.id, score_job(job, profile))
        return {"ok": True, "id": job.id, "title": job.title, "company": job.company}

    @app.delete("/api/filtered")
    def clear_filtered():
        """Empty the filtered list. The ads come back on the next search."""
        database.clear_filtered()
        return {"ok": True}

    @app.get("/api/rates")
    def rates():
        exchange = ExchangeRates.load(paths.cache_dir)
        return {"as_of": exchange.as_of, "currencies": sorted(exchange.rates)}

    return app


def serve(host: str = "127.0.0.1", port: int = 8000, paths: Paths | None = None,
          reload: bool = False) -> None:
    """Run the dashboard with uvicorn."""
    import os

    import uvicorn

    extra = {h.strip() for h in os.environ.get("JOBRADAR_ALLOWED_HOSTS", "").split(",") if h.strip()}
    if host in ("0.0.0.0", "::") and not extra:
        # Listening on every interface: the names it will be reached by are
        # unknown here, so the Host check is off and the Origin check remains.
        # Set JOBRADAR_ALLOWED_HOSTS to turn it back on.
        allowed: Iterable[str] | None = None
    else:
        allowed = LOOPBACK_HOSTS | {host.lower()} | extra
    uvicorn.run(create_app(paths, allowed_hosts=allowed), host=host, port=port, reload=reload,
                log_level="info")
