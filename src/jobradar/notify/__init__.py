"""Digests.

The point of a scheduled search is not having to check anything. That only
works if the run can reach you when it finds something, so JobRadar can send a
short digest by email or Telegram — and, importantly, sends nothing at all when
there is nothing new. A daily "0 new jobs" message trains you to ignore it.
"""

from .digest import build_digest, send_digest

__all__ = ["build_digest", "send_digest"]
