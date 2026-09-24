"""The errors JobRadar reports to the user on purpose.

Every failure a user can cause or fix — a missing file, a malformed config, an
unwritable data directory, an optional package that is not installed — is
raised as a :class:`JobRadarError` subclass carrying two things: a ``message``
saying what went wrong, in plain words, and a ``hint`` saying what to do about
it. The command line prints both and exits non-zero; the dashboard returns them
as JSON with the subclass's HTTP status. Anything that is *not* one of these is
a bug, and is reported as such (with the traceback in the log, never in the
response).

Failures that must not stop a run — one job board down, a language model
timing out, a digest that could not be delivered — are still handled where
they happen and logged, not raised: a nightly search that dies because one of
ten boards is unreachable is worse than one that reports it and carries on.
"""

from __future__ import annotations


class JobRadarError(Exception):
    """Base class: an expected failure with a message and a way out."""

    #: HTTP status the dashboard answers with for this kind of failure.
    status_code: int = 500
    #: Process exit code the command line returns for it.
    exit_code: int = 1

    def __init__(self, message: str, hint: str = ""):
        super().__init__(message)
        self.message = message
        self.hint = hint

    def __str__(self) -> str:
        return self.message

    def to_dict(self) -> dict[str, str]:
        """The JSON body the dashboard returns."""
        payload = {"detail": self.message, "error": type(self).__name__}
        if self.hint:
            payload["hint"] = self.hint
        return payload


class ConfigError(JobRadarError):
    """Settings that cannot be read, parsed or validated."""

    status_code = 400
    exit_code = 2


class SetupRequiredError(JobRadarError):
    """The operation needs onboarding (settings or a profile) done first."""

    status_code = 409
    exit_code = 2


class NotFoundError(JobRadarError):
    """A job, document or filtered entry that does not exist."""

    status_code = 404
    exit_code = 2


class MissingDependencyError(JobRadarError):
    """An optional extra (PDF parsing, Excel, ...) that is not installed."""

    status_code = 501
    exit_code = 2


class ProfileError(JobRadarError):
    """A CV that cannot be read or turned into a profile."""

    status_code = 400
    exit_code = 2


class StorageError(JobRadarError):
    """The data directory or the SQLite database cannot be used."""

    status_code = 500


class LLMError(JobRadarError):
    """The language-model provider is misconfigured.

    The pipeline itself never raises it — a model that cannot be used is
    logged and skipped — but code that requires a model can.
    """

    status_code = 502


class MailError(JobRadarError):
    """The mail server cannot be reached or refuses the login."""

    status_code = 502


class RenderError(JobRadarError):
    """A CV or document that cannot be rendered or written to disk."""

    status_code = 500


class ExportError(JobRadarError):
    """An export file that cannot be written."""

    status_code = 500


def describe_os_error(exc: OSError) -> str:
    """``[Errno 13] Permission denied: 'x'`` -> ``permission denied``."""
    reason = exc.strerror or str(exc) or type(exc).__name__
    return reason[0].lower() + reason[1:] if reason else "unknown error"


__all__ = [
    "ConfigError",
    "ExportError",
    "JobRadarError",
    "LLMError",
    "MailError",
    "MissingDependencyError",
    "NotFoundError",
    "ProfileError",
    "RenderError",
    "SetupRequiredError",
    "StorageError",
    "describe_os_error",
]
