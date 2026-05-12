# Telegram Screenshot OCR Bot

Lightweight Telegram bot that turns publisher screenshots into Google Sheets rows.
Publisher uploads a screenshot, the bot OCRs it with Google Vision, extracts
`customer_name / phone / transaction_id`, and appends a row to the campaign's
Google Sheet alongside a link to the original screenshot.

> Status: scaffold + bot bootstrap (M1 + M2). OCR / sheets / storage modules
> arrive in later milestones — see `/root/.claude/plans/` for the full plan.

## Commands

| Command | Who | What |
|---|---|---|
| `/start` | anyone | greeting + quick help |
| `/help` | anyone | command reference |
| `/campaign <name>` | publisher | set the active campaign for your uploads *(M3)* |
| `/today` | publisher | count of your uploads today *(M3)* |
| `/reload` | super admin | reload the campaigns control sheet *(M4)* |

## Architecture (target)

- **aiogram v3** long-poll, single async worker
- **Google Vision** `document_text_detection` for OCR
- **gspread** for Sheets append (1 queue worker + backoff)
- **Telegram private channel** as image storage (bot forwards uploads there,
  stores the `t.me/c/<id>/<msg>` link — admins viewing the sheet must be members
  of that channel)
- **SQLite** (aiosqlite) for `user → campaign` mapping, dedup, daily counts
- **Control sheet** lists campaigns with their target sheet ID, regex per
  campaign, admin chat, storage channel — editable at runtime, hot-reload via
  `/reload`

## Local development

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env  # fill BOT_TOKEN at minimum
python -m app.main
```

## Deploy (Fly.io)

```bash
fly launch --no-deploy        # generates app, attaches region sin
fly volumes create bot_data --size 1 --region sin
fly secrets set BOT_TOKEN=... CONTROL_SHEET_ID=... SUPER_ADMIN_IDS=...
fly secrets set GOOGLE_APPLICATION_CREDENTIALS_JSON="$(cat sa.json)"  # see runbook
fly deploy
```

Single shared-cpu-1x VM, 256MB RAM, 1GB persistent volume mounted at `/data`
for the SQLite file. Long-poll worker so no public HTTPS endpoint needed.

## Repo layout

```
app/
  main.py           entrypoint
  config.py         pydantic-settings env loader
  bot.py            Bot/Dispatcher factory
  handlers/         aiogram handlers (commands, photo, errors)
  services/         campaigns, ocr, parser, sheets, storage, state, notifier
  models/           dataclasses + enums
  utils/            logging, regex_lib
migrations/         SQL migrations
tests/              pytest unit tests
Dockerfile / fly.toml
```
