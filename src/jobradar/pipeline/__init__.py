"""The search pipeline: collect, deduplicate, filter, price, score.

Each stage is a separate module with no knowledge of the others, so a stage can
be tested — or replaced — on its own. ``search.run`` wires them together.
"""

from .dedupe import deduplicate
from .filters import FilterOutcome, apply_filters, explain
from .salary import ExchangeRates, estimate_salary
from .scoring import score_job
from .search import SearchPipeline, run_search
from .sweep import sweep_closed

__all__ = [
    "deduplicate",
    "apply_filters",
    "explain",
    "FilterOutcome",
    "ExchangeRates",
    "estimate_salary",
    "score_job",
    "SearchPipeline",
    "run_search",
    "sweep_closed",
]
