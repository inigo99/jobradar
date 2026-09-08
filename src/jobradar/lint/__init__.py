"""The recruiter red-flag linter.

A senior recruiter spends somewhere between six and thirty seconds on a first
pass, and in that time they are not reading — they are scanning for reasons to
stop. This package encodes the reasons that are mechanically detectable, so
they get caught before the CV is sent rather than after it is ignored.

Findings are advice, never edits: JobRadar reports what a reader will notice and
leaves the judgement to the person whose career it is.
"""

from .rules import LintResult, lint_profile, lint_tailored

__all__ = ["LintResult", "lint_profile", "lint_tailored"]
