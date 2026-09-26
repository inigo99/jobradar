# Security

JobRadar runs on your own machine and holds personal data: your CV, your job
search, and — if you connect them — your mailbox and API keys. Reports that
help keep that safe are very welcome.

## Reporting a vulnerability

Please **do not open a public issue**. Report it privately through GitHub:
**Security → Report a vulnerability** on
[the repository](https://github.com/inigo99/jobradar/security/advisories/new).
Say what an attacker can do, and how to reproduce it. You will get an answer
within a week.

## What is in scope

- The dashboard: it has no login and is meant to be reached from your own
  machine only. Anything that lets another site, another user on the network
  or a crafted job ad read or change your data is in scope (the Host and
  Origin checks in `web/app.py` exist for this).
- Anything that sends your data somewhere you did not configure.
- The mailbox reader, which must never change your mail (read-only, `BODY.PEEK`).

Publishing the dashboard to a network yourself, without something that
authenticates in front of it, is not a vulnerability — the README and
`docs/SCHEDULING.md` warn against it.

## Supported versions

Only the latest release gets fixes.
