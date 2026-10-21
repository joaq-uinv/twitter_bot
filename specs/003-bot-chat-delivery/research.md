# Research: Bot Chat Delivery & Commands

**Date of probing:** 2026-10-21, about 16:00 UTC, from the operator's machine.
Documentation was read on the same day (Bot API 10.3, changelog dated 2026-08-24).
Telegram's own behaviour with a **real** bot token could not be probed yet: the
operator creates the bot after this plan is approved. Those claims are marked
**doc** and are re-checked during setup (quickstart steps 2–4).

## R-1: Why the old channel stopped (the trigger for this feature)

Every relay run since 2026-10-20 05:07 UTC that reached delivery got this CallMeBot
reply (phone redacted by the relay):

> `… You have 0 messages left. I need your support. Please, subscribe here to continue using CallMeBot. Message not sent`

The relay classified it as an unrecognised response, did not mark the post
delivered, and failed the run (001 A-8). Correct behaviour, but the channel is
gone for a free-only project (001 FR-14).

## R-2: Which messaging platform

Chosen by the operator in conversation (2026-10-21): **Telegram**, private chat with
a bot. Recorded here only for the properties the design relies on:

| Property | Source | Matters for |
|---|---|---|
| Bots are free, with no message quota for a one-to-one chat at our volume (≤ 50 messages/check, ~100/day) | doc (Bots FAQ: about 1 message per second per chat) | FR-18, pacing |
| The bot can **read** messages sent to it by polling (`getUpdates`), with no public server | doc | FR-6, no always-on service (spec Out of Scope) |
| A chat's type is readable (`getChat` → `type` ∈ private, group, supergroup, channel) | doc | D-4, FR-1 |
| Messages are plain text unless `parse_mode` is set | doc | 001 E-11: post text can never change message structure |
| Text limit 1–4096 characters after entity parsing | doc | 001 E-13; the formatter already caps post text at 900 |

## R-3: Telegram Bot API behaviour the design depends on

**Response envelope** (doc, and observed for errors):

```
{"ok": true,  "result": …}
{"ok": false, "error_code": 401, "description": "Unauthorized"}
```

Observed 2026-10-21 with fake tokens:

| Request | Observed |
|---|---|
| `GET /bot123456:AAAA-not-a-real-token/getMe` | HTTP 401, `{"ok":false,"error_code":401,"description":"Unauthorized"}` |
| `GET /bot123456:AAAA-not-a-real-token/getUpdates` | same 401 |
| `GET /botnotatoken/getMe` | HTTP 404, `{"ok":false,"error_code":404,"description":"Not Found"}` |

**The token travels in the URL path.** Any exception or log line that includes the
request URL leaks it. This is the same class of leak as 001 A-3 (CallMeBot key in the
query string), so the same defences apply, plus a new adversarial test (DD-8).

**`getUpdates`** (doc):
- `offset`: "An update is considered confirmed as soon as getUpdates is called with an
  offset higher than its update_id." So reading does **not** consume; only the next
  call with a higher offset does.
- Retention: updates "will not be kept longer than 24 hours". Spec E-9 accepts this.
  The longest observed delay between scheduled relay runs in October 2026 was about
  5 h (run list, 2026-10-18 to 2026-10-21), well inside 24 h.
- `limit` 1–100. `allowed_updates` filters types; we ask for `["message"]` only, so
  edits, reactions and joins never arrive.
- "This method will not work if an outgoing webhook is set up." We never set one; if
  one is set, `getUpdates` errors and the run fails loudly.

**Errors that matter** (doc, error wording "subject to change", so we branch on
`error_code`, and use `description` only to tell message problems from chat problems):

| Case | Expected | Our handling |
|---|---|---|
| Token wrong or revoked | 401 | channel failure (spec E-13) |
| Operator blocked the bot | 403 "bot was blocked by the user" | channel failure (spec E-12) |
| Chat id wrong | 400 "chat not found" | channel failure |
| Flood control | 429 with `parameters.retry_after` (seconds) | wait if ≤ 30 s and retry once, else channel failure |
| One message refused (e.g. too long, empty text) | 400 with another description | `MessageRejected` → 001 minimal-form retry (D-4 of 001) |
| Server trouble | 5xx, timeouts | retry with backoff, as today |

## R-4: Preview cards for X posts (spec D-1)

Each address was fetched as Telegram's link-preview fetcher identifies itself
(`User-Agent: TelegramBot (like TwitterBot)`), and once as a phone browser.

| Address | Post `…2112685998547010004` (link + image) | Post `…2112329895200125440` (text) | Phone browser |
|---|---|---|---|
| `x.com/…/status/…` | 200, card **without** text or image (`og:description` = a `t.co` link) | **307 redirect**, no card | — |
| `fxtwitter.com/…` | 200, title, text, **image** | 200, title, text, avatar | **302 → `x.com/…`** (reader lands on the real post) |
| `fixupx.com/…` | same as fxtwitter (same service) | — | — |
| `vxtwitter.com/…` | 200, title, text, image | 200, text, avatar | 200, serves its own page (no redirect) |
| `fixvx.com/…` | 302 → vxtwitter | — | — |
| `xcancel.com/…` | 451 | — | — |

Conclusions:
- `x.com` itself is unreliable as a card source: sometimes a bare card, sometimes a
  redirect and no card. This confirms the premise of spec D-1.
- **fxtwitter** gives full cards and sends human readers straight on to `x.com`.
  Selected (DD-4). vxtwitter is the fallback if fxtwitter dies.
- fxtwitter also answers 200 for a nonexistent post id (`/status/1`), so a card is
  never proof that a post exists. That is harmless here: we only ever link ids we
  just read from the feed.

**The Bot API can take the card from a different URL than the one in the text**
(doc: `LinkPreviewOptions.url`, "URL to use for the link preview"). So the message
text can keep the post's own `x.com` link while the card is built from the
fxtwitter address. See DD-4 for why that is better than putting fxtwitter in the
text.

**Verified 2026-10-21 at the switch-over:** Telegram renders the fxtwitter card in
the operator's app, with the post's own `x.com` link in the text.

## R-5: Posts with no text are dropped (brought into scope as spec US-7)

Post `2112685998547010004` above is one of three posts every recent relay run drops
with "text is empty after normalisation": it has a link and an image but no text of
its own. The relay never delivers posts like this. Cause, from the code: the parser takes a post's text from the feed item's
title; for a post that is only media or a link the title is empty, and `Tweet`
rejects empty text as malformed (001 FR-8). With preview cards such a post is worth
delivering as a fixed line plus the link and card. The operator asked for it to be
fixed in this feature (spec D-5).
