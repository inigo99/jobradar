"""JobRadar — a self-hosted job radar with honest CV tailoring.

The package is organised in layers, each of which can be used on its own:

``jobradar.models``      Plain data structures shared by every layer.
``jobradar.config``      User settings, filters and where files live on disk.
``jobradar.storage``     SQLite persistence for jobs, applications and settings.
``jobradar.sources``     Pluggable job-board adapters.
``jobradar.pipeline``    Search orchestration: dedupe, filter, salary, scoring.
``jobradar.profile``     Importing an existing CV into a structured profile.
``jobradar.documents``   Tailoring and rendering the CV, cover letter and email.
``jobradar.lint``        The recruiter red-flag linter.
``jobradar.llm``         Optional, provider-agnostic language-model client.
``jobradar.web``         The local dashboard (FastAPI + a single-page UI).
"""

__version__ = "1.4.0"
__all__ = ["__version__"]
