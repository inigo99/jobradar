"""Reading the inbox over IMAP — read-only, standard library only.

Configuration comes from the environment, never from the database:

``JOBRADAR_IMAP_HOST``      e.g. ``imap.gmail.com``, ``outlook.office365.com``
``JOBRADAR_IMAP_USER``      the address
``JOBRADAR_IMAP_PASSWORD``  an *app password* (Gmail and Outlook require one
                            for IMAP when two-step verification is on)
``JOBRADAR_IMAP_PORT``      optional, default 993 (IMAP over TLS)
``JOBRADAR_IMAP_FOLDER``    optional, default ``INBOX``; on Gmail,
                            ``[Gmail]/All Mail`` also sees archived replies

The mailbox is opened with ``EXAMINE`` (read-only) and bodies are fetched with
``BODY.PEEK``, so checking mail never marks anything as read, moves it or
changes a flag.
"""

from __future__ import annotations

import email
import imaplib
import logging
import os
import re
from dataclasses import dataclass
from datetime import date, datetime, timezone
from email.header import decode_header, make_header
from email.message import Message
from email.utils import parseaddr, parsedate_to_datetime

from ..errors import ConfigError, MailError
from ..textutils import strip_html

log = logging.getLogger(__name__)

#: How many of the newest matching messages are read in one check.
MAX_MESSAGES = 400
#: Body text kept per message: replies say what they mean near the top.
BODY_LIMIT = 6000


@dataclass
class MailMessage:
    message_id: str
    received_at: datetime
    sender_name: str
    sender_address: str
    subject: str
    body: str
    #: Opens the thread in the web client, when the provider has one (Gmail).
    link: str = ""

    @property
    def sender(self) -> str:
        return f"{self.sender_name} <{self.sender_address}>" if self.sender_name \
            else self.sender_address


@dataclass(frozen=True)
class ImapConfig:
    host: str
    user: str
    password: str
    port: int = 993
    folder: str = "INBOX"

    @classmethod
    def from_environment(cls) -> ImapConfig:
        """Read the ``JOBRADAR_IMAP_*`` variables, or explain what is missing."""
        host = os.environ.get("JOBRADAR_IMAP_HOST", "").strip()
        user = os.environ.get("JOBRADAR_IMAP_USER", "").strip()
        password = os.environ.get("JOBRADAR_IMAP_PASSWORD", "")
        missing = [name for name, value in (("JOBRADAR_IMAP_HOST", host),
                                            ("JOBRADAR_IMAP_USER", user),
                                            ("JOBRADAR_IMAP_PASSWORD", password)) if not value]
        if missing:
            raise ConfigError(
                f"Reading your email needs {', '.join(missing)}.",
                hint="Add them to .env (see .env.example). Use an app password, not your "
                     "normal one.",
            )
        raw_port = os.environ.get("JOBRADAR_IMAP_PORT", "993").strip() or "993"
        try:
            port = int(raw_port)
        except ValueError:
            raise ConfigError(f"JOBRADAR_IMAP_PORT={raw_port!r} is not a port number.") from None
        folder = os.environ.get("JOBRADAR_IMAP_FOLDER", "").strip() or "INBOX"
        return cls(host=host, user=user, password=password, port=port, folder=folder)


def configured() -> bool:
    """Whether the ``JOBRADAR_IMAP_*`` variables needed to read mail are set."""
    return all(os.environ.get(name) for name in
               ("JOBRADAR_IMAP_HOST", "JOBRADAR_IMAP_USER", "JOBRADAR_IMAP_PASSWORD"))


def _decoded(value: str | None) -> str:
    """A header value with any RFC 2047 encoded words decoded."""
    if not value:
        return ""
    try:
        return str(make_header(decode_header(value)))
    except (ValueError, UnicodeDecodeError, LookupError):
        return value


def body_text(message: Message) -> str:
    """The readable text of a message: the plain part, or the HTML one stripped."""
    plain: list[str] = []
    html: list[str] = []
    for part in message.walk() if message.is_multipart() else [message]:
        if part.get_content_maintype() == "multipart" or part.get_filename():
            continue
        try:
            payload = part.get_payload(decode=True)
        except (ValueError, TypeError):
            continue
        if not isinstance(payload, bytes):
            continue
        charset = part.get_content_charset() or "utf-8"
        try:
            text = payload.decode(charset, errors="replace")
        except LookupError:
            text = payload.decode("utf-8", errors="replace")
        (html if part.get_content_type() == "text/html" else plain).append(text)
    text = "\n".join(plain) if plain else strip_html("\n".join(html))
    return text[:BODY_LIMIT]


def parse_message(raw: bytes, gmail_thread: str = "") -> MailMessage | None:
    message = email.message_from_bytes(raw)
    try:
        received = parsedate_to_datetime(message.get("Date", ""))
    except (TypeError, ValueError, IndexError):
        received = None
    if received is None:
        return None
    if received.tzinfo is None:
        received = received.replace(tzinfo=timezone.utc)
    name, address = parseaddr(_decoded(message.get("From")))
    link = f"https://mail.google.com/mail/u/0/#all/{gmail_thread}" if gmail_thread else ""
    return MailMessage(
        message_id=(message.get("Message-ID") or "").strip(),
        received_at=received,
        sender_name=name.strip(),
        sender_address=address.strip().lower(),
        subject=" ".join(_decoded(message.get("Subject")).split()),
        body=body_text(message),
        link=link,
    )


_GMAIL_THREAD = re.compile(rb"X-GM-THRID (\d+)")


def fetch_since(config: ImapConfig, since: date, limit: int = MAX_MESSAGES) -> list[MailMessage]:
    """Messages received on or after ``since``, newest first.

    Raises :class:`MailError` when the server cannot be reached or refuses
    the login, with the provider-specific fix when there is one.
    """
    try:
        client = imaplib.IMAP4_SSL(config.host, config.port, timeout=30)
    except (TimeoutError, OSError) as exc:
        raise MailError(
            f"Cannot connect to the mail server {config.host}:{config.port}: {exc}.",
            hint="Check JOBRADAR_IMAP_HOST and JOBRADAR_IMAP_PORT (usually 993).",
        ) from exc
    try:
        try:
            client.login(config.user, config.password)
        except imaplib.IMAP4.error as exc:
            raise MailError(
                f"{config.host} refused the login for {config.user}.",
                hint="Use an app password (Gmail: myaccount.google.com/apppasswords; Outlook: "
                     "account security settings), and check IMAP is enabled for the account.",
            ) from exc
        status, _ = client.select(_quote(config.folder), readonly=True)
        if status != "OK":
            raise MailError(f"The folder {config.folder!r} does not exist on {config.host}.",
                            hint="Check JOBRADAR_IMAP_FOLDER, or leave it empty for INBOX.")
        status, data = client.search(None, "SINCE", since.strftime("%d-%b-%Y"))
        if status != "OK" or not data or not data[0]:
            return []
        ids = data[0].split()[-limit:]
        gmail = "gmail" in config.host.lower() or "googlemail" in config.host.lower()
        fields = "(BODY.PEEK[] X-GM-THRID)" if gmail else "(BODY.PEEK[])"
        messages: list[MailMessage] = []
        for message_id in reversed(ids):
            status, parts = client.fetch(message_id, fields)
            if status != "OK" or not parts:
                continue
            for part in parts:
                if not isinstance(part, tuple):
                    continue
                meta, raw = part
                thread = _GMAIL_THREAD.search(meta or b"")
                parsed = parse_message(raw, format(int(thread.group(1)), "x") if thread else "")
                if parsed is not None:
                    messages.append(parsed)
        return messages
    except imaplib.IMAP4.error as exc:
        raise MailError(f"The mail server {config.host} answered with an error: {exc}.") from exc
    except (TimeoutError, OSError) as exc:
        raise MailError(f"The connection to {config.host} dropped: {exc}.",
                        hint="Try again; if it keeps happening, check your network.") from exc
    finally:
        try:
            client.logout()
        except (imaplib.IMAP4.error, OSError):
            pass


def _quote(folder: str) -> str:
    """IMAP folder names with spaces or brackets must be quoted."""
    return f'"{folder}"' if re.search(r'[\s\[\]"]', folder) else folder
