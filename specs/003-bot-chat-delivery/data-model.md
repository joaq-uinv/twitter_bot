# Data Model: Bot Chat Delivery & Commands

Only what changes. Every 001 and 002 entity not listed here is unchanged.

## `Tweet` (changed, 001)

| Field | Change |
|---|---|
| `text` | May now be `""` after `clean_text` (spec US-7, DD-15). Still capped at `MAX_TEXT`. Every other invariant (id range, `HANDLE_RE` author, tz-aware time, kind) is unchanged and still raises `ValueError` |
| `preview_url` (new property) | `https://fxtwitter.com/{author}/status/{id}`, built from the validated `author` and `id` only (DD-4). Never derived from feed links |

## `RelayState` (changed, `state/seen.json`)

New fields. All are optional in the file: a file written before 003 loads with the
defaults below, so no migration step exists (DD-10).

| Field | Type | Default | Invariant / validation on load |
|---|---|---|---|
| `paused_since` | ISO-8601 tz-aware datetime or `null` | `null` | Unparseable or naive → `null` (resume is the safe direction: a lost pause delivers posts, a stuck pause hides them silently), logged at ERROR |
| `update_offset` | int ≥ 0 | `0` | Not an int, a bool, or negative → `0`, logged at ERROR. `0` means "everything Telegram still holds" (≤ 24 h), so a reset can only re-handle commands from the last day, which are idempotent apart from repeated replies |
| `announced` | bool | `false` | Strict bool; anything else → `false` (at worst one extra "now delivering here") |
| `last_check` | `{"at": datetime, "sent": int ≥ 0}` or `null` | `null` | Any invalid part → `null`; `/status` then says "none yet" (E-17) |

Re-bootstrap (unreadable file, changed handle) resets these to defaults along with
the delivered set, as today (001 E-16).

## `IncomingMessage` (new, `commands.py`)

Built from one Bot API `Update`. Anything that does not fit is skipped, never raised.

| Field | Source | Validation |
|---|---|---|
| `update_id` | `update.update_id` | int, > 0, not bool. Missing or invalid → the update is skipped; `InboxBatch.next_offset` still moves past it when a later valid id exists |
| `chat_id` | `update.message.chat.id` | int, not bool. The **only** identity used (spec E-5) |
| `chat_type` | `update.message.chat.type` | str |
| `text` | `update.message.text` | str, or `""` if absent (stickers, photos). Truncated to 4096 chars before anything else touches it |

`is_from_operator` ⇔ `chat_id == TELEGRAM_CHAT_ID and chat_type == "private"`.
Messages that fail it are discarded before parsing: their fields are never logged,
stored or compared to anything else (FR-7).

## `Command` (new)

`StrEnum`: `STATUS`, `PAUSE`, `RESUME`, `HELP`, `UNKNOWN`.

`parse(text) -> Command`: regex in DD-12 on `text[:64]`, case-insensitive. Anything
else, including empty text, is `UNKNOWN`. Pure; no I/O.

## Replies (new, `formatter.py` / `commands.py`)

Fixed templates. The only variable parts are numbers, times we produced, validated
handles and our own status page URL. Operator text is never interpolated (FR-11).

| Command | Reply |
|---|---|
| `/status` | "Last check: {time UTC or 'none yet'}, delivered {n}. Waiting: {k or 'unknown, sources unavailable'}. Deliveries: {running \| paused since {time}}. Mirrors: {h} of {t} healthy \| health check not available. {STATUS_PAGE_URL}" |
| `/pause` | "⏸ Paused. Send /resume to start again." / "Already paused since {time}." |
| `/resume` | "▶️ Resumed. {k} posts waiting; up to {cap} arrive now." (+ "Posts from early in the pause may no longer be retrievable." when AC-4.5 holds) / "Already running." |
| `/help` | The four commands, one line each, and "Replies arrive at the next check, which can take minutes or hours." |
| unknown | "I don't know that one. Send /help." |

## Mirror-health input (read-only)

`MIRROR_LATEST_PATH` (default `/data/mirror-latest.json`): 002's `latest.json`,
loaded with `mirrors.history._latest_from_json`. Missing, unreadable or invalid →
"not available" (AC-3.2). Only `in_use_healthy` and `in_use_total` are used.

## Configuration (changed)

| Variable | Type | Validation |
|---|---|---|
| `TELEGRAM_BOT_TOKEN` | SecretStr | `^\d{5,12}:[A-Za-z0-9_-]{30,64}$`. Blank allowed for `check-source`; required by commands that deliver (`require_delivery`). The error never echoes the value |
| `TELEGRAM_CHAT_ID` | str of an int | `^-?\d{1,20}$`; required with the token. Treated as a secret (FR-16) |
| `STATUS_PAGE_URL` | str | `https://` URL; default `https://joaq-uinv.github.io/twitter_bot/` |
| `MIRROR_LATEST_PATH` | str | path; default `/data/mirror-latest.json` |
| `CALLMEBOT_PHONE`, `CALLMEBOT_APIKEY` | — | **Removed.** If still present in `.env` they are ignored (`extra="ignore"`) |

## Result line (changed)

`sent= withheld= failed= bootstrapped= outage= paused= dry_run=`. `paused=True`
when the check ended paused. `report.py` matches the new field; a log without it
(older runs) still parses with `paused` unknown.
