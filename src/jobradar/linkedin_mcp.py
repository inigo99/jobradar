"""LinkedIn through the LinkedIn MCP server, signed in as you. **Opt-in, restricted.**

`linkedin-mcp-server <https://github.com/stickerdaniel/linkedin-mcp-server>`_
reads LinkedIn in a browser that holds *your* session, and answers over the
Model Context Protocol. JobRadar starts it (``uvx mcp-server-linkedin`` by
default) and talks to it as an MCP client over stdio; the ``mcp`` package
comes with the ``linkedin-mcp`` extra. Nothing of the server is copied here.

Three things use it: the ``linkedin_mcp`` source (searches with your titles
and reads each ad), the import of the jobs you saved on LinkedIn, and the
import of your own profile. They share the client and the readers below.

The server answers with the page's visible text, not with fields: what a
posting or a profile says is read here from that text, the way a person
would read the page. LinkedIn's interface language changes the words, so the
markers are listed in English and Spanish.
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import json
import logging
import os
import re
import shlex
import shutil
import threading
import time
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any

from .errors import JobRadarError, MissingDependencyError
from .models import WorkMode

log = logging.getLogger(__name__)

#: The server's repository, for the settings screen and the docs.
HOMEPAGE = "https://github.com/stickerdaniel/linkedin-mcp-server"
#: How JobRadar starts the server. Without ``@latest`` uvx keeps the version it
#: installed first; ``uvx mcp-server-linkedin@latest`` updates it on every
#: start, which keeps up with LinkedIn's page changes — your choice, in Settings.
DEFAULT_COMMAND = "uvx mcp-server-linkedin"
#: Seconds one tool call may take: a cold start installs a browser.
CALL_TIMEOUT = 300.0
#: How long a call waits for the server to finish setting up (installing its
#: browser, or you signing in), and how often it asks again meanwhile.
SETUP_WAIT = 600.0
SETUP_POLL = 20.0
#: The server's answer while it is still setting up.
_SETTING_UP = re.compile(r"setup is not complete|in progress|call this tool again", re.I)
#: The sections of your profile the import reads, besides the main page.
PROFILE_SECTIONS = "experience,education,skills,languages,certifications,honors,contact_info"


class LinkedInMCPError(JobRadarError):
    """The LinkedIn MCP server could not be started or refused a call."""

    status_code = 502


# ---------------------------------------------------------------------------
# The client
# ---------------------------------------------------------------------------


class LinkedInMCP:
    """One running server and an MCP session with it.

    The MCP client is asynchronous and JobRadar is not: the session lives on
    its own event loop in a background thread, opened and closed by one task
    (the transport insists), and :meth:`call` hands each request to that loop
    and waits. Use it as a context manager, or call :meth:`close`.
    """

    def __init__(self, command: str = DEFAULT_COMMAND, timeout: float = CALL_TIMEOUT,
                 setup_wait: float | None = None):
        self.command = (command or "").strip() or DEFAULT_COMMAND
        self.timeout = timeout
        self.setup_wait = SETUP_WAIT if setup_wait is None else setup_wait
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._session: Any = None
        self._stop: asyncio.Event | None = None
        self._serving: concurrent.futures.Future | None = None

    def __enter__(self) -> LinkedInMCP:
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    def start(self) -> None:
        """Start the server and open the session, unless that is done."""
        if self._session is not None:
            return
        try:
            from mcp import ClientSession, StdioServerParameters
            from mcp.client.stdio import stdio_client
        except ImportError as exc:
            raise MissingDependencyError(
                "Reading LinkedIn through the MCP server needs the 'mcp' package.",
                hint="pip install 'jobradar-cv[linkedin-mcp]'",
            ) from exc
        argv = shlex.split(self.command)
        if shutil.which(argv[0]) is None:
            raise LinkedInMCPError(
                f"Cannot start the LinkedIn MCP server: '{argv[0]}' is not installed.",
                hint="Install uv (https://docs.astral.sh/uv/), or set the command that starts "
                     "the server in Settings.",
            )
        # Your whole environment, not the SDK's short default list: uv needs your
        # proxy and certificate settings to install the server.
        params = StdioServerParameters(command=argv[0], args=argv[1:], env=dict(os.environ))
        ready: concurrent.futures.Future = concurrent.futures.Future()

        async def serve() -> None:
            self._stop = asyncio.Event()
            try:
                async with stdio_client(params) as (read, write):
                    async with ClientSession(read, write) as session:
                        await session.initialize()
                        self._session = session
                        ready.set_result(None)
                        await self._stop.wait()
            except BaseException as exc:  # reported to start(), or logged once running
                if not ready.done():
                    ready.set_exception(exc)
                else:
                    log.debug("The LinkedIn MCP session ended: %s", exc)
            finally:
                self._session = None

        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(target=self._loop.run_forever,
                                        name="linkedin-mcp", daemon=True)
        self._thread.start()
        self._serving = asyncio.run_coroutine_threadsafe(serve(), self._loop)
        try:
            ready.result(timeout=self.timeout)
        except Exception as exc:
            self.close()
            raise LinkedInMCPError(
                f"The LinkedIn MCP server did not start: {_first_line(exc)}",
                hint=f"Try '{self.command} --login' in a terminal first.",
            ) from exc

    def call(self, tool: str, **arguments: Any) -> dict:
        """Call ``tool`` and return its result as a dict.

        The server's first calls answer "setup is not complete" while it
        installs its browser, or while you sign in in the window it opened:
        those are waited out, up to :data:`SETUP_WAIT` seconds.
        """
        waited = 0.0
        while True:
            try:
                return self._call_once(tool, arguments)
            except LinkedInMCPError as exc:
                if not _SETTING_UP.search(exc.message) or waited >= self.setup_wait:
                    raise
                log.info("The LinkedIn MCP server is still setting up; asking again in %ds.",
                         SETUP_POLL)
                time.sleep(SETUP_POLL)
                waited += SETUP_POLL

    def _call_once(self, tool: str, arguments: dict[str, Any]) -> dict:
        self.start()
        if self._loop is None or self._session is None:
            raise LinkedInMCPError("The LinkedIn MCP session is closed.")
        arguments = {name: value for name, value in arguments.items() if value is not None}
        future = asyncio.run_coroutine_threadsafe(
            self._session.call_tool(tool, arguments), self._loop)
        try:
            result = future.result(timeout=self.timeout)
        except concurrent.futures.TimeoutError as exc:
            future.cancel()
            raise LinkedInMCPError(f"LinkedIn took too long to answer {tool}.") from exc
        except Exception as exc:
            raise LinkedInMCPError(f"{tool} failed: {_first_line(exc)}") from exc
        return tool_result(tool, result)

    def close(self) -> None:
        """Close the session and stop the server; safe to call twice."""
        loop, self._loop = self._loop, None
        if loop is None:
            return
        if self._stop is not None:
            loop.call_soon_threadsafe(self._stop.set)
        if self._serving is not None:
            try:
                self._serving.result(timeout=15)
            except Exception as exc:
                log.debug("Closing the LinkedIn MCP session: %s", exc)
        loop.call_soon_threadsafe(loop.stop)
        if self._thread is not None:
            self._thread.join(timeout=5)
        if not loop.is_running():
            loop.close()
        self._session = self._stop = self._serving = self._thread = None


def tool_result(tool: str, result: Any) -> dict:
    """The dict a tool returned, from a ``CallToolResult`` of either SDK generation."""
    error = getattr(result, "is_error", None)
    if error is None:
        error = getattr(result, "isError", False)
    texts = [str(getattr(item, "text", "")) for item in (getattr(result, "content", None) or [])
             if getattr(item, "text", None)]
    if error:
        message = " ".join(texts).strip() or "no reason given"
        raise LinkedInMCPError(f"LinkedIn MCP: {tool} failed: {message}",
                               hint=_login_hint(message))
    structured = getattr(result, "structured_content", None)
    if structured is None:
        structured = getattr(result, "structuredContent", None)
    if isinstance(structured, dict):
        inner = structured.get("result")
        return inner if set(structured) == {"result"} and isinstance(inner, dict) else structured
    for text in texts:
        try:
            parsed = json.loads(text)
        except ValueError:
            continue
        if isinstance(parsed, dict):
            return parsed
    return {"text": "\n".join(texts)}


def _login_hint(message: str) -> str:
    if re.search(r"login|log in|sign in|authenticat|session", message, re.I):
        return f"Sign in once with '{DEFAULT_COMMAND} --login'."
    return ""


def _first_line(exc: BaseException) -> str:
    """The first line of the error that actually happened, out of any task-group wrapping."""
    while getattr(exc, "exceptions", None):
        exc = exc.exceptions[0]  # type: ignore[attr-defined]
    return (str(exc).strip().splitlines() or [type(exc).__name__])[0]


# ---------------------------------------------------------------------------
# Reading what the server returns
# ---------------------------------------------------------------------------


def job_ids(result: dict) -> list[str]:
    """The job ids a search or the saved-jobs list returned, in order."""
    return [str(job_id) for job_id in (result.get("job_ids") or []) if str(job_id).isdigit()]


_JOB_URL = re.compile(r"/jobs/view/(\d+)")


def titles_by_id(result: dict) -> dict[str, str]:
    """The title of each result, where the server could read one."""
    titles: dict[str, str] = {}
    for references in (result.get("references") or {}).values():
        for reference in references or []:
            match = _JOB_URL.search(str(reference.get("url") or ""))
            text = str(reference.get("text") or "").strip()
            if match and text and match.group(1) not in titles:
                titles[match.group(1)] = text
    return titles


#: The heading the description follows.
DESCRIPTION_HEADINGS = ("About the job", "Acerca del empleo", "Acerca de la oferta")
#: Where the description ends: what LinkedIn shows below it.
DESCRIPTION_ENDS = (
    "Set alert for similar jobs", "About the company", "See how you compare to",
    "Looking for talent?", "More jobs", "Show less",
    "Crear alerta de empleo", "Acerca de la empresa", "Más empleos", "Mostrar menos",
)
_SEE_MORE = re.compile(r"^(?:…\s*(?:more|más)|(?:…\s*)?(?:show more|see more|show all|"
                       r"mostrar más|ver más|mostrar todo))$", re.I)
#: Buttons and labels on the posting's header, never its title or company.
_HEADER_NOISE = re.compile(
    r"^(?:share|show more options|save|saved|apply|easy apply|applied|message|follow|"
    r"compartir|mostrar más opciones|guardar|guardado|solicitar|solicitud sencilla|mensaje|"
    r"seguir|premium|promoted|promocionado|meet the hiring team|conoce al equipo de contratación|"
    r"use ai to assess how you fit|show match details|tailor my resume|help me stand out|"
    r"am i a good fit.*|how can i best position.*|tell me more about.*|"
    r"(?:save|guardar) .+ (?:at|en) .+|responses managed off linkedin|"
    r"promoted by hirer.*|actively reviewing applicants|.*matches your job preferences.*|"
    r"full-time|part-time|contract|temporary|internship|volunteer|"
    r"jornada completa|media jornada|contrato por obra|temporal|prácticas|voluntario)$",
    re.I,
)
#: The line under the title: "Madrid, Spain · 3 days ago · Over 100 applicants".
_META = re.compile(r"·.*(?:\bago\b|\bhace\b|applicant|solicitud|clicked|people|personas|"
                   r"reposted|publicad|vuelto a publicar)", re.I)
_AGO = re.compile(r"(\d+)\s+(minute|hour|day|week|month)s?\s+ago", re.I)
_HACE = re.compile(r"hace\s+(\d+)\s+(minuto|hora|día|dia|semana|mes)", re.I)
_UNIT_DAYS = {"minute": 0, "hour": 0, "day": 1, "week": 7, "month": 30,
              "minuto": 0, "hora": 0, "día": 1, "dia": 1, "semana": 7, "mes": 30}
_BADGES = {
    "remote": WorkMode.REMOTE, "remoto": WorkMode.REMOTE,
    "hybrid": WorkMode.HYBRID, "híbrido": WorkMode.HYBRID, "hibrido": WorkMode.HYBRID,
    "on-site": WorkMode.ONSITE, "onsite": WorkMode.ONSITE, "presencial": WorkMode.ONSITE,
}
_CLOSED = re.compile(r"^(?:no longer accepting applications|ya no se aceptan solicitudes)$", re.I)


@dataclass
class Posting:
    """What a job posting's page says, read from its text."""

    job_id: str
    title: str = ""
    company: str = ""
    location: str = ""
    posted_at: date | None = None
    work_mode: WorkMode = WorkMode.UNKNOWN
    description: str = ""
    #: ``closed`` or ``applied`` when the page shows it, else empty.
    state: str = ""

    @property
    def url(self) -> str:
        return f"https://www.linkedin.com/jobs/view/{self.job_id}/"


def read_posting(job_id: str, result: dict, title: str = "",
                 today: date | None = None) -> Posting:
    """The posting ``get_job_details`` returned for ``job_id``.

    ``title`` is the one the search showed, which is surer than a line read
    off the page header; the page is read for everything else.
    """
    text = str((result.get("sections") or {}).get("job_posting") or "")
    lines = _unique_lines(text)
    start = next((i for i, line in enumerate(lines) if line in DESCRIPTION_HEADINGS), len(lines))
    header, body = lines[:start], lines[start + 1:]
    posting = Posting(job_id=str(job_id), title=title.strip())

    state = str((result.get("apply") or {}).get("type") or "")
    if state in ("closed", "applied"):
        posting.state = state
    elif any(_CLOSED.match(line) for line in header):
        posting.state = "closed"

    meta = next((i for i, line in enumerate(header) if _META.search(line)), None)
    useful = [i for i, line in enumerate(header) if not _HEADER_NOISE.match(line)
              and line.lower() not in _BADGES and not _CLOSED.match(line)]
    if meta is not None:
        parts = [part.strip() for part in header[meta].split("·")]
        posting.location = parts[0]
        posting.posted_at = _posted(header[meta], today)
        above = [i for i in useful if i < meta]
        if not posting.title and above:
            posting.title = header[above[-1]]
        company = [i for i in above if header[i] != posting.title]
        if company:
            posting.company = header[company[0]]
    elif useful:
        if not posting.title:
            posting.title = header[useful[0]]
        rest = [header[i] for i in useful if header[i] != posting.title]
        posting.company = rest[0] if rest else ""
    for line in header:
        if line.lower() in _BADGES:
            posting.work_mode = _BADGES[line.lower()]
            break

    description: list[str] = []
    for line in body:
        if line in DESCRIPTION_ENDS:
            break
        if not _SEE_MORE.match(line):
            description.append(line)
    posting.description = "\n".join(description).strip()
    return posting


def _posted(line: str, today: date | None = None) -> date | None:
    match = _AGO.search(line) or _HACE.search(line)
    if not match:
        return None
    days = int(match.group(1)) * _UNIT_DAYS[match.group(2).lower()]
    return (today or date.today()) - timedelta(days=days)


def _unique_lines(text: str) -> list[str]:
    """Non-empty lines, without the copy LinkedIn prints right under some of them."""
    lines: list[str] = []
    for raw in text.splitlines():
        line = raw.strip()
        if line and (not lines or lines[-1] != line):
            lines.append(line)
    return lines


#: LinkedIn's profile headings, and the CV heading the importer knows each by.
_PROFILE_HEADINGS = {
    "about": "Summary", "acerca de": "Summary",
    "experience": "Experience", "experiencia": "Experience",
    "education": "Education", "educación": "Education", "formación": "Education",
    "skills": "Skills", "aptitudes": "Skills",
    "languages": "Languages", "idiomas": "Languages",
    "licenses & certifications": "Certifications", "licencias y certificaciones": "Certifications",
    "honors & awards": "Awards", "reconocimientos y premios": "Awards",
}
#: Where the main page's header (name, headline, place) ends.
_MAIN_STOPS = {"about", "acerca de", "activity", "actividad", "featured", "destacado",
               "experience", "experiencia", "education", "educación", "analytics", "análisis",
               "resources", "recursos", "open to", "disponible para"}
#: Lines of the main page's header that are buttons or counts, not you.
_PROFILE_NOISE = re.compile(
    r"connections|contactos|followers|seguidores|^contact info$|^información de contacto$|"
    r"^(?:open to|add profile section|enhance profile|more|resources|message|follow|connect|"
    r"disponible para|añadir sección|mejorar perfil|más|mensaje|seguir|conectar)$|"
    r"^(?:he|she|they)/(?:him|her|them)$",
    re.I,
)
#: Section names in the order a CV is read.
_SECTION_ORDER = ("experience", "education", "certifications", "skills", "languages", "honors")
_SECTION_HEADING = {"experience": "Experience", "education": "Education",
                    "certifications": "Certifications", "skills": "Skills",
                    "languages": "Languages", "honors": "Awards"}


def profile_text(result: dict) -> str:
    """Your profile as the text of a CV, for the CV importer to read.

    The main page gives the header (name, headline, place) and the About
    text; each detail page gives one section. LinkedIn lays a position out
    as title, company, dates on separate lines; each is rewritten the way a
    CV writes it ("Title — Company", "place · 2024-01 - present", bullets),
    which is the layout the importer reads best.
    """
    sections = result.get("sections") or {}
    main = _unique_lines(str(sections.get("main_profile") or ""))
    header: list[str] = []
    about: list[str] = []
    reading = "header"  # then "about" under its heading, "skip" under any other
    for line in main:
        key = line.lower()
        if key in ("about", "acerca de"):
            reading = "about"
        elif key in _MAIN_STOPS or key in _PROFILE_HEADINGS:
            reading = "skip"
        elif reading == "header" and not _PROFILE_NOISE.search(line):
            header.append(line)
        elif reading == "about":
            about.append(line)
    header = header[:3]  # name, headline, place: what a CV's header holds

    contact = [line for line in _section_lines(sections, "contact_info")
               if not _CONTACT_LABEL.match(line)]
    url = str(result.get("url") or "")
    if "/in/" in url:
        contact.append(url)
    if contact:
        # The place, then every way to reach you, on one line as CVs have it.
        place = header.pop() if len(header) == 3 else ""
        header.append(" · ".join([part for part in [place] if part] + contact))

    parts: list[str] = ["\n".join(header)]
    if about:
        parts.append("Summary\n" + "\n".join(about))
    writers = {"experience": _positions, "education": _studies, "languages": _languages}
    for name in _SECTION_ORDER:
        lines = _section_lines(sections, name)
        lines = writers[name](lines) if name in writers else lines
        if lines:
            parts.append(_SECTION_HEADING[name] + "\n" + "\n".join(lines))
    return "\n\n".join(part for part in parts if part.strip())


_CONTACT_LABEL = re.compile(
    r"^(?:contact info|información de contacto|email|correo electrónico|phone|teléfono|"
    r"website|websites|sitio web|address|dirección|birthday|cumpleaños|"
    r"your profile|tu perfil|connected since|.*\(work\)|.*\(mobile\)|.*\(home\))$",
    re.I,
)
_MONTHS = {name: number for number, names in enumerate((
    ("jan", "ene", "january", "enero"), ("feb", "february", "febrero"),
    ("mar", "march", "marzo"), ("apr", "abr", "april", "abril"), ("may", "mayo"),
    ("jun", "june", "junio"), ("jul", "july", "julio"), ("aug", "ago", "august", "agosto"),
    ("sep", "sept", "september", "septiembre", "set"), ("oct", "october", "octubre"),
    ("nov", "november", "noviembre"), ("dec", "dic", "december", "diciembre"),
), start=1) for name in names}
_WHEN = r"(?:([a-záéíóú]+)\.?\s+(?:de\s+)?)?(\d{4})"
#: "Jan 2024 - Jun 2024 · 6 mos", "2019 - 2023", "sept. 2022 - actualidad".
_DATE_RANGE = re.compile(
    rf"^{_WHEN}\s*[-–]\s*(?:{_WHEN}|(present|actualidad|presente|now))(?:\s*·.*)?$", re.I)
_SINGLE_DATE = re.compile(rf"^{_WHEN}(?:\s*·.*)?$", re.I)
_LEVELS = {"native": "Native", "nativo": "Native", "bilingual": "Native", "bilingüe": "Native",
           "full professional": "C1", "completa": "C1", "professional working": "B2",
           "profesional": "B2", "limited working": "B1", "limitada": "B1",
           "elementary": "A2", "básica": "A2", "elemental": "A2"}


def _section_lines(sections: dict, name: str) -> list[str]:
    lines = _unique_lines(str(sections.get(name) or ""))
    if lines and (lines[0].lower() in _PROFILE_HEADINGS or _CONTACT_LABEL.match(lines[0])):
        lines = lines[1:]
    return [line for line in lines if not _SEE_MORE.match(line)]


def _month(word: str | None, year: str) -> str:
    number = _MONTHS.get((word or "").lower().rstrip("."), 0)
    return f"{year}-{number:02d}" if number else year


def _dates(line: str) -> str | None:
    """A LinkedIn date line as a CV writes it ("2024-01 - present"), or None."""
    match = _DATE_RANGE.match(line)
    if match:
        start = _month(match.group(1), match.group(2))
        end = "present" if match.group(5) else _month(match.group(3), match.group(4))
        return f"{start} - {end}"
    single = _SINGLE_DATE.match(line)
    return _month(single.group(1), single.group(2)) if single else None


def _positions(lines: list[str]) -> list[str]:
    """LinkedIn's experience as a CV's: "Title — Company", "place · dates", bullets.

    A position is the two lines above a date line (title, then company with
    its employment type); what follows the dates, up to the next position,
    is its place (when it reads like one) and its description.
    """
    starts = [i for i, line in enumerate(lines) if _dates(line) and i >= 1]
    out: list[str] = []
    for number, at in enumerate(starts):
        title = lines[at - 2] if at >= 2 else lines[at - 1]
        company = lines[at - 1].split(" · ")[0] if at >= 2 else ""
        end = starts[number + 1] - 2 if number + 1 < len(starts) else len(lines)
        rest = lines[at + 1:max(end, at + 1)]
        place = ""
        if rest and re.search(r",|\b(?:on-site|remote|hybrid|presencial|remoto|híbrido)$",
                              rest[0], re.I) and len(rest[0]) < 80:
            place = rest.pop(0).split(" · ")[0]
        if out:
            out.append("")
        out.append(f"{title} — {company}" if company else title)
        out.append(" · ".join(part for part in (place, _dates(lines[at]) or "") if part))
        out.extend(f"• {line}" for line in rest if not line.lower().startswith(("skills:",
                                                                                 "aptitudes:")))
    return out


def _studies(lines: list[str]) -> list[str]:
    """LinkedIn's education as a CV's: "Degree — School", then the years."""
    starts = [i for i, line in enumerate(lines) if _dates(line)]
    out: list[str] = []
    for at in starts:
        above = [line for line in lines[max(0, at - 2):at] if not _dates(line)]
        school = above[0] if above else ""
        degree = above[1] if len(above) > 1 else ""
        if out:
            out.append("")
        out.append(f"{degree} — {school}" if degree else school)
        out.append(_dates(lines[at]) or "")
    return out


def _languages(lines: list[str]) -> list[str]:
    """LinkedIn's languages, name then proficiency, as one line: "Spanish (Native) · English (C1)"."""
    spoken: list[str] = []
    for line in lines:
        level = next((code for word, code in _LEVELS.items() if word in line.lower()), None)
        if level and spoken and "(" not in spoken[-1]:
            spoken[-1] = f"{spoken[-1]} ({level})"
        elif not level:
            spoken.append(line)
    return [" · ".join(spoken)] if spoken else []
