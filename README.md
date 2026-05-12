# Telegram Screenshot OCR Bot

Lightweight Telegram bot that turns publisher screenshots into Google Sheets rows.
Publisher uploads a screenshot, the bot OCRs it with Google Vision, extracts
`customer_name / phone / transaction_id`, and appends a row to the campaign's
Google Sheet alongside a link to the original screenshot.

## Commands

| Command | Who | What |
|---|---|---|
| `/start` | anyone | greeting + quick help |
| `/help` | anyone | command reference |
| `/campaign <name>` | publisher | set the active campaign for your uploads |
| `/campaign` | publisher | show current campaign + list active |
| `/today` | publisher | count of your uploads today |
| `/reload` | super admin | reload the campaigns control sheet |
| `/deadletter` | super admin | list the 10 most recent unresolved failures |
| `/resolve <id>` | super admin | mark a dead-letter entry resolved |

Any photo (or album) sent in DM is treated as a screenshot upload for the
publisher's currently selected campaign.

## Architecture

- **aiogram v3** long-poll, single async worker
- **Google Vision** `document_text_detection` for OCR (lazy client, 3-attempt retry)
- **gspread** for Sheets append (1 background queue worker + tenacity backoff;
  failed rows land in a SQLite `dead_letter` table for manual replay)
- **Telegram private channel** as image storage (bot forwards uploads there,
  stores the `t.me/c/<id>/<msg>` link — admins viewing the sheet must be members
  of that channel)
- **SQLite** (aiosqlite) for `user → campaign` mapping, dedup, daily counts,
  and the dead-letter queue
- **Control sheet** lists campaigns with their target sheet ID, regexes,
  admin chat, storage channel — editable at runtime, hot-reload via `/reload`

### Upload flow

```
on_photo
 ├─ state.get_campaign(user) ─────────── nag /campaign if missing
 ├─ campaigns.get(name) ──────────────── reject if inactive / unknown
 ├─ state.exists_upload(file_unique_id) → "đã ghi nhận" if duplicate
 ├─ placeholder "⏳ Đang xử lý..."
 ├─ asyncio.gather:
 │    forward_to_storage_channel    → StoredRef (chat_id, msg_id, link)
 │    bot.download(file_id)         → bytes
 ├─ ocr.extract_text(bytes)         → raw_text  (or "" on error)
 ├─ parser.extract_fields(text, camp) → ParsedData + status
 ├─ sheets.enqueue(row)             → async append, retried in worker
 ├─ state.insert_upload(...)
 └─ edit placeholder + notifier.notify_admin if PARTIAL/FAILED
```

Failures at any I/O step are recorded in `dead_letter` and surfaced to the
campaign admin chat — the user still gets a reply.

## Configuration

### `.env` / environment variables

```
BOT_TOKEN=                            # @BotFather token
GOOGLE_APPLICATION_CREDENTIALS=/app/secrets/sa.json
CONTROL_SHEET_ID=                     # spreadsheet ID of the master control sheet
SUPER_ADMIN_IDS=123,456               # telegram user ids that can /reload, /deadletter, /resolve
SQLITE_PATH=/data/app.db              # persisted on a volume in production
CAMPAIGN_CACHE_TTL_SEC=300
TZ=Asia/Ho_Chi_Minh
LOG_LEVEL=INFO
```

On hosts where you can't ship a JSON file, set `GOOGLE_APPLICATION_CREDENTIALS_JSON`
to the raw JSON blob — the entrypoint (and `app/main.py` as a safety net) will
materialize it to disk at `GOOGLE_APPLICATION_CREDENTIALS`.

### Control sheet — `campaigns` tab

| campaign_name | active | sheet_id | worksheet | admin_chat_id | storage_channel_id | txid_regex | name_regex | phone_regex | notes |
|---|---|---|---|---|---|---|---|---|---|
| `msb` | `TRUE` | `1AbC…` | `data` | `-1001111111111` | `-1002222222222` | `MSB\d{12}` | `Người nhận:\s*(.+)` |  | first campaign |

- `active=TRUE` rows are the only ones a publisher can pick.
- `worksheet` defaults to `data` if blank; the worksheet is auto-created on
  first append with the column headers below.
- `txid_regex` / `name_regex` / `phone_regex` are optional. If the regex has
  a capture group, the first group's value is used; otherwise the full match.
- `phone_regex` falls back to a built-in VN mobile matcher.
- Bad regexes are ignored (logged + fallback used) so a typo in the sheet
  doesn't take the bot offline.

### Per-campaign data tab columns

```
timestamp | telegram_user_id | telegram_username | customer_name | phone |
transaction_id | screenshot_link | raw_ocr_text | status
```

`status` is `OK` (all 3 fields parsed), `PARTIAL` (1–2 fields), or `FAILED`
(0 fields / OCR failed).

### Regex examples

```
# MoMo transaction id
txid_regex = MOMO\d{10,12}

# Generic "Mã giao dịch: XYZ123"
txid_regex = Mã giao dịch:\s*([A-Z0-9\-]+)

# Customer name after a Vietnamese label
name_regex = (?:Người nhận|Người thụ hưởng|Tên):\s*(.+)

# Strict VN phone (overrides the built-in fallback)
phone_regex = 0(?:3|5|7|8|9)\d{8}
```

## Runbook

### 1. Service account + sheet wiring

1. GCP project → enable **Cloud Vision API** and **Google Sheets API**.
2. Create a service account, download the JSON key. The same SA is used for
   both Vision and Sheets.
3. Share the **control sheet** (`CONTROL_SHEET_ID`) and **every campaign data
   spreadsheet** with the SA email as **Editor**.
4. Drop the JSON at `GOOGLE_APPLICATION_CREDENTIALS`, or set
   `GOOGLE_APPLICATION_CREDENTIALS_JSON` env var with the raw blob.

### 2. Storage channel

1. Create a **private Telegram channel** per campaign (or share one across).
2. Add the bot as **admin** with `can_post_messages`.
3. Put the channel id (`-100…`) into the campaign row's `storage_channel_id`.
4. Every admin who needs to click `screenshot_link` from the sheet must be a
   member of that channel — links don't resolve for non-members.

### 3. Local development

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env  # fill BOT_TOKEN at minimum
python -m app.main
```

Run tests:

```bash
pytest -q
```

### 4. Deploy (Fly.io)

```bash
fly launch --no-deploy
fly volumes create bot_data --size 1 --region sin
fly secrets set BOT_TOKEN=... CONTROL_SHEET_ID=... SUPER_ADMIN_IDS=...
fly secrets set GOOGLE_APPLICATION_CREDENTIALS_JSON="$(cat sa.json)"
fly deploy
```

Single shared-cpu-1x VM, 256MB RAM, 1GB persistent volume mounted at `/data`
for the SQLite file. Long-poll worker so no public HTTPS endpoint needed.

### 5. Smoke test

1. `fly logs` — expect `bot_started …`.
2. `/start` → greeting.
3. `/campaign <valid_name>` → confirmation with sheet link; invalid → list of
   active campaigns.
4. DM a real screenshot → channel gets the forward, sheet gets a row, the
   `screenshot_link` opens the forwarded message.
5. DM the *same* screenshot again → "đã ghi nhận" dedup reply.
6. `/reload` (super admin) → `✓ Đã reload. N chiến dịch active.`
7. `/deadletter` (super admin) → empty list on a healthy run.
8. Kick bot from the storage channel, upload again → admin chat receives a
   dead-letter alert; `/deadletter` shows the entry; `/resolve <id>` clears it.
9. `fly machine stop` / start → SQLite mapping survives.

## Repo layout

```
app/
  main.py             entrypoint (lifecycle: state, campaigns, sheets worker)
  config.py           pydantic-settings env loader
  bot.py              Bot/Dispatcher factory
  handlers/
    commands.py       /start /help /campaign /today /reload /deadletter /resolve
    photo.py          screenshot upload pipeline
    errors.py         global error handler
  services/
    campaigns.py      control sheet loader + TTL cache
    ocr.py            Google Vision wrapper (lazy client + retry)
    parser.py         pure regex/heuristic field extractor
    sheets.py         async append queue + backoff + dead-letter on failure
    storage.py        forward to private channel + t.me/c/ link builder
    state.py          aiosqlite DAO (users_campaign, uploads, dead_letter)
    notifier.py       admin chat ping (partial / dead-letter)
  models/             dataclasses + UploadStatus enum
  utils/              structlog config, regex helpers
migrations/           SQL migrations
tests/                pytest unit tests (parser, state, campaigns, storage, ocr)
Dockerfile / fly.toml
```

## Cost ballpark (1k images/day = 30k/month)

| Item | Cost |
|---|---|
| Vision `document_text_detection` (after 1k/month free) | ~$43.5/mo |
| Google Sheets API | $0 |
| Fly.io shared-cpu-1x 256MB + 1GB volume | $0 (free tier) |
| Telegram Bot API | $0 |
| **Total** | **~$44/mo** |

Tips: resize >1600px screenshots before Vision; pre-filter < 50KB / non-image
uploads; dedup short-circuits Vision entirely on retries.
