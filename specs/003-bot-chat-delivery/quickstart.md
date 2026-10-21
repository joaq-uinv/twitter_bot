# Quickstart: switching the relay to the bot chat

How a human sets up and verifies feature 003 end to end. Steps 1–4 are the
operator's (they need your Telegram account); the rest can be run by anyone with
repo access. Never paste the token into a chat, an issue, or a commit.

## 1. Create the bot (operator, once)

1. In Telegram, open **@BotFather** and send `/newbot`.
2. Pick a display name and a username ending in `bot`.
3. BotFather replies with a token like `123456789:AA…`. Save it straight into the
   repo secrets:
   ```bash
   gh secret set TELEGRAM_BOT_TOKEN      # paste the token at the prompt
   ```
4. Also put it in your local `.env` as `TELEGRAM_BOT_TOKEN=…` (gitignored).
5. Optional: `/setcommands` in BotFather with
   ```
   status - How the relay is doing
   pause - Stop deliveries until /resume
   resume - Restart deliveries
   help - List commands
   ```
   so the commands appear in the chat's menu.

## 2. Find your chat id (operator, once)

1. Open your new bot in Telegram and send it any message, e.g. `hi`.
2. Locally:
   ```bash
   docker compose run --rm relay find-chat-id
   ```
   It lists the private chats that have written to the bot in the last 24 h, by
   first name and id, without confirming the messages. Pick yours.
3. Save it:
   ```bash
   gh secret set TELEGRAM_CHAT_ID         # paste the id
   ```
   and add `TELEGRAM_CHAT_ID=…` to `.env`.

## 3. Send a test message (operator)

```bash
docker compose run --rm relay test-delivery
```

Expected: "✓ Sent. Check your phone." and the message arrives in the bot chat. This
is the one-time confirmation that the chat is really yours (spec D-4). If it says
the chat is not private, the id is a group or channel: repeat step 2.

## 4. Dry run in Actions

```bash
gh workflow run poll.yml -f dry_run=true && gh run watch
```

Expected: the job summary shows the posts that would be sent, each with a
`card: https://fxtwitter.com/…` line, and the pending commands it would answer.
Nothing is sent, the stored offset is not advanced, and `seen.json` is not committed.

## 5. First real run (switch-over)

```bash
gh workflow run poll.yml -f dry_run=false && gh run watch
```

Expected in the bot chat, in order:
1. "✅ Relay now delivers here for @santtiagom_" (once, spec D-2).
2. The posts stuck since 2026-10-20 that the mirrors still list, oldest first, at
   most 10, each with a preview card. Posts with no text arrive as a "(no text)" line
   plus the link (spec US-7).
3. If more than 10 were waiting: "…and N more".

Check: no post delivered before 2026-10-20 arrives again (AC-2.1). The card shows the
post (R-4 "not verified" item); tapping the link opens the post on X.

## 6. Commands

Send, in the bot chat, `/status`, then `/pause`. Wait for (or trigger) a check:

```bash
gh workflow run poll.yml -f dry_run=false
```

Expected: the status reply, then "⏸ Paused…", and no posts in that check. The job
summary headline says paused, and the run is green (FR-17). Then send `/resume`,
trigger a check, and expect "▶️ Resumed…" followed by any waiting posts.

From a **second Telegram account**, message the bot `/pause`. Expected: no reply,
no change, and nothing about it in the run log or summary (spec US-6).

## 7. Remove the old channel (only after step 5 delivered)

```bash
gh secret delete CALLMEBOT_PHONE
gh secret delete CALLMEBOT_APIKEY
```

and delete those two lines from your local `.env`.

## Verification commands

```bash
docker compose run --rm --entrypoint python relay -m pytest                  # full suite
docker compose run --rm --entrypoint python relay -m pytest tests/adversarial -v
TELEGRAM_LIVE=1 docker compose run --rm -e TELEGRAM_LIVE --entrypoint python relay \
  -m pytest -m live -k telegram                                              # sends one real message
```
