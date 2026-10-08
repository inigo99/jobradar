"""Does the CV's PDF read back as text? The check an applicant-tracking system makes.

An ATS does not look at the PDF: it extracts its text and parses that. A CV
whose name is drawn as an image, whose letters come out as glyph codes, or
whose bullets are split across columns, looks right and reads as nothing. So
after printing, the PDF is read back the way an ATS reads it (with ``pypdf``)
and compared with what was meant to be in it: your name and email, each
position and organisation, and the start of every achievement.

Needs the ``parse`` extra (``pypdf``); without it the check is skipped.
"""

from __future__ import annotations

import logging
import re
import unicodedata
from pathlib import Path

log = logging.getLogger(__name__)

#: Words of each achievement looked for: enough to be sure, few enough to
#: survive a line break the PDF puts in the middle of a sentence.
BULLET_WORDS = 6
#: Share of achievements that may be missing before it is worth a warning.
MISSING_SHARE = 0.2

_LIGATURES = {"ﬁ": "fi", "ﬂ": "fl", "ﬀ": "ff", "ﬃ": "ffi", "ﬄ": "ffl", "’": "'", "‘": "'",
              "“": '"', "”": '"', "–": "-", "—": "-"}


def _plain(text: str) -> str:
    """Lower case, no accents or ligatures, hyphenated line breaks joined, one space."""
    for ligature, letters in _LIGATURES.items():
        text = text.replace(ligature, letters)
    text = re.sub(r"(\w)-\s*\n\s*(\w)", r"\1\2", text)
    text = unicodedata.normalize("NFKD", text)
    text = "".join(char for char in text if not unicodedata.combining(char))
    return " ".join(re.sub(r"[^\w@.+'%-]+", " ", text.lower()).split())


def pdf_text(path: Path) -> str | None:
    """The text an ATS would extract from ``path``, or None when it cannot be read."""
    try:
        from pypdf import PdfReader
    except ImportError:
        return None
    try:
        reader = PdfReader(str(path))
        return "\n".join(page.extract_text() or "" for page in reader.pages)
    except Exception as exc:  # a malformed PDF is exactly what this is here to catch
        log.info("Could not read %s back: %s", path, exc)
        return ""


def ats_warnings(path: Path | None, context: dict) -> list[str]:
    """What an ATS would not find in the PDF at ``path``, as warnings for the user.

    ``context`` is what the PDF was printed from (``render.build_context``).
    """
    if path is None or not Path(path).is_file():
        return []
    extracted = pdf_text(Path(path))
    if extracted is None:
        return []
    text = _plain(extracted)
    if not text:
        return ["The PDF has no text an applicant-tracking system can read: it would see an "
                "empty CV. Print it again with the built-in PDF writer."]
    warnings: list[str] = []
    name = str(context.get("name") or "")
    if name and _plain(name) not in text:
        warnings.append("An applicant-tracking system reading this PDF does not find your name.")
    email = next((part for part in str(context.get("contact_line") or "").split(" · ")
                  if "@" in part), "")
    if email and _plain(email) not in text:
        warnings.append("An applicant-tracking system reading this PDF does not find your email.")
    positions = [entry for entry in context.get("experiences") or []]
    lost = [entry["title"] for entry in positions
            if entry.get("title") and _plain(str(entry["title"])) not in text]
    if lost:
        warnings.append(f"The position “{lost[0]}” does not come out of the PDF as text"
                        + (f", nor {len(lost) - 1} more." if len(lost) > 1 else "."))
    bullets = [str(bullet) for entry in positions for bullet in entry.get("bullets") or []]
    missing = [bullet for bullet in bullets
               if " ".join(_plain(bullet).split()[:BULLET_WORDS]) not in text]
    if bullets and len(missing) > MISSING_SHARE * len(bullets):
        warnings.append(f"{len(missing)} of {len(bullets)} achievements do not come out of the "
                        "PDF as continuous text: an applicant-tracking system may read them "
                        "jumbled. A single-column template avoids it.")
    return warnings
