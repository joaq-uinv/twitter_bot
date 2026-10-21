# Tasks: Bot Chat Delivery & Commands

**Plan:** `./plan.md` | **Baseline:** branch `003-bot-chat-delivery` off `main`
46380b4, 546 tests green.

`PT` means `docker compose run --rm --entrypoint python relay -m pytest`.

- **"RED"** means the named tests fail for the stated reason, usually a missing
  module, function or field, never a typo.
- **"GREEN"** means those tests pass **and** `PT` stays green with 0 failed.
- Per §2, every implementation task comes right after its test task.

**Parallelism.** `[P]` marks a *test+implementation pair* that touches no file
shared with another `[P]` pair. Inside a pair the order is always test, then
implementation.

---

## Phase 1: Fixtures, posts without text, commands (DD-12, DD-15)

**T001 Capture fixtures.** ✅ 2026-10-21
- Files: `tests/fixtures/telegram/` with
  - `send_ok.json` (`ok: true`, `result.message_id`);
  - `unauthorized_401.json`, `not_found_404.json` (bodies observed in R-3);
  - `blocked_403.json`, `chat_not_found_400.json`, `too_long_400.json`,
    `flood_429.json` (`parameters.retry_after`), built from the documented shapes;
  - `updates_mixed.json`: operator commands, a stranger's `/pause`, a sticker
    (no `text`), an edited message, and one update with a missing `update_id`;
  - `get_chat_private.json`, `get_chat_group.json`.
- `tests/fixtures/feed_no_text_item.xml`: a real feed item with an empty title
  (captured from a working mirror; post `2112685998547010004` or any text-less post).
- Verify: `ls tests/fixtures/telegram | wc -l` gives `10`, and
  `grep -rlE '[0-9]{8,10}:[A-Za-z0-9_-]{30,}' tests/fixtures` gives nothing (no real token).
- Covers: §5 for FR-5, FR-7, E-12, E-13; US-7.

**T002 [P] Test posts without text.** ✅ 2026-10-21 `tests/unit/test_models.py`, `test_nitter_parse.py`, `test_formatter.py`
- `Tweet(text="")` and `Tweet(text="​‮")` construct, with `text == ""`.
- Bad id, author and time still raise (AC-7.3).
- Parsing `feed_no_text_item.xml` yields the post instead of logging "empty after
  normalisation".
- `render` of a text-less post per kind: ORIGINAL "New post from @santtiagom_ (no
  text)", RETWEET "@santtiagom_ reposted @x (no text)", QUOTE, REPLY; each followed by
  the `x.com` link, separated by a blank line as in every other message.
- Verify: RED with `ValueError: text is empty after normalisation` and the old
  wording.
- Covers: US-7, AC-7.1, AC-7.3, FR-19, E-21, E-22.

**T003 Implement posts without text.** ✅ 2026-10-21 `src/tweet_relay/models.py`, `formatter.py`
- Verify: GREEN (T002).
- Covers: FR-19.

**T004 [P] Test `Tweet.preview_url`.** ✅ 2026-10-21 `tests/unit/test_models.py`
- Returns `https://fxtwitter.com/{author}/status/{id}`.
- A hostile feed link (other host, extra path, query) cannot change it: the value
  depends only on `author` and `id`.
- Verify: RED with `AttributeError: preview_url`.
- Covers: FR-2, AC-1.2 (DD-4).

**T005 Implement `preview_url`.** ✅ 2026-10-21 `src/tweet_relay/models.py`
- Verify: GREEN (T004).

**T006 [P] Test command parsing.** ✅ 2026-10-21 `tests/unit/test_commands.py`
- `/status`, `/STATUS`, `/Pause now`, `/resume@my_bot`, `/help` give the command.
- `/statusx`, `status`, `""`, ` /pause` (leading space), a 100 KB string, and
  binary-looking text give `UNKNOWN`.
- Only `text[:64]` is examined: a 1 MB string parses in < 50 ms.
- Verify: RED with `ModuleNotFoundError: tweet_relay.commands`.
- Covers: FR-8, D-3, E-6, E-7.

**T007 Implement `Command` and `parse`.** ✅ 2026-10-21 `src/tweet_relay/commands.py`
- Verify: GREEN (T006).

**T008 [P] Test reply templates.** ✅ 2026-10-21 `tests/unit/test_commands.py`
- Each reply in data-model.md, with fixed inputs.
- `/status`: "none yet" for no `last_check`; "not available" for no mirror data;
  "unknown, sources unavailable" for the waiting count when the fetch failed.
- `/resume` warns about aged-out posts only when `paused_since` precedes the oldest
  listed post.
- `/help` mentions all four commands and the next-check delay.
- No template accepts operator text: a property test feeds random text through
  every path that builds a reply and asserts it never appears in the output.
- Verify: RED (functions missing).
- Covers: AC-3.1, AC-3.2, AC-3.3, AC-4.1, AC-4.4, AC-4.5, AC-4.6, AC-5.1, AC-5.2,
  FR-11, E-17.

**T009 Implement reply templates.** ✅ 2026-10-21 `src/tweet_relay/commands.py`
- Verify: GREEN (T008).

## Phase 2: State (DD-9, DD-10)

**T010 Test the new state fields.** ✅ 2026-10-21 `tests/unit/test_state.py`
- Round trip of `paused_since`, `update_offset`, `announced`, `last_check`.
- The **current** `state/seen.json` from `main` loads with the defaults (`None`, `0`,
  `False`, `None`) and keeps every seen id (AC-2.1).
- Each invalid value falls back as in data-model.md and logs at ERROR: naive
  datetime, `"5"`, `-1`, `true` as offset, `"yes"` as announced, a negative `sent`.
- A re-bootstrap (changed handle) resets them.
- Verify: RED with `TypeError`/`AttributeError` on the new fields.
- Covers: FR-4, FR-12, AC-2.1, AC-4.2 (persistence).

**T011 Implement the state fields.** ✅ 2026-10-21 `src/tweet_relay/state.py`
- Verify: GREEN (T010).

## Phase 3: `TelegramBot` as a sink (DD-1, DD-2, DD-8)

**T012 Test sending.** ✅ 2026-10-21 `tests/unit/test_telegram.py`, respx
- `send` posts JSON with `chat_id`, `text`, **no** `parse_mode`, and
  `link_preview_options.url == preview_url` when given; no `link_preview_options`
  when not.
- Returns only for `send_ok.json`. `ok: true` without an integer `message_id`,
  non-JSON, and an HTML body raise `DeliveryFailed`.
- Verify: RED with `ModuleNotFoundError: tweet_relay.sinks.telegram`.
- Covers: FR-1, FR-5, AC-1.1, AC-1.3, 001 E-11.

**T013 Implement sending.** ✅ 2026-10-21 `src/tweet_relay/sinks/telegram.py`
- Verify: GREEN (T012).

**T014 Test error classification.** ✅ 2026-10-21 `tests/unit/test_telegram.py`
- 401, 403 blocked, 404, 400 "chat not found" → `DeliveryFailed`, **not**
  `MessageRejected`.
- 400 "message is too long" → `MessageRejected`.
- 429 with `retry_after: 2` → one wait (clock injected) and a retry that succeeds;
  `retry_after: 120` → `DeliveryFailed` with no wait.
- 5xx and timeouts → retried with backoff, then `DeliveryFailed`.
- Pacing: two sends in a row wait ≥ 1 s between them (clock injected).
- The 401 message says the token was rejected (E-13).
- Verify: RED (classification missing).
- Covers: E-11, E-12, E-13, FR-10, contract message-sink 5–7.

**T015 Implement error classification.** ✅ 2026-10-21 `src/tweet_relay/sinks/telegram.py`
- Verify: GREEN (T014).

**T016 Test the private-chat check.** ✅ 2026-10-21 `tests/unit/test_telegram.py`
- `chat_is_private()` is `True` for `get_chat_private.json`, `False` for the group
  fixture; any error raises `DeliveryFailed`.
- Verify: RED (method missing).
- Covers: D-4, E-14.

**T017 Implement the private-chat check.** ✅ 2026-10-21 `src/tweet_relay/sinks/telegram.py`
- Verify: GREEN (T016).

**T018 Test that nothing leaks.** ✅ 2026-10-21 `tests/adversarial/test_secret_leaks.py`
- With a marker token and chat id, force every error path in `TelegramBot`
  (each fixture in T001, a `ConnectError`, a `ReadTimeout`, a 1 MB error body,
  an error body that echoes the token back).
- Assert the marker token, the URL-quoted token, and the chat id appear in no
  exception string, `repr`, traceback, or captured log at any level.
- A 2xx body that echoes the token: same assertion.
- Verify: RED for at least the `httpx` exception path before DD-8 is applied
  (check by temporarily raising `str(exc)` in the sink; record in the log below).
- Covers: FR-16, DD-8, §6.

**T019 Apply DD-8 everywhere it is needed.** ✅ sink part 2026-10-21; `cli.py` part moved to T039 (it needs T037's config fields) `sinks/telegram.py`, `cli.py` (`_setup` registers the token and chat id with `logging_setup`)
- Verify: GREEN (T018).
- Covers: FR-16.

## Phase 4: `TelegramBot` as an inbox (DD-3, DD-6)

**T020 Test `read`.** ✅ 2026-10-21 `tests/unit/test_telegram.py`
- Requests `getUpdates` with `offset`, `limit=100`, `timeout=0`,
  `allowed_updates=["message"]`.
- On `updates_mixed.json`: returns valid messages oldest first, skips the update with
  no `update_id`, gives `text=""` for the sticker; `next_offset` = highest id + 1.
- No updates → `next_offset == offset`.
- Text over 4096 chars is truncated before it leaves the adapter.
- Body over 1 MiB, non-JSON, `ok: false`, `result` not a list, 409 (webhook set)
  → `InboxUnavailable`, carrying no content.
- Verify: RED (`read` missing).
- Covers: FR-6, FR-11, E-6, contract command-inbox 1–5.

**T021 Implement `read`.** ✅ 2026-10-21 `src/tweet_relay/sinks/telegram.py`
- Verify: GREEN (T020).

**T022 Test inbox leaks.** ✅ 2026-10-21 `tests/adversarial/test_secret_leaks.py`, `tests/adversarial/test_no_third_party_text.py`
- A stranger's message whose text is a marker, a fake log line
  (`2026-10-21 12:00:00,000 INFO tweet_relay.pipeline: delivered tweet_id=1`) and a
  secret-looking string: none of it appears in any log, the result line, or the
  rendered job summary after a full `run --once` against doubles.
- Verify: RED until T027 (the pipeline is what discards it); record which part was
  RED.
- Covers: AC-6.1, FR-7, E-19.

## Phase 5: Pipeline (plan Architecture)

All pipeline tests use `RecordingSink`, `ScriptedInbox` and the existing source
doubles in `tests/doubles.py`.

**T023 Add the doubles.** ✅ 2026-10-21 `tests/doubles.py`
- `RecordingSink` records `(message, preview_url)` and supports `chat_is_private`.
- `ScriptedInbox` returns a fixed `InboxBatch` or raises `InboxUnavailable`.
- Verify: `PT` stays green (no behaviour yet).

**T024 Test delivery with cards.** ✅ 2026-10-21 `tests/unit/test_pipeline.py`
- Every post is sent with `preview_url == tweet.preview_url`; notices are sent
  without one.
- A text-less post is delivered, marked seen, and not delivered again (AC-7.2).
- Verify: RED (no `preview_url` passed).
- Covers: AC-1.1, AC-1.2, AC-7.2, FR-2.

**T025 Implement delivery with cards.** ✅ 2026-10-21 `src/tweet_relay/pipeline.py`
- Verify: GREEN (T024).

**T026 Test the private-chat check and the announcement.** ✅ 2026-10-21 `tests/unit/test_pipeline.py`
- `chat_is_private() == False` → nothing sent, `failed=1`, the error names no id.
- Old-format state (bootstrapped, `announced` absent) → the first check sends "now
  delivering here" first, then the pending posts; the second check does not
  announce again (AC-2.3, D-2).
- A fresh bootstrap sends only the bootstrap message and sets `announced`.
- Paused on the first check → announcement still sent, posts not (E-18).
- Verify: RED.
- Covers: AC-2.2, AC-2.3, D-2, D-4, E-14, E-18.

**T027 Implement check and announcement.** ✅ 2026-10-21 `src/tweet_relay/pipeline.py`
- Verify: GREEN (T026).

**T028 Test command handling.** ✅ 2026-10-21 `tests/unit/test_pipeline.py`
- Operator `/pause`: state paused, saved with `update_offset` advanced **before**
  the reply is sent (assert by making the sink raise on the reply: the state on disk
  is paused and the offset advanced, `failed=1`).
- A stranger's `/pause` is ignored: no reply, no state change, the offset still
  moves past it (AC-6.1, AC-6.2, E-4, E-5).
- A message from the operator's id but `chat_type == "group"` is ignored.
- Order: `/pause` then `/resume` ends running with two replies (E-1); the reverse
  ends paused (E-2).
- 25 operator commands: 20 handled, offset stops at the 21st (DD-6, FR-10); the next
  check handles the rest.
- `InboxUnavailable` → `failed=1`, posts are still delivered.
- The same `InboxBatch` replayed (crash before save) after a save → not handled
  twice (FR-9, E-8).
- Verify: RED.
- Covers: FR-6, FR-7, FR-9, FR-10, AC-6.1, AC-6.2, E-1, E-2, E-3, E-4, E-5, E-8.

**T029 Implement command handling.** ✅ 2026-10-21 `src/tweet_relay/pipeline.py`
- Verify: GREEN (T028).

**T030 Test pause behaviour.** ✅ 2026-10-21 `tests/unit/test_pipeline.py`
- Paused: no posts, no withheld notice, nothing marked seen, across three checks
  (AC-4.1, AC-4.2, FR-13, FR-14).
- Paused + all sources fail → outage notice delivered (AC-4.3).
- `/resume` with 13 posts waiting → reply states 13; 10 delivered oldest first, then
  "…and 3 more"; next check delivers 3 (AC-4.4).
- `paused_since` earlier than the oldest listed post → the resume reply carries the
  aged-out warning (AC-4.5, E-15); later than it → no warning.
- `/pause` while paused and `/resume` while running → "already" replies (AC-4.6).
- `RunResult.paused` is `True` for a paused check (AC-4.7).
- Verify: RED.
- Covers: US-4, AC-4.1..AC-4.7, FR-13, FR-14, FR-15, E-15.

**T031 Implement pause behaviour.** ✅ 2026-10-21 `src/tweet_relay/pipeline.py`
- Verify: GREEN (T030).

**T032 Test `/status` inputs.** ✅ 2026-10-21 `tests/unit/test_pipeline.py`
- `last_check` is written at the end of every completed check with the number
  delivered.
- `/status` reflects the previous check, the waiting count, the pause, and the
  mirror file (present: "h of t healthy"; missing or invalid: "not available").
- `/status` during an outage is still answered (AC-3.3).
- Verify: RED.
- Covers: AC-3.1, AC-3.2, AC-3.3, E-17.

**T033 Implement `/status` inputs.** ✅ 2026-10-21 `src/tweet_relay/pipeline.py`
- Verify: GREEN (T032).

**T034 Re-run T022.** ✅ 2026-10-21 ✅ 2026-10-21 Verify: GREEN. Covers: AC-6.1, FR-7, E-19.

**T035 Test concurrency.** ✅ 2026-10-21 `tests/unit/test_pipeline.py`
- Two pipelines on one state path, run in threads, with the same inbox batch:
  each command handled once, the pause state consistent (E-10).
- Verify: RED or GREEN on first run; if GREEN, record that the existing state lock
  already covers it.
- Covers: E-10, FR-9.

## Phase 6: CLI, config, report; CallMeBot removed (FR-3)

**T036 Test config.** ✅ 2026-10-21 `tests/unit/test_config.py`
- `TELEGRAM_BOT_TOKEN` shape and `TELEGRAM_CHAT_ID` shape accepted or rejected per
  data-model.md; the error never contains the value.
- `require_delivery()` names the missing variable(s).
- `CALLMEBOT_*` in the environment is ignored, not an error (AC-1.4).
- `STATUS_PAGE_URL` must be https.
- Verify: RED.
- Covers: AC-1.4, FR-3, FR-16.

**T037 Implement config.** ✅ 2026-10-21 `src/tweet_relay/config.py`, `.env.example`
- Verify: GREEN (T036).

**T038 Test the CLI.** ✅ 2026-10-21 `tests/unit/test_cli.py`
- `run --once` builds `TelegramBot` as sink and inbox; `--dry-run` uses
  `ConsoleSink`, prints `| card: …`, and reads commands without advancing the real
  offset (temporary state copy, 001 A-10).
- Result line includes `paused=`.
- `test-delivery` sends one message and fails clearly on a non-private chat.
- `find-chat-id` lists private chats from `getUpdates` without passing an offset
  that confirms anything; it never prints the token.
- `test-whatsapp` no longer exists.
- Verify: RED.
- Covers: FR-3, AC-4.7, quickstart steps 2–4.

**T039 Implement the CLI.** ✅ 2026-10-21 `src/tweet_relay/cli.py`, `sinks/console.py`
- Verify: GREEN (T038).

**T040 Test the report.** ✅ 2026-10-21 `tests/unit/test_report.py`, `tests/adversarial/test_report_forgery.py`
- `paused=True` gives a "⏸ paused" headline and is not shown as a failure.
- A log without `paused=` (older runs) still renders.
- A forged `paused=` inside a post line (prefixed `| `) is ignored.
- Verify: RED.
- Covers: AC-4.7.

**T041 Implement the report.** ✅ 2026-10-21 `src/tweet_relay/report.py`
- Verify: GREEN (T040).

**T042 Delete CallMeBot.** ✅ 2026-10-21 `sinks/callmebot.py`, `tests/unit/test_callmebot.py`, `tests/fixtures/callmebot_paused.html`, CallMeBot cases in `tests/adversarial/*` and `tests/integration/test_live.py`
- Replace the live WhatsApp test with `test_real_telegram_delivery`, skipped unless
  `TELEGRAM_LIVE=1` (resolves the 002 follow-up).
- Verify: `grep -rniE 'callmebot|whatsapp' src tests .env.example` finds only the
  deliberate references (the `001-tweet-to-whatsapp` folder name, the AC-1.4 test that
  old settings are ignored, the test that `test-whatsapp` is gone), and `PT` is green.
- Covers: FR-3.

**T043 Update the docs.** ✅ 2026-10-21 `README.md`, `CLAUDE.md`, `specs/001-tweet-to-whatsapp/plan.md` (amendment A-13 pointing at spec 003)
- Commands, secrets, test count, the "Secrets" section.
- Verify: `grep -niE 'callmebot|whatsapp' README.md CLAUDE.md` only finds
  historical references marked as such.
- Covers: FR-3.

## Phase 7: Workflow (DD-11, DD-13)

**T044 Update `poll.yml`.** ✅ 2026-10-21
- `.env`: `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`, `STATUS_PAGE_URL`; CallMeBot lines
  removed.
- A step before the check copies `mirror-status:latest.json` to
  `state/mirror-latest.json` when the branch exists (failure only warns), and
  `state/mirror-latest.json` is gitignored.
- Scrub step: the two new secrets.
- "Alert on workflow failure" step deleted (DD-13).
- Verify: `docker run --rm -v "$PWD:/repo" -w /repo rhysd/actionlint:1.7.7` exits 0,
  and `grep -niE 'callmebot' .github/workflows/*.yml` gives nothing.
- Covers: FR-3, FR-17, AC-3.1, DD-11, DD-13.

## Phase 8: Review and switch-over

**T045 Pre-merge review.** ✅ 2026-10-21 `superpowers:requesting-code-review` on the branch.
- Fix every Critical and Important finding; record as plan amendment(s).
- Verify: verdict "Yes", or "With fixes" with the fixes landed; `PT` green.

**T046 Operator setup** ✅ 2026-10-21 (quickstart steps 1–3). Needs your Telegram account.
- Verify: `gh secret list` shows `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID`;
  `test-delivery` prints "✓ Sent" and the message arrives.
- Covers: D-4.

**T047 Dry run in Actions** ✅ 2026-10-21 (quickstart step 4), after merge.
- Verify: the job summary shows cards and no message is sent; no state commit.

**T048 Live switch-over** ✅ 2026-10-21 (quickstart steps 5–6).
- Verify: announcement once; the stuck posts arrive with cards; no pre-2026-10-20 post
  repeats; `/status`, `/pause`, `/resume` behave as quickstart step 6; a second
  account's `/pause` has no effect.
- Covers: Success criteria, AC-2.1..AC-2.3, US-3..US-6 live.

**T049 Remove the CallMeBot secrets** ✅ 2026-10-21 (quickstart step 7), only after T048.
- Verify: `gh secret list` shows no `CALLMEBOT_*`.
- Covers: FR-3, plan DD-14.

---

## Traceability

| Requirement | Tasks |
|---|---|
| AC-1.1 | T012, T024, T048 |
| AC-1.2 | T004, T024, T048 |
| AC-1.3 | T012 |
| AC-1.4 | T036 |
| AC-2.1 | T010, T048 |
| AC-2.2 | T026, T048 |
| AC-2.3 | T026, T048 |
| AC-3.1 | T008, T032, T044 |
| AC-3.2 | T008, T032 |
| AC-3.3 | T008, T032 |
| AC-4.1–4.6 | T008, T030 |
| AC-4.7 | T030, T038, T040 |
| AC-5.1, AC-5.2 | T008 |
| AC-6.1 | T022, T028, T034 |
| AC-6.2 | T028 |
| AC-7.1 | T002 |
| AC-7.2 | T024 |
| AC-7.3 | T002 |
| FR-1 | T012 |
| FR-2 | T004, T024 |
| FR-3 | T036, T038, T042, T043, T044, T049 |
| FR-4 | T010 |
| FR-5 | T012 |
| FR-6 | T020, T028 |
| FR-7 | T022, T028 |
| FR-8 | T006 |
| FR-9 | T028, T035 |
| FR-10 | T014, T028 |
| FR-11 | T008, T020 |
| FR-12 | T010 |
| FR-13, FR-14 | T030 |
| FR-15 | T030 |
| FR-16 | T018, T019, T036 |
| FR-17 | T044, T048 |
| FR-18 | plan Technical Context (no paid service); T048 |
| FR-19 | T002, T003 |
| E-1..E-5 | T028 |
| E-6, E-7 | T006, T020 |
| E-8 | T028 |
| E-9 | accepted limitation; `/help` text in T008 |
| E-10 | T035 |
| E-11 | T014 |
| E-12, E-13 | T014 |
| E-14 | T016, T026 |
| E-15 | T030 |
| E-16, E-20 | DD-4: the card is the chat's own rendering; T012 asserts a send never depends on it |
| E-17 | T008, T032 |
| E-18 | T026 |
| E-19 | T022 |
| E-21, E-22 | T002 |

## Manual verification log

*(Tasks record results here, with dates.)*

- 2026-10-21, T049: `CALLMEBOT_PHONE` and `CALLMEBOT_APIKEY` deleted at the operator's
  request, after T048 delivered. `gh secret list` now shows only the two Healthchecks
  URLs and the two Telegram secrets.

- 2026-10-21, T046–T048 (live, after merge `168a371`, mirror swap 001 A-14 included):
  - T046: secrets `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` set; `test-delivery`
    printed "✓ Sent" and the operator saw the message. The token was once pasted into
    the conversation and a shell command; the operator was asked to revoke it with
    BotFather `/revoke` and replace it.
  - T047 ([run 39663423496](https://github.com/joaq-uinv/twitter_bot/actions/runs/39663423496)):
    dry run green; announcement, two "unknown" replies (the operator's setup
    messages), 10 posts each with a `card:` line, 9 withheld; no state commit.
  - T048 switch-over ([run 39663779658](https://github.com/joaq-uinv/twitter_bot/actions/runs/39663779658)):
    sent 10, withheld 9, failed 0. None of the 10 was in the pre-switch delivered set;
    all 10 recorded; `announced` true.
  - T048 commands ([run 39664705404](https://github.com/joaq-uinv/twitter_bot/actions/runs/39664705404)):
    `/status` and `/pause` handled in order; "paused, 10 posts waiting", `sent=0`,
    run green. `kareem.one` failed and `mie.foundation` (added by A-14) served the feed.
  - T048 resume ([run 39664882139](https://github.com/joaq-uinv/twitter_bot/actions/runs/39664882139)):
    two `/resume` messages (the offset moved by 2, so two distinct updates, not a
    double-handle); 10 delivered oldest first, 0 withheld.
  - Confirmed by the operator in the Telegram app: posts show preview cards (research
    R-4's "not verified" item is now verified), and image-only posts read "(no text)".
    Not done: the stranger check from a second account (covered by unit and
    adversarial tests only).

- 2026-10-21, Phase 1 (T001–T009): `PT` 585 passed. Each test pair was RED first for
  the stated reason (empty text rejected; `preview_url`, `tweet_relay.commands` and
  the reply builders missing). The full suite takes about 2.5 min, so it runs once per
  phase; targeted tests run per task.
  - T001: the text-less fixture was captured from `nitter.mie.foundation`, a
    *candidate* mirror, because **all four in-use mirrors failed at capture time**
    (kareem 404, pp.ua 403, thepixora 403, meowing 502). It holds three text-less
    posts, including `2112685998547010004` from research R-5. Telegram fixtures: the
    401 and 404 bodies are verbatim from R-3; the others follow the documented shapes
    and are re-checked against the real bot in T046.
- 2026-10-21, Phases 2–4 (T010–T021): `PT` 665 passed. RED first for each pair
  (missing fields, `ModuleNotFoundError: tweet_relay.sinks.telegram`, missing
  classification, `chat_is_private`, `InboxUnavailable`).
  - T018 went GREEN on its first run, because T013/T015 already followed DD-8. It was
    proven able to fail by two mutants, each reverted: passing httpx's message on
    (`str(exc)`) failed the connect and timeout cases (the token is in the URL);
    disabling the description scrub failed the three echo cases. The tests live in
    `tests/adversarial/test_telegram_leaks.py` rather than `test_secret_leaks.py`,
    which holds the CallMeBot cases that T042 deletes.
  - `IncomingMessage` and `InboxBatch` live in `commands.py` (data-model.md);
    `InboxUnavailable` sits next to `DeliveryFailed` in `models.py`.
