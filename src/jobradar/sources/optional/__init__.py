"""Opt-in source adapters.

Everything in this package reads pages that were built for human visitors
rather than for programmatic access. They are **disabled by default** and are
never switched on automatically: the user must enable each one explicitly, in
`settings.sources.enabled`, having read `tos_note`.

Why they exist at all: for many people the national boards are where the jobs
actually are, and a tool that ignores them is not useful. Why they are off by
default: whether automated access is acceptable is a decision for the person
running the software on their own behalf, under their own jurisdiction and the
site's terms — not a default the project should make for them.

If you enable one, keep `request_delay` generous, keep `respect_robots` on, and
use it at the volume of a person doing their own job search.
"""
