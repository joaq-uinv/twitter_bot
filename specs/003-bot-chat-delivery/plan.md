# Implementation Plan: Bot Chat Delivery & Commands

**Spec:** `./spec.md` (Clarified, 0 open questions, D-1..D-4) | **Research:** `./research.md`
**Created:** 2026-10-21

## Constitution Gate

Checked before design. Any "no" blocks the plan.

| Principle | Compliant? | Notes |
|-----------|-----------|-------|
| §1 Spec approved, no open clarifications | ✅ | 0 markers, D-1..D-4 recorded. A scan of `spec.md` finds no technology names. One wording refinement is proposed in P-1 below, for the operator to confirm |
| §2 Test-first plan | ✅ | Every phase starts with failing tests. Telegram responses become fixtures (R-3) before the sink exists |
| §3 External systems behind adapters | ✅ | Delivery stays behind `MessageSink`. Reading commands gets a new `CommandInbox` adapter. Both are implemented by one `TelegramBot` class (DD-2). The mirror-health result is read from a file the workflow places, behind the existing `history` loader |
| §4 Untrusted input validated | ✅ | Incoming updates are hostile JSON from a party the operator does not control: size-capped, schema-checked, identity from `chat.id` only, text never echoed or logged (FR-7, FR-11). The mirror-health file is parsed by the existing hostile-tolerant loader |
| §5 Unit tests network-free | ✅ | `respx` fixtures for every Bot API case in R-3. Real sends are `@pytest.mark.live` **and** need `TELEGRAM_LIVE=1`, which also fixes the open 002 follow-up about `test_real_whatsapp_delivery` |
| §6 Secrets from env only | ✅ | `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`. Both redacted by `logging_setup`, both scrubbed from `run.log`, both asserted absent by adversarial tests. The token sits in the URL path (R-3), so no exception text may carry a URL (DD-8) |
| §7 Failures surface to operator | ✅ | Unchanged channels: the run fails (GitHub email) and Healthchecks. The relay's own outage notice moves to the bot chat. The workflow's CallMeBot alert step is deleted rather than ported: it shared the delivery channel, so it could never report that channel's own failure (001 A-7) |
| §8 No unjustified abstraction | ✅ | No new runtime dependency (httpx already present; no bot framework, DD-1). Net code shrinks: `callmebot.py` (166 lines) goes. One new adapter, which has a production caller and a test double |

## Technical Context

| Choice | Justification against a requirement |
|---|---|
| **Telegram Bot API over plain HTTPS with `httpx`** | FR-1, FR-18 (R-2). The two calls we need (`sendMessage`, `getUpdates`, plus `getChat`) are three JSON requests; a framework would add async machinery and a dependency for nothing (DD-1) |
| **Polling `getUpdates` once per check, no webhook** | FR-6 and spec Out of Scope: no always-on service. The relay already wakes per check |
| **State fields added to `state/seen.json`** | FR-12: the pause must be as durable as the delivered-posts record. Same file, same lock, same atomic write, same git commit per run |
| **Mirror-health result copied into the run by the workflow** | AC-3.1: `/status` reports spec 002's latest round. The relay reads a local file instead of calling GitHub, so it needs no new credential and no new adapter |
| **fxtwitter as the preview go-between** | D-1, R-4: the only probed service giving full cards and redirecting readers to the real post |

## Architecture

One check (`Pipeline.run_once`) after this change. New or changed steps in **bold**.

```
lock, load state
fetch posts                                 (SourceUnavailable → outage branch)
**read commands**    inbox.read(state.update_offset)          → [IncomingMessage]
**apply commands**   in send order, ≤ 20 per check (DD-6):
                       - not from operator's chat → skip (offset still advances)
                       - parse → Command | UNKNOWN
                       - mutate state (pause/resume), state.update_offset = id + 1
                       - save state   (before replying: at most once, FR-9, DD-5)
                       - send reply   (failure → failed=1, keep going with posts? no: DD-5)
**check chat**       first delivery of the run: target chat is private (D-4, DD-7)
**announce once**    if not state.announced: "now delivering here" (D-2)
if outage: outage notice (also while paused), save, return
if not bootstrapped: bootstrap as today
**if paused: deliver nothing, no withheld notice, save, return (FR-13, FR-14)**
deliver batch as today, **with preview_url per post** (DD-4)
withheld notice as today
**state.last_check = (now, sent)**; save
```

Commands are read **after** the fetch because `/resume`'s reply needs the number of
waiting posts and the oldest listed post's time (AC-4.4, AC-4.5), and **before**
delivery because `/pause` must stop this check's deliveries (AC-4.1). If the fetch
fails, commands are still handled (AC-3.3); the `/resume` reply then says sources are
unavailable instead of giving a count.

`/status` reports the **previous** completed check (`state.last_check`), the posts
waiting now, the pause, and the mirror-health round. Reporting the previous check
avoids sending replies after delivery, which would split one command's handling across
the run.

Components:

| Module | Change |
|---|---|
| `sinks/telegram.py` (new) | `TelegramBot`: `send(text, preview_url=None)`, `read(offset)`, `chat_is_private()`. Response judging, retries, pacing, redaction |
| `sinks/callmebot.py` | **Deleted**, with its tests and fixture |
| `commands.py` (new) | Pure: `parse(text) -> Command`, `IncomingMessage` validation, reply rendering. No I/O |
| `state.py` | New fields (data-model.md), backward-compatible load |
| `pipeline.py` | The bold steps above |
| `formatter.py` | `preview_url(tweet)`, switch announcement, no-text line (DD-15), docstring no longer says WhatsApp |
| `models.py` | `Tweet` accepts empty text after cleaning (DD-15); every other invariant unchanged |
| `config.py` | `TELEGRAM_BOT_TOKEN` (SecretStr), `TELEGRAM_CHAT_ID`, `STATUS_PAGE_URL`, `MIRROR_LATEST_PATH`; CallMeBot fields removed |
| `cli.py` | `test-whatsapp` → `test-delivery`; new `find-chat-id` for setup; result line gains `paused=` |
| `report.py` | Parses `paused=`; headline "⏸ paused" when paused |
| `poll.yml` | New secrets, scrub list, mirror-health file step; CallMeBot alert step deleted |

## Design Decisions

| # | Decision | Alternatives rejected | Why |
|---|----------|----------------------|-----|
| DD-1 | Call the Bot API directly with `httpx` | `python-telegram-bot`, `aiogram` | §8: three endpoints. Frameworks are async, run their own polling loop, and log requests their own way, which we would have to audit for token leaks (R-3) |
| DD-2 | One `TelegramBot` class implements both `MessageSink` and `CommandInbox` | Two classes | Both share the token, the client, the response judging and the redaction. Two protocols keep the pipeline testable with separate doubles |
| DD-3 | Poll `getUpdates(offset, limit=100, timeout=0, allowed_updates=["message"])` once per check | Webhook; long polling | A webhook needs a public always-on endpoint (spec Out of Scope). Long polling would hold the run open. `timeout=0` returns immediately |
| DD-4 | Text keeps the post's own `x.com` link; the card comes from `https://fxtwitter.com/<author>/status/<id>` via `link_preview_options.url` | fxtwitter link in the text (literal reading of D-1); vxtwitter; no card | R-4. The card is still built by the go-between (D-1), but the link the operator taps and copies is the real post, so the go-between learns only that Telegram previewed a post, not which posts the operator opens. If fxtwitter dies, posts still arrive with a working link. vxtwitter does not redirect readers, so it is the fallback only. Built from the validated author and id, never by string replacement on the URL. Spec wording: see P-1 |
| DD-5 | Per command: apply the state change, save state with `update_offset = update_id + 1`, **then** send the reply | Reply first, then save | FR-9 (at most once). Saving first means a crash or a failed reply can lose a reply but never re-applies a command. A failed reply fails the run (E-11), so it is not silent. Reply-first would double-apply on a crash between send and save |
| DD-6 | At most 20 operator commands per check; strangers' updates are skipped without counting | No cap; cap replies only | FR-10. Updates beyond the cap keep their offset and wait for the next check. 20 replies at 1 s pacing ≈ 20 s, inside the run's budget. Stranger updates cost no send, so they never count, and the `limit=100` read caps them anyway |
| DD-7 | `getChat(TELEGRAM_CHAT_ID).type == "private"` checked once per run, before the first send; otherwise `DeliveryFailed("configured chat is not a private chat")` and nothing is sent | Check only at setup; check `from.id == chat.id` on incoming messages | D-4. One extra request per run. The identity itself is never in the message |
| DD-8 | No exception or log line may contain a request URL: errors are reported as `type(exc).__name__` plus the Bot API `error_code` and a scrubbed `description` (≤ 200 chars); the token and chat id are registered with `logging_setup` | Rely on log redaction only | R-3: the token is in the URL path, and `httpx` exception strings include the URL. Same lesson as 001 A-3; redaction stays as the backstop |
| DD-9 | Pause state is `paused_since: datetime | None` in `seen.json` | A separate file; a GitHub variable | FR-12: same durability and lock as the delivered set. A variable would need a write token in the relay |
| DD-10 | Switch announcement keyed on a state flag `announced`, absent in existing files (so `False`), set `True` after the first successful send. A fresh bootstrap sets it too (the bootstrap message already says the relay is live) | Announce on every config change; no flag | D-2: once ever, never repeated. Old state files are upgraded by default values, no migration step |
| DD-11 | Mirror health: the workflow writes `state/mirror-latest.json` from `mirror-status:latest.json` (ignored by git); the relay reads it with `history._latest_from_json` | Relay calls the Pages URL; relay reads GitHub API | No network call and no token in the relay. The loader is already hostile-tolerant (002 E-20). Missing or invalid → "not available" (AC-3.2) |
| DD-12 | `/status`, `/pause`, `/resume`, `/help` match `^/(status|pause|resume|help)(@\w+)?(\s|$)` case-insensitively on the first 64 characters | Exact match | D-3. `@botname` suffix is what Telegram appends when a command is tapped from the menu. Nothing after the command is ever used or echoed |
| DD-13 | Delete the workflow's "Alert on workflow failure" step; do not port it to Telegram | Port it | It goes through the delivery channel, so it cannot report that channel failing (001 A-7). Healthchecks and the GitHub email are the independent alarms (FR-17). A Telegram alert from the workflow would also need the token in a shell step, outside the app's redaction |
| DD-14 | `CALLMEBOT_*` secrets are deleted by the operator after the first successful Telegram delivery (quickstart step 7) | Delete at merge | Spec US-2 / FR-3 order: never remove the old credentials before the new channel is proven |

| DD-15 | `Tweet.text` may be empty after cleaning; `render` then uses a fixed lead by kind (reusing the wording of the minimal form, e.g. "New post from @x (no text)", "@x reposted @y (no text)") plus the link | Keep dropping (001 behaviour); fall back to the feed's description HTML for some text | Spec US-7, D-5. The description is HTML from a third party; turning it into text needs a new sanitiser for no gain over the card. The fixed lead contains only validated handles, so it cannot be refused for its content, and E-21's minimal retry is unaffected |

### P-1 Proposed spec wording refinement (needs the operator's OK)

Spec AC-1.2 and FR-2 say the post's link is *presented through* the go-between
address. R-4 found that the Bot API can take the card from the go-between while the
visible link stays the post's own address (DD-4). That keeps everything D-1 asked for
(the card, built by the go-between) and removes D-1's accepted cost (the go-between
seeing which posts the operator opens). Proposed wording:

> **AC-1.2** Given a delivered post, when the operator views it, then a preview card
> built by a go-between service is shown, and the message's link is the post's own
> address.

If the operator prefers the literal D-1 (go-between link in the text), only DD-4
changes.

## Risks

| Risk | Likelihood | Mitigation |
|------|-----------|------------|
| fxtwitter dies or changes | Medium (volunteer-run, like the mirrors) | No card, but posts and links still work (E-16, E-20). Swap the host constant to vxtwitter (R-4) |
| Scheduler delays exceed 24 h, so commands expire (spec E-9) | Low (max observed ~5 h) | `/help` says replies wait for the next check |
| The token leaks through an exception URL | Medium without DD-8 | DD-8 plus an adversarial test that forces every error path with a marker token |
| Telegram changes error wording | Medium | Branch on `error_code`; `description` only distinguishes a refused message from a refused chat, and the safe default is plain `DeliveryFailed` |
| `seen.json` git push fails after commands were applied | Low | State is committed with `always()`. If the push fails, the next run re-reads those commands; pause/resume are idempotent and repeated replies are harmless |

## Phases

1. **Fixtures and models.** Capture Bot API envelopes (R-3) as fixtures. `IncomingMessage`, `Command`, `parse` (pure). `Tweet` with empty text and its no-text rendering (US-7), using a real text-less feed item as fixture. Tests first.
2. **State.** New fields with backward-compatible load; tests with an old-format `seen.json` from git history.
3. **`TelegramBot` sink.** Success judging, every error row of R-3, pacing, 429, retries, `MessageRejected` rules, no URL in errors. Adversarial leak tests.
4. **Inbox and chat check.** `read`, `chat_is_private`, hostile updates (wrong chat, huge text, missing fields, non-JSON).
5. **Pipeline.** Command handling, pause, announcement, preview URL, `last_check`. Every spec AC and edge case as a test against doubles.
6. **CLI, config, report.** `test-delivery`, `find-chat-id`, `paused=`; CallMeBot removed everywhere (code, `.env.example`, README, CLAUDE.md).
7. **Workflow.** Secrets, scrub list, mirror-health file, alert step deleted. actionlint.
8. **Review** (`superpowers:requesting-code-review`), then the operator's setup and a live switch-over (quickstart).
