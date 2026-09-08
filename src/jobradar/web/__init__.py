"""The local dashboard.

A small FastAPI application serving one page on ``localhost``. It exists for
three reasons a command line cannot cover: the first-run wizard that collects
the user's details, the settings screen that keeps them editable, and the
tracking board where applications live.

Everything it reads and writes goes through the same SQLite store as the CLI,
so a job marked applied in the browser is applied in ``jobradar export`` too.
Nothing is sent anywhere: the server binds to loopback by default and the only
outbound requests are the ones the pipeline makes to job boards.
"""

from .app import create_app, serve

__all__ = ["create_app", "serve"]
