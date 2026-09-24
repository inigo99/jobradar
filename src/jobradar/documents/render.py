"""Rendering the tailored CV to HTML and PDF.

Three constraints shape everything here, in order of importance.

**It has to survive an ATS.** Roughly every applicant tracking system parses a
PDF by pulling out its text layer. Two-column layouts interleave, tables come
out scrambled, text inside images is invisible, and icons become question marks.
So every template is a single column of real text, in a standard font, with no
tables, no graphics and nothing in the page margins.

**It has to fit the page.** A CV that runs to 1.1 pages reads as carelessness.
Rather than truncating the candidate's content, the renderer shrinks type and
leading in small steps until it fits, and only reports a problem if it cannot.

**It has to look like the CV the user already had.** Not pixel-identical — that
is not achievable from an arbitrary PDF — but recognisably the same document:
same section order, same density, same restraint.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape
from jinja2.exceptions import TemplateError, TemplateNotFound

from ..config import Paths, Settings
from ..errors import RenderError, describe_os_error
from ..models import Job, Profile, localized
from ..textutils import slugify
from .tailor import TailoredCV

log = logging.getLogger(__name__)

TEMPLATE_DIR = Path(__file__).parent / "templates"

#: A4 at 96 dpi, less the print margins the templates declare.
PAGE_HEIGHT_PX = 1123
PAGE_MARGIN_PX = 2 * 34

#: Type scales tried in order until the CV fits. Below the last one the CV
#: stops being comfortable to read, and the honest answer is "cut something".
SCALES: tuple[float, ...] = (1.0, 0.97, 0.94, 0.91, 0.88, 0.85, 0.82, 0.79)

SECTION_LABELS: dict[str, dict[str, str]] = {
    "summary": {"en": "Professional summary", "es": "Resumen profesional",
                "fr": "Profil professionnel", "de": "Profil", "pt": "Resumo profissional",
                "it": "Profilo professionale"},
    "experience": {"en": "Professional experience", "es": "Experiencia profesional",
                   "fr": "Expérience professionnelle", "de": "Berufserfahrung",
                   "pt": "Experiência profissional", "it": "Esperienza professionale"},
    "education": {"en": "Education", "es": "Formación académica", "fr": "Formation",
                  "de": "Ausbildung", "pt": "Formação", "it": "Formazione"},
    "certifications": {"en": "Additional training", "es": "Formación complementaria",
                       "fr": "Formations complémentaires", "de": "Weiterbildung",
                       "pt": "Formação complementar", "it": "Formazione aggiuntiva"},
    "skills": {"en": "Technical skills", "es": "Competencias técnicas",
               "fr": "Compétences techniques", "de": "Kenntnisse",
               "pt": "Competências técnicas", "it": "Competenze tecniche"},
    "languages": {"en": "Languages", "es": "Idiomas", "fr": "Langues", "de": "Sprachen",
                  "pt": "Idiomas", "it": "Lingue"},
    "present": {"en": "present", "es": "actualidad", "fr": "aujourd'hui", "de": "heute",
                "pt": "atualidade", "it": "presente"},
}

MONTHS: dict[str, tuple[str, ...]] = {
    "en": ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"),
    "es": ("ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic"),
}


@dataclass
class RenderResult:
    """Where the CV ended up and how well it fitted."""

    html_path: Path
    pdf_path: Path | None
    pages: int | None
    scale: float
    fitted: bool
    warnings: list[str]


def label(section: str, language: str) -> str:
    options = SECTION_LABELS.get(section, {})
    return options.get(language) or options.get("en", section.title())


def format_period(start: str, end: str | None, language: str) -> str:
    """Human date range, in the CV's language, from ``YYYY-MM`` values."""

    def one(value: str) -> str:
        if not value:
            return ""
        parts = value.split("-")
        year = parts[0]
        if len(parts) < 2:
            return year
        try:
            month_index = int(parts[1]) - 1
            if month_index < 0:
                raise ValueError("month 00 does not exist")
            month = MONTHS.get(language, MONTHS["en"])[month_index]
        except (ValueError, IndexError):
            return year
        return f"{month} {year}"

    tail = one(end) if end else label("present", language)
    head = one(start)
    return f"{head} – {tail}" if head else tail


def build_context(profile: Profile, tailored: TailoredCV, job: Job | None = None) -> dict:
    """Everything a template needs, already ordered and localised.

    All of the tailoring is resolved here, so the templates contain no logic
    beyond looping — which is what keeps a new template cheap to write.
    """
    language = tailored.language
    order = {experience.id: tailored.bullet_order.get(experience.id, []) for experience in profile.experience}

    experiences = []
    for experience in profile.experience:
        by_id = {bullet.id: bullet for bullet in experience.bullets}
        ordered_ids = [bid for bid in order.get(experience.id, []) if bid in by_id]
        ordered_ids += [bid for bid in by_id if bid not in ordered_ids]
        experiences.append(
            {
                "title": localized(experience.title, language),
                "organization": experience.organization,
                "location": localized(experience.location, language),
                "period": localized(experience.period_note, language)
                or format_period(experience.start, experience.end, language),
                "bullets": [localized(by_id[bid].text, language) for bid in ordered_ids],
            }
        )

    groups_by_key = {group.key: group for group in profile.skills}
    ordered_groups = [groups_by_key[key] for key in tailored.skill_order if key in groups_by_key]
    ordered_groups += [group for group in profile.skills if group not in ordered_groups]

    return {
        "language": language,
        "name": profile.contact.name_for(language),
        "headline": tailored.headline,
        "contact_line": " · ".join(
            part
            for part in (
                localized(profile.contact.city, language),
                profile.contact.phone,
                profile.contact.email,
                profile.contact.linkedin,
                profile.contact.github,
            )
            if part
        ),
        "summary": tailored.summary,
        "experiences": experiences,
        "education": [
            {
                "degree": localized(item.degree, language),
                "institution": localized(item.institution, language),
                "period": format_period(item.start, item.end, language),
                "note": localized(item.note, language),
            }
            for item in profile.education
        ],
        "certifications": [
            " — ".join(
                part
                for part in (localized(item.name, language), item.issuer, item.year)
                if part
            )
            for item in profile.certifications
        ],
        "skill_groups": [
            {"label": localized(group.label, language), "items": ", ".join(group.items)}
            for group in ordered_groups
            if group.items
        ],
        "languages": [
            f"{localized(item.name, language)}" + (f" ({item.level})" if item.level else "")
            for item in profile.languages
        ],
        "extras": {key: localized(value, language) for key, value in profile.extras.items()},
        "label": lambda section: label(section, language),
        "job": {"company": job.company, "title": job.title} if job else None,
    }


def _environment() -> Environment:
    return Environment(
        loader=FileSystemLoader(str(TEMPLATE_DIR)),
        autoescape=select_autoescape(["html"]),
        trim_blocks=True,
        lstrip_blocks=True,
    )


def render_html(context: dict, template_name: str = "classic", scale: float = 1.0) -> str:
    """Render the CV to a standalone HTML document."""
    env = _environment()
    try:
        template = env.get_template(f"{template_name}.html")
    except TemplateNotFound:
        log.warning("CV template '%s' does not exist; using 'classic' instead.", template_name)
        try:
            template = env.get_template("classic.html")
        except TemplateNotFound as exc:
            raise RenderError(
                "The CV templates are missing from the installation.",
                hint="Reinstall JobRadar.",
            ) from exc
    try:
        return template.render(**context, scale=scale)
    except TemplateError as exc:
        raise RenderError(
            f"The CV template '{template.name}' could not be rendered: {exc}",
            hint="If you edited the template, check its syntax.",
        ) from exc


def _measure_and_print(html: str, pdf_path: Path, max_pages: int) -> tuple[int, bool]:
    """Print ``html`` to PDF with headless Chromium and report the page count.

    Playwright is an optional dependency; without it the caller keeps the HTML,
    which every browser can print to PDF by hand.
    """
    from playwright.sync_api import sync_playwright

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page()
        page.set_content(html, wait_until="load")
        height = page.evaluate("document.documentElement.scrollHeight")
        page.pdf(
            path=str(pdf_path),
            format="A4",
            print_background=True,
            margin={"top": "0", "bottom": "0", "left": "0", "right": "0"},
        )
        browser.close()
    usable = PAGE_HEIGHT_PX - PAGE_MARGIN_PX
    pages = max(1, -(-int(height) // usable))  # ceiling division
    return pages, pages <= max_pages


def _write(path: Path, html: str) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(html, encoding="utf-8")
    except OSError as exc:
        raise RenderError(
            f"Cannot write the CV to {path}: {describe_os_error(exc)}.",
            hint="Check that the data directory is writable and the disk is not full.",
        ) from exc


def _pdf_failure(exc: Exception) -> str:
    """One readable line for a failed PDF render, with the fix when known.

    Playwright's own messages run to a boxed banner of a dozen lines; the
    first line says what happened and the rest is the advice given here.
    """
    first_line = (str(exc).strip().splitlines() or [type(exc).__name__])[0]
    message = f"PDF rendering failed, so only the HTML was produced: {first_line}"
    if "executable doesn't exist" in str(exc).lower() or "playwright install" in str(exc).lower():
        message += " — install the browser with: playwright install chromium"
    return message


def render_cv(
    profile: Profile,
    tailored: TailoredCV,
    job: Job,
    paths: Paths,
    settings: Settings,
) -> RenderResult:
    """Render, shrink to fit, and write the CV next to the other generated files."""
    context = build_context(profile, tailored, job)
    stem = f"CV_{slugify(job.company or 'company', 28)}__{slugify(job.title or 'job', 34)}"
    html_path = paths.cv_dir / f"{stem}.html"
    pdf_path = paths.cv_dir / f"{stem}.pdf"
    warnings: list[str] = []

    html = render_html(context, settings.cv_template, 1.0)
    _write(html_path, html)

    try:
        import playwright  # noqa: F401
    except ImportError:
        warnings.append(
            "Playwright is not installed, so only the HTML was produced. "
            "Install it with: pip install 'jobradar[pdf]' && playwright install chromium"
        )
        return RenderResult(html_path, None, None, 1.0, False, warnings)

    pages, fitted, used_scale = None, False, 1.0
    for scale in SCALES:
        html = render_html(context, settings.cv_template, scale)
        _write(html_path, html)
        try:
            pages, fitted = _measure_and_print(html, pdf_path, settings.cv_max_pages)
        except Exception as exc:  # Playwright raises its own errors, and browsers crash
            log.warning("PDF rendering failed: %s", exc)
            warnings.append(_pdf_failure(exc))
            return RenderResult(html_path, None, None, scale, False, warnings)
        used_scale = scale
        if fitted:
            break

    if not fitted:
        warnings.append(
            f"The CV still runs to {pages} pages at the smallest readable size. "
            "Shorten an achievement or drop an older position rather than shrinking further."
        )
    return RenderResult(html_path, pdf_path, pages, used_scale, fitted, warnings)
