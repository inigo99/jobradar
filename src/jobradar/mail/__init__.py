"""Replies to applications, read from the user's inbox (read-only IMAP).

``check_mail`` is the entry point; see ``sync.py`` for how a message is tied
to a job and ``classify.py`` for how its meaning is decided.
"""

from .sync import MailReport, check_mail, interview_ics

__all__ = ["MailReport", "check_mail", "interview_ics"]
