# Data Model: Tweet → WhatsApp Relay

## Entity: `Tweet`

One retrieved post, **after** validation. An object of this type is by construction
safe to deliver — every field has already been checked. Invalid input never becomes a
`Tweet`; it is discarded at the boundary (§4).

| Field | Type | Invariants |
|-------|------|-----------|
| `id` | `int` | > 0, ≤ 2⁶³-1. Parsed from `guid`. **Not** assumed to increase with `published_at` — a retweet's ID is the original's (F-3) |
| `author` | `str` | Matches `^[A-Za-z0-9_]{1,15}$`. For a retweet/quote, the **original** author, not the monitored account |
| `text` | `str` | 1..10000 chars after normalisation. Control chars except `\n` stripped; bidi-override chars (U+202A-U+202E, U+2066-U+2069) stripped; NFC-normalised |
| `url` | `str` | Exactly `https://x.com/<author>/status/<id>`. Constructed by us from validated parts — never copied from the feed (DD-5) |
| `published_at` | `datetime` | Timezone-aware UTC. Items with unparseable or >24h-future timestamps are discarded (E-12) |
| `kind` | `TweetKind` | See below |

### Enum: `TweetKind`

| Value | Detection | Default delivered? |
|-------|-----------|-------------------|
| `REPLY` | Title begins `R to @` | ❌ (AC-2.3) |
| `RETWEET` | Title begins `RT by @` **or** link author != monitored handle | ✅ (AC-2.1) |
| `QUOTE` | Own author, no prefix, body embeds another post | ✅ (D-1) |
| `ORIGINAL` | Everything else | ✅ |

Evaluated **in the order listed**. Both retweet conditions are needed: the account
retweets itself, so link-author-differs alone misses self-retweets. See plan
Amendment A-1.

## Entity: `RelayState`

Persisted at `/data/seen.json`. The **only** mutable durable state.

| Field | Type | Invariants |
|-------|------|-----------|
| `handle` | `str` | The account this history belongs to. A mismatch means the operator retargeted → treat as fresh state, re-bootstrap (AC-5.1) |
| `seen_ids` | `list[int]` | Newest-first, **max 300** (DD-2), unique. Membership-tested, never `max()`-tested (DD-1) |
| `bootstrapped` | `bool` | False until the first check completes. Gates the once-per-account liveness message (D-2, AC-3.3) |
| `outage_notified` | `bool` | True while an unresolved total-source outage has already been reported. Edge-triggers FR-10 (DD-6, AC-4.3) |
| `last_success` | `datetime \| None` | Last check that retrieved posts. Drives the container healthcheck |

### Durability rules

- Written atomically: temp file in the same directory, then `os.replace`. A crash
  mid-write leaves the previous valid file intact (E-6).
- An exclusive file lock is held across read-modify-write, so concurrent processes on
  one volume cannot lose updates (E-17).
- Unreadable, invalid, or schema-mismatched state is **not** fatal: log at ERROR,
  treat as fresh, re-bootstrap. Never crash-loop (E-16). Re-bootstrapping suppresses
  history rather than replaying it, so corruption cannot cause a delivery flood.

## Entity: `Config`

Immutable, from environment. Validated at startup; invalid config refuses to start
with a specific message (AC-5.2).

| Variable | Type | Default | Validation |
|----------|------|---------|-----------|
| `X_PROFILE_URL` | str | *required* | Accepts `https://x.com/<h>`, `https://twitter.com/<h>`, `@h`, `h`. Host must be x.com/twitter.com if a URL. Extracted handle must match `^[A-Za-z0-9_]{1,15}$` — also the path-injection control (E-20) |
| `CALLMEBOT_PHONE` | str | *required* | E.164, `^\+[1-9]\d{7,14}$` |
| `CALLMEBOT_APIKEY` | secret | *required* | Non-empty. Never logged (FR-13) |
| `INCLUDE_RETWEETS` | bool | `true` | |
| `INCLUDE_REPLIES` | bool | `false` | |
| `INCLUDE_QUOTES` | bool | `true` | D-1 |
| `POLL_INTERVAL_SECONDS` | int | `900` | 60..86400 |
| `MAX_MESSAGES_PER_RUN` | int | `10` | 1..50 (DD-7) |
| `NITTER_INSTANCES` | list[str] | 4 verified mirrors | Comma-separated. **https only**; private/loopback/link-local hosts rejected (E-20) |
| `MAX_FEED_BYTES` | int | `5242880` | Cap enforced during download, before parse (E-9) |
| `REQUEST_TIMEOUT_SECONDS` | float | `15.0` | Bounded wait per request (E-18) |
| `STATE_PATH` | path | `/data/seen.json` | |
| `VERIFY_ACROSS_INSTANCES` | bool | `false` | Cross-mirror agreement check |
| `LOG_LEVEL` | str | `INFO` | |

## Message rendering

```
🔁 RT @originalauthor          ← kind marker, omitted for ORIGINAL
<text, truncated to 900 chars with "…">
https://x.com/<author>/status/<id>
```

The link is appended **after** truncation, so it always survives (E-13). The whole
message is passed as a single encoded parameter — text can never alter request
structure (E-11, FR-13).
