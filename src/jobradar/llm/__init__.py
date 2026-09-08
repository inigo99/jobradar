"""Optional language-model support.

Nothing in JobRadar requires a model. With ``llm.provider = "none"`` the whole
pipeline runs on the deterministic paths in ``textutils`` and ``taxonomy``: it
still searches, filters, prices, scores, renders a tailored CV and tracks
applications. What a model adds is judgement — reading an ad the way a person
would, and writing a summary in the candidate's own material rather than from a
template.

The client speaks plain HTTP to whichever provider is configured, so enabling a
model adds no Python dependency.
"""

from .client import LLMClient, build_client

__all__ = ["LLMClient", "build_client"]
