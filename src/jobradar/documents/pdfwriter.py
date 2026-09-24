"""A dependency-free PDF writer for the CV and the letters.

Printing through a browser (Playwright + Chromium) gives the best typography,
but it is a large install that breaks whenever the browser build and the
package drift apart. This writer needs nothing: it produces PDF 1.4 with the
standard Helvetica fonts every PDF reader ships (no font is embedded), in the
Windows-1252 encoding those fonts use, and measures text with the fonts' own
character widths so lines wrap where they should.

It covers what a CV and a letter need — headings, wrapped paragraphs, bullet
lists, thin rules, several pages — and nothing else. Characters outside
Windows-1252 are reduced to their base letter (``ł`` -> ``l``) or ``?``.
"""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass, field

#: A4 in points.
PAGE_WIDTH, PAGE_HEIGHT = 595.28, 841.89

#: Advance widths (1/1000 em) of Helvetica and Helvetica-Bold, indexed by
#: Windows-1252 byte, from the Adobe font metrics of the base-14 fonts.
HELVETICA: tuple[int, ...] = (
    0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0,
    0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0,
    278, 278, 355, 556, 556, 889, 667, 191, 333, 333, 389, 584, 278, 333, 278, 278,
    556, 556, 556, 556, 556, 556, 556, 556, 556, 556, 278, 278, 584, 584, 584, 556,
    1015, 667, 667, 722, 722, 667, 611, 778, 722, 278, 500, 667, 556, 833, 722, 778,
    667, 778, 722, 667, 611, 722, 667, 944, 667, 667, 611, 278, 278, 278, 469, 556,
    333, 556, 556, 500, 556, 556, 278, 556, 556, 222, 222, 500, 222, 833, 556, 556,
    556, 556, 333, 500, 278, 556, 500, 722, 500, 500, 500, 334, 260, 334, 584, 350,
    556, 350, 222, 556, 333, 1000, 556, 556, 333, 1000, 667, 333, 1000, 350, 611, 350,
    350, 222, 222, 333, 333, 350, 556, 1000, 333, 1000, 500, 333, 944, 350, 500, 667,
    278, 333, 556, 556, 556, 556, 260, 556, 333, 737, 370, 556, 584, 333, 737, 333,
    400, 584, 333, 333, 333, 556, 537, 278, 333, 333, 365, 556, 834, 834, 834, 611,
    667, 667, 667, 667, 667, 667, 1000, 722, 667, 667, 667, 667, 278, 278, 278, 278,
    722, 722, 778, 778, 778, 778, 778, 584, 778, 722, 722, 722, 722, 667, 667, 611,
    556, 556, 556, 556, 556, 556, 889, 500, 556, 556, 556, 556, 278, 278, 278, 278,
    556, 556, 556, 556, 556, 556, 556, 584, 611, 556, 556, 556, 556, 500, 556, 500,
)

HELVETICA_BOLD: tuple[int, ...] = (
    0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0,
    0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0,
    278, 333, 474, 556, 556, 889, 722, 238, 333, 333, 389, 584, 278, 333, 278, 278,
    556, 556, 556, 556, 556, 556, 556, 556, 556, 556, 333, 333, 584, 584, 584, 611,
    975, 722, 722, 722, 722, 667, 611, 778, 722, 278, 556, 722, 611, 833, 722, 778,
    667, 778, 722, 667, 611, 722, 667, 944, 667, 667, 611, 333, 278, 333, 584, 556,
    333, 556, 611, 556, 611, 556, 333, 611, 611, 278, 278, 556, 278, 889, 611, 611,
    611, 611, 389, 556, 333, 611, 556, 778, 556, 556, 500, 389, 280, 389, 584, 350,
    556, 350, 278, 556, 500, 1000, 556, 556, 333, 1000, 667, 333, 1000, 350, 611, 350,
    350, 278, 278, 500, 500, 350, 556, 1000, 333, 1000, 556, 333, 944, 350, 500, 667,
    278, 333, 556, 556, 556, 556, 280, 556, 333, 737, 370, 556, 584, 333, 737, 333,
    400, 584, 333, 333, 333, 611, 556, 278, 333, 333, 365, 556, 834, 834, 834, 611,
    722, 722, 722, 722, 722, 722, 1000, 722, 667, 667, 667, 667, 278, 278, 278, 278,
    722, 722, 778, 778, 778, 778, 778, 584, 778, 722, 722, 722, 722, 667, 667, 611,
    556, 556, 556, 556, 556, 556, 889, 556, 556, 556, 556, 556, 278, 278, 278, 278,
    611, 611, 611, 611, 611, 611, 611, 584, 611, 611, 611, 611, 611, 556, 611, 556,
)

#: Characters Windows-1252 places in 0x80-0x9F, where Latin-1 has controls.
CP1252_EXTRAS = {
    "€": 128, "‚": 130, "ƒ": 131, "„": 132, "…": 133, "†": 134, "‡": 135, "ˆ": 136, "‰": 137,
    "Š": 138, "‹": 139, "Œ": 140, "Ž": 142, "‘": 145, "’": 146, "“": 147, "”": 148, "•": 149,
    "–": 150, "—": 151, "˜": 152, "™": 153, "š": 154, "›": 155, "œ": 156, "ž": 158, "Ÿ": 159,
}
QUESTION_MARK = 63

INK = (0.07, 0.09, 0.10)
MUTED = (0.40, 0.45, 0.44)
ACCENT = (0.08, 0.38, 0.35)
RULE = (0.80, 0.84, 0.83)


def encode_char(char: str) -> int:
    """The Windows-1252 byte for ``char``, or the nearest plain letter, or ``?``."""
    code = ord(char)
    if char == "\t":
        return 32
    if 32 <= code < 127 or 160 <= code < 256:
        return code
    if char in CP1252_EXTRAS:
        return CP1252_EXTRAS[char]
    base = "".join(c for c in unicodedata.normalize("NFD", char) if 32 <= ord(c) < 127)
    return ord(base[0]) if base else QUESTION_MARK


def text_width(text: str, size: float, bold: bool = False) -> float:
    """Width of ``text`` in points at ``size``."""
    table = HELVETICA_BOLD if bold else HELVETICA
    return sum(table[encode_char(c)] or table[QUESTION_MARK] for c in text) * size / 1000.0


def wrap(text: str, size: float, bold: bool, max_width: float) -> list[str]:
    """Lines of ``text`` no wider than ``max_width``; a too-long word is split."""
    lines: list[str] = []
    for paragraph in str(text or "").replace("\r", "").split("\n"):
        words = paragraph.split()
        if not words:
            lines.append("")
            continue
        line = ""
        for word in words:
            candidate = f"{line} {word}" if line else word
            if text_width(candidate, size, bold) <= max_width:
                line = candidate
                continue
            if line:
                lines.append(line)
            while text_width(word, size, bold) > max_width and len(word) > 1:
                cut = len(word) - 1
                while cut > 1 and text_width(word[:cut], size, bold) > max_width:
                    cut -= 1
                lines.append(word[:cut])
                word = word[cut:]
            line = word
        lines.append(line)
    while lines and not lines[-1]:
        lines.pop()
    return lines


def _number(value: float) -> str:
    return f"{value:.2f}".rstrip("0").rstrip(".")


def _pdf_string(text: str) -> bytes:
    out = bytearray()
    for char in text:
        byte = encode_char(char)
        if byte in (40, 41, 92):  # ( ) \ must be escaped inside a PDF string
            out.append(92)
        out.append(byte)
    return bytes(out)


@dataclass
class Page:
    operations: list[bytes] = field(default_factory=list)

    def text(self, x: float, y: float, text: str, size: float, bold: bool = False,
             color: tuple[float, float, float] = INK) -> None:
        font = "F2" if bold else "F1"
        rgb = " ".join(_number(c) for c in color)
        self.operations.append(
            f"BT /{font} {_number(size)} Tf {rgb} rg 1 0 0 1 {_number(x)} {_number(y)} Tm (".encode()
            + _pdf_string(text) + b") Tj ET\n")

    def rule(self, x1: float, x2: float, y: float, width: float = 0.7,
             color: tuple[float, float, float] = RULE) -> None:
        rgb = " ".join(_number(c) for c in color)
        self.operations.append(
            f"{rgb} RG {_number(width)} w {_number(x1)} {_number(y)} m "
            f"{_number(x2)} {_number(y)} l S\n".encode())


def build_pdf(pages: list[Page], title: str = "") -> bytes:
    """Serialise ``pages`` into a complete PDF file."""
    objects: list[bytes] = []
    page_ids = [3 + 2 * i for i in range(len(pages))]
    font_id = 3 + 2 * len(pages)
    info_id = font_id + 2
    objects.append(b"<</Type/Catalog/Pages 2 0 R>>")
    objects.append(f"<</Type/Pages/Count {len(pages)}/Kids["
                   f"{' '.join(f'{i} 0 R' for i in page_ids)}]>>".encode())
    resources = f"<</Font<</F1 {font_id} 0 R/F2 {font_id + 1} 0 R>>>>"
    for page_id, page in zip(page_ids, pages, strict=True):
        objects.append(f"<</Type/Page/Parent 2 0 R/MediaBox[0 0 {_number(PAGE_WIDTH)} "
                       f"{_number(PAGE_HEIGHT)}]/Resources{resources}/Contents "
                       f"{page_id + 1} 0 R>>".encode())
        stream = b"".join(page.operations)
        objects.append(f"<</Length {len(stream)}>>\nstream\n".encode() + stream
                       + b"\nendstream")
    for base in ("Helvetica", "Helvetica-Bold"):
        objects.append(f"<</Type/Font/Subtype/Type1/BaseFont/{base}"
                       f"/Encoding/WinAnsiEncoding>>".encode())
    objects.append(b"<</Title(" + _pdf_string(title) + b")/Producer(JobRadar)>>")

    output = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets = []
    for number, body in enumerate(objects, start=1):
        offsets.append(len(output))
        output += f"{number} 0 obj\n".encode() + body + b"\nendobj\n"
    xref = len(output)
    output += f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode()
    for offset in offsets:
        output += f"{offset:010d} 00000 n \n".encode()
    output += (f"trailer\n<</Size {len(objects) + 1}/Root 1 0 R/Info {info_id} 0 R>>\n"
               f"startxref\n{xref}\n%%EOF\n").encode()
    return bytes(output)


# ---------------------------------------------------------------------------
# Layout
# ---------------------------------------------------------------------------


class Layout:
    """A cursor that writes downwards and starts a new page when it runs out."""

    def __init__(self, margin_x: float, margin_y: float, scale: float = 1.0):
        self.margin_x, self.margin_y, self.scale = margin_x, margin_y, scale
        self.width = PAGE_WIDTH - 2 * margin_x
        self.pages: list[Page] = [Page()]
        self.y = PAGE_HEIGHT - margin_y

    @property
    def page(self) -> Page:
        return self.pages[-1]

    def space(self, points: float) -> None:
        self.y -= points * self.scale
        if self.y < self.margin_y:
            self.pages.append(Page())
            self.y = PAGE_HEIGHT - self.margin_y - points * self.scale

    def line(self, text: str, size: float, bold: bool = False, color=INK, indent: float = 0.0,
             leading: float = 1.32) -> None:
        size *= self.scale
        self.space(size * leading / self.scale)
        self.page.text(self.margin_x + indent, self.y, text, size, bold, color)

    def paragraph(self, text: str, size: float, bold: bool = False, color=INK,
                  indent: float = 0.0, bullet: str = "") -> None:
        width = self.width - indent - (text_width(bullet + " ", size * self.scale) if bullet else 0)
        for index, text_line in enumerate(wrap(text, size * self.scale, bold, width)):
            if bullet and index == 0:
                self.line(f"{bullet} {text_line}", size, bold, color, indent)
            elif bullet:
                self.line(text_line, size, bold, color,
                          indent + text_width(bullet + " ", size * self.scale))
            else:
                self.line(text_line, size, bold, color, indent)

    def heading(self, text: str) -> None:
        self.space(7)
        self.line(text.upper(), 9.4, bold=True, color=ACCENT)
        self.space(2.5)
        self.page.rule(self.margin_x, PAGE_WIDTH - self.margin_x, self.y - 3 * self.scale)
        self.space(3)


#: Type scales tried, largest first, until the CV fits its page limit.
SCALES = (1.0, 0.95, 0.9, 0.86, 0.82, 0.78)


def _cv_layout(context: dict, scale: float) -> Layout:
    label = context["label"]
    page = Layout(margin_x=40, margin_y=34, scale=scale)
    page.line(context["name"], 19, bold=True)
    if context.get("headline"):
        page.line(context["headline"], 11.5, color=ACCENT)
    if context.get("contact_line"):
        page.paragraph(context["contact_line"], 8.6, color=MUTED)
    if context.get("summary"):
        page.heading(label("summary"))
        page.paragraph(context["summary"], 9.6)
    if context.get("experiences"):
        page.heading(label("experience"))
        for experience in context["experiences"]:
            page.space(3)
            page.paragraph(f"{experience['title']} — {experience['organization']}", 10, bold=True)
            where = " · ".join(p for p in (experience.get("location"), experience.get("period")) if p)
            if where:
                page.line(where, 8.6, color=MUTED)
            for bullet in experience["bullets"]:
                page.paragraph(bullet, 9.4, indent=4, bullet="•")
    if context.get("education"):
        page.heading(label("education"))
        for item in context["education"]:
            heading = " — ".join(p for p in (item.get("degree"), item.get("institution")) if p)
            if heading:
                page.paragraph(heading, 9.6, bold=True)
            details = " · ".join(p for p in (item.get("period"), item.get("note")) if p)
            if details:
                page.paragraph(details, 8.8, color=MUTED)
    if context.get("certifications"):
        page.heading(label("certifications"))
        for certification in context["certifications"]:
            page.paragraph(certification, 9.2, indent=4, bullet="•")
    if context.get("skill_groups"):
        page.heading(label("skills"))
        for group in context["skill_groups"]:
            page.paragraph(f"{group['label']}: {group['items']}", 9.2)
    if context.get("languages"):
        page.heading(label("languages"))
        page.paragraph(" · ".join(context["languages"]), 9.2)
    return page


def cv_pdf(context: dict, max_pages: int = 1) -> tuple[bytes, int, float]:
    """``(pdf, pages, scale)`` for the render context built by ``build_context``.

    The type shrinks step by step until the CV fits ``max_pages``; if even
    the smallest readable size does not fit, the CV runs over and the caller
    says so.
    """
    layout = _cv_layout(context, SCALES[0])
    for scale in SCALES:
        layout = _cv_layout(context, scale)
        if len(layout.pages) <= max_pages:
            break
    title = f"CV — {context['name']}"
    return build_pdf(layout.pages, title), len(layout.pages), layout.scale


LETTER_HEADINGS = {
    "cover_letter": {"en": "Cover letter", "es": "Carta de presentación", "fr": "Lettre de motivation",
                     "de": "Anschreiben", "pt": "Carta de apresentação", "it": "Lettera di presentazione"},
    "email": {"en": "Application email", "es": "Correo de candidatura", "fr": "E-mail de candidature",
              "de": "Bewerbungs-E-Mail", "pt": "E-mail de candidatura", "it": "E-mail di candidatura"},
}


def letter_pdf(sender: str, contact_line: str, recipient: str, kind: str, language: str,
               date_text: str, body: str) -> bytes:
    """A one- or two-page letter: sender, a thin rule, who it is for, the text."""
    headings = LETTER_HEADINGS.get(kind, LETTER_HEADINGS["cover_letter"])
    page = Layout(margin_x=64, margin_y=64)
    page.line(sender, 14.5, bold=True)
    if contact_line:
        page.paragraph(contact_line, 8.6, color=MUTED)
    page.space(8)
    page.page.rule(64, PAGE_WIDTH - 64, page.y)
    page.space(14)
    if recipient:
        page.paragraph(recipient, 10.8, bold=True)
    page.line(f"{headings.get(language) or headings['en']}  ·  {date_text}", 8.8, color=MUTED)
    page.space(14)
    for paragraph in str(body or "").split("\n"):
        if paragraph.strip():
            page.paragraph(paragraph, 11)
        else:
            page.space(7)
    return build_pdf(page.pages, headings.get(language) or headings["en"])

