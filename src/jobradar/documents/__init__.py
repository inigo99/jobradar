"""Producing the documents: the tailored CV, the cover letter and the email.

The division of labour is the point of this package. Achievements are the
candidate's own words, written once in the profile and only ever *reordered*
for a job. What gets adapted per job is the framing: the headline, the summary,
which achievements lead, and which skill groups come first. Nothing that
appears on a generated CV can come from anywhere but the profile, and
:mod:`~jobradar.documents.validator` checks that after the fact rather than
trusting it.
"""

from .letters import generate_cover_letter, generate_email
from .render import render_cv
from .tailor import TailoredCV, tailor
from .validator import ValidationReport, validate_document

__all__ = [
    "TailoredCV",
    "tailor",
    "render_cv",
    "generate_cover_letter",
    "generate_email",
    "validate_document",
    "ValidationReport",
]
