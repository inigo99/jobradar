"""The dashboard server.

Routes are thin: every one of them loads state from SQLite, calls into the
pipeline or the documents package, and returns JSON. All the behaviour lives in
those packages, which is what makes the same operations available from the CLI.

The server binds to ``127.0.0.1`` by default. The database contains the user's
CV, contact details and job-search history; putting that on a public interface
would be a poor default, so exposing it takes an explicit ``--host``.
"""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.requests import Request

from .. import __version__
from ..config import Paths, countries, load_dotenv
from ..documents import generate_cover_letter, generate_email, render_cv, tailor
from ..lint import lint_profile, lint_tailored
from ..llm import build_client
from ..models import Application, Job, MatchScore, Profile
from ..pipeline import run_search, sweep_closed
from ..pipeline.focus import focus_for
from ..pipeline.salary import ExchangeRates
from ..pipeline.scoring import score_job
from ..profile import import_profile
from ..sources import available as available_sources
from ..storage import Database
from .api import (
    ApplicationPayload,
    FilteredView,
    JobView,
    OnboardingPayload,
    ProfilePatch,
    SettingsPayload,
)

log = logging.getLogger(__name__)

TEMPLATES = Path(__file__).parent / "templates"
STATIC = Path(__file__).parent / "static"


def _job_view(job: Job, score: MatchScore | None, application: Application,
              documents: dict, profile_years: float | None = None) -> JobView:
    focus, focus_reason = focus_for(job, score, max_years=profile_years)
    return JobView(
        id=job.id,
        title=job.title,
        company=job.company,
        location=job.location,
        work_mode=job.work_mode.value,
        remote_scope=job.remote_scope.value,
        source=job.source,
        url=job.link,
        language=job.language,
        posted_at=job.posted_at,
        salary_min=job.salary.minimum,
        salary_max=job.salary.maximum,
        salary_currency=job.salary.currency,
        salary_origin=job.salary.origin.value,
        salary_basis=job.salary.basis,
        min_years_experience=job.min_years_experience,
        alerts=job.alerts,
        requirements=[f"{r.label} ({r.weight})" for r in sorted(job.requirements, key=lambda r: -r.weight)[:12]],
        score_base=score.base if score else 0.0,
        score_tailored=score.tailored if score else 0.0,
        score_delta=score.delta if score else 0.0,
        gaps=score.gaps if score else [],
        gap_details=score.gap_details if score else [],
        strengths=score.strengths if score else [],
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


def create_app(paths: Paths | None = None) -> FastAPI:
    """Build the application. ``paths`` is injectable so tests get a temp home."""
    load_dotenv()
    paths = (paths or Paths.resolve()).ensure()
    # A single connection is reused: SQLite handles this fine for one local
    # user, and it keeps the settings the CLI wrote immediately visible.
    database = Database(paths)

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        yield
        database.close()

    app = FastAPI(title="JobRadar", version=__version__, docs_url="/api/docs", lifespan=lifespan)
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
            raise HTTPException(status_code=404, detail="Unknown job")
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
    def state():
        """Everything the page needs in one request."""
        settings = database.load_settings()
        profile = database.load_profile()
        scores = database.all_scores()
        applications = database.all_applications()
        profile_years = profile.years_of_experience() if profile else None
        jobs = []
        for job in database.list_jobs(include_closed=True):
            application = applications.get(job.id) or Application(job_id=job.id)
            documents = database.documents_for(job.id)
            jobs.append(
                _job_view(job, scores.get(job.id), application, documents, profile_years)
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
            "countries": {code: entry.get("name", code) for code, entry in countries().items()},
            "runs": runs,
            "filtered": [FilteredView(**entry).model_dump(mode="json")
                         for entry in database.list_filtered()],
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
                    "title": experience.title,
                    "start": experience.start,
                    "end": experience.end,
                    "bullets": [{"id": b.id, "text": b.text} for b in experience.bullets],
                }
                for experience in profile.experience
            ],
            "skills": [
                {"key": key, "label": profile.label_for(key),
                 "evidence": value, "ceiling": profile.ceiling.get(key, value)}
                for key, value in sorted(profile.evidence.items(), key=lambda item: -item[1])
            ],
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
            target = paths.uploads_dir / cv_file.filename
            target.write_bytes(await cv_file.read())
            source = target
        elif data.cv_text.strip():
            source = data.cv_text

        if source is not None:
            llm = build_client(settings.llm)
            try:
                profile, notes = import_profile(source, llm)
            except RuntimeError as exc:  # a missing optional parser
                raise HTTPException(status_code=400, detail=str(exc)) from exc
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
        return {"ok": True, "settings": settings.model_dump(mode="json")}

    @app.put("/api/profile")
    def update_profile(patch: ProfilePatch):
        """Edit the parts of the profile that change how documents come out."""
        profile = require_profile()
        if patch.summary is not None:
            profile.summary = {profile.default_language: patch.summary}
        if patch.evidence is not None:
            profile.evidence.update({k: max(0.0, min(1.0, v)) for k, v in patch.evidence.items()})
        if patch.ceiling is not None:
            for key, value in patch.ceiling.items():
                base = profile.evidence.get(key, 0.0)
                if base > 0.0:  # a skill with no evidence can never gain a ceiling
                    profile.ceiling[key] = max(base, min(1.0, value))
        database.save_profile(profile)
        return {"ok": True, "profile": _profile_summary(profile)}

    @app.post("/api/profile/reimport")
    async def reimport(cv_file: UploadFile = File(...)):
        """Replace the profile from a new CV file."""
        settings = database.load_settings()
        target = paths.uploads_dir / cv_file.filename
        target.write_bytes(await cv_file.read())
        llm = build_client(settings.llm)
        try:
            profile, notes = import_profile(target, llm)
        finally:
            if llm:
                llm.close()
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

        from ..models import GeneratedDocument

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
        if not document or not document.path or not Path(document.path).exists():
            raise HTTPException(status_code=404, detail="Generate the CV first")
        path = Path(document.path)
        return FileResponse(path, filename=path.name)

    @app.post("/api/jobs/{job_id}/documents/{kind}")
    def build_letter(job_id: str, kind: str):
        """Write the cover letter or the application email for one job."""
        if kind not in ("cover_letter", "email"):
            raise HTTPException(status_code=400, detail="Unknown document type")
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
        return {"ok": True, "document": document.model_dump(mode="json")}

    @app.get("/api/jobs/{job_id}/documents")
    def list_documents(job_id: str):
        return {
            kind: document.model_dump(mode="json")
            for kind, document in database.documents_for(job_id).items()
        }

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
            raise HTTPException(status_code=404, detail="Not in the filtered list")
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
    import uvicorn

    uvicorn.run(create_app(paths), host=host, port=port, reload=reload, log_level="info")
