# Running JobRadar on a schedule

The daily run is `sweep` then `search`: retire the ads that have closed, then
look for new ones. Add `--notify` so you do not have to remember to look.

```bash
jobradar sweep && jobradar search --notify
```

Nothing is sent when the run finds nothing. A daily "0 new jobs" message is one
you learn to ignore, and then you miss the one that matters.

Set `notifications.min_score` in Settings so only jobs worth your attention
trigger a message.

Two things need no extra schedule entry. Sources marked *weekly* in Settings
run only on their weekday, so a daily run is right for them too. And with
**Settings → Email** on, the same `search` reads the replies received since the
last check at the end of the run; a mail server that is down is reported and
never fails the search. `jobradar mail` does it on its own if you prefer a
separate entry.

## cron (Linux, macOS)

```cron
# Every weekday at 08:30. Use absolute paths: cron's PATH is minimal.
30 8 * * 1-5 cd /home/alex/jobradar && /home/alex/jobradar/.venv/bin/jobradar sweep >> data/cron.log 2>&1 && /home/alex/jobradar/.venv/bin/jobradar search --notify >> data/cron.log 2>&1
```

## systemd timer (Linux)

`~/.config/systemd/user/jobradar.service`:

```ini
[Unit]
Description=JobRadar daily search

[Service]
Type=oneshot
WorkingDirectory=%h/jobradar
ExecStart=%h/jobradar/.venv/bin/jobradar sweep
ExecStart=%h/jobradar/.venv/bin/jobradar search --notify
```

`~/.config/systemd/user/jobradar.timer`:

```ini
[Unit]
Description=Run JobRadar every weekday morning

[Timer]
OnCalendar=Mon..Fri 08:30
Persistent=true

[Install]
WantedBy=timers.target
```

```bash
systemctl --user enable --now jobradar.timer
systemctl --user list-timers jobradar        # check it
journalctl --user -u jobradar -n 50          # read the last run
```

`Persistent=true` runs a missed job when the machine comes back, which is what
you want on a laptop.

## Task Scheduler (Windows)

```powershell
$action  = New-ScheduledTaskAction -Execute "C:\dev\jobradar\.venv\Scripts\jobradar.exe" `
                                   -Argument "search --notify" `
                                   -WorkingDirectory "C:\dev\jobradar"
$trigger = New-ScheduledTaskTrigger -Daily -At 8:30am
Register-ScheduledTask -TaskName "JobRadar" -Action $action -Trigger $trigger `
                       -Description "Daily job search"
```

## Docker

```dockerfile
FROM python:3.12-slim
WORKDIR /app
COPY . .
RUN pip install --no-cache-dir -e ".[all]" && playwright install --with-deps chromium
VOLUME ["/app/data"]
EXPOSE 8000
CMD ["jobradar", "serve", "--host", "0.0.0.0"]
```

```bash
docker build -t jobradar .
docker run -d -p 8000:8000 -v "$PWD/data:/app/data" --env-file .env jobradar
```

Binding to `0.0.0.0` puts your CV and your job-search history on the network.
Only do it behind something that authenticates.

## GitHub Actions

Workable, with two caveats: the runner's IP is shared, so boards may rate-limit
it, and the database has to persist between runs. Cache it and keep the schedule
modest.

```yaml
name: Job search

on:
  schedule:
    - cron: "30 7 * * 1-5"      # 07:30 UTC on weekdays
  workflow_dispatch:

jobs:
  search:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - run: pip install -e ".[all]"

      - name: Restore the database
        uses: actions/cache@v4
        with:
          path: data
          key: jobradar-db-${{ github.run_id }}
          restore-keys: jobradar-db-

      - run: jobradar search --notify
        env:
          ADZUNA_APP_ID: ${{ secrets.ADZUNA_APP_ID }}
          ADZUNA_APP_KEY: ${{ secrets.ADZUNA_APP_KEY }}
          ANTHROPIC_API_KEY: ${{ secrets.ANTHROPIC_API_KEY }}
          JOBRADAR_LLM_PROVIDER: anthropic
          JOBRADAR_LLM_MODEL: claude-sonnet-4-5
          TELEGRAM_BOT_TOKEN: ${{ secrets.TELEGRAM_BOT_TOKEN }}
          TELEGRAM_CHAT_ID: ${{ secrets.TELEGRAM_CHAT_ID }}
```

Do not enable restricted sources on shared CI infrastructure. Their terms are a
matter between the site and the person browsing it, and a shared runner is not
that person.

## Keeping the cost bounded

An unattended run with a language model enabled is the one way JobRadar can
spend money without you watching. `llm.max_calls_per_run` (default 60) is a hard
cap per run; beyond it the pipeline finishes on the deterministic path. Setting
`enrich_jobs: false` and leaving `tailor_cv: true` is the cheapest useful
configuration: no model calls during the nightly search, and a model only when
you press "Tailor CV" on a job you actually care about.
