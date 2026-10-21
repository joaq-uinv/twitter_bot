# tweet-relay

Relays new posts from an X profile to a private Telegram chat with your own bot, with
link previews, and lets you send it `/status`, `/pause`, `/resume` and `/help`. Free
to run, everything in Docker, built Spec-Driven.

```bash
cp .env.example .env    # set TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, HOST_UID, HOST_GID
docker compose build
docker compose run --rm relay check-source     # verify retrieval works
docker compose run --rm relay find-chat-id     # after messaging your bot once
docker compose run --rm relay test-delivery    # verify delivery works
```

Full setup, including creating the bot:
[`specs/003-bot-chat-delivery/quickstart.md`](specs/003-bot-chat-delivery/quickstart.md).
Until October 2026 delivery went to WhatsApp through CallMeBot; its free quota ran out,
so spec 003 replaced it.

## What this is

Two things, and the first is the point:

1. **A worked example of Spec-Driven Development** — a constitution, a behaviour-only
   spec, a plan that records rejected alternatives, and a task list with full
   requirement traceability. The `.claude/skills/speckit-*` skills drive that loop.
2. **A relay that actually works**, used to prove the process produces something real.

Read `CLAUDE.md` first if you are picking this up.

## Repo layout

| Path | What's there |
|---|---|
| `specs/001-tweet-to-whatsapp/spec.md` | The relay: behaviour and acceptance criteria — no tech named |
| `specs/001-tweet-to-whatsapp/plan.md` | Design decisions, rejected alternatives, and the amendments recording where reality corrected the plan |
| `specs/001-tweet-to-whatsapp/research.md` | Live-probed evidence — which mirrors actually work, as of when |
| `specs/002-mirror-health/` | Mirror health checks and the public status page |
| `specs/003-bot-chat-delivery/` | The bot chat: delivery, preview cards, commands, pause |
| `.specify/memory/constitution.md` | The 8 principles every change is checked against |
| `.claude/skills/speckit-*` | The skills that drive spec → plan → tasks → implement |
| `docs/tweet-relay.architecture.html` | Interactive architecture diagram, with guided views for failover and dedup |

## How it works

```
scheduler → source (4 mirrors, failover) → commands → filter → sort → cap → sink (bot chat)
                                              ↕
                                     state (seen-ID set)
```

An interactive version, with guided views for the failover and dedup cases, is at
[`docs/tweet-relay.architecture.html`](docs/tweet-relay.architecture.html).

Retrieval uses public mirrors rather than the X API, which has had no free tier since
February 2026. Delivery uses a Telegram bot in a private chat; preview cards come from
fxtwitter, while the link in each message stays the post's own `x.com` address.

## The one thing to know before changing anything

**Delivery history is a set of seen post IDs, not a high-water mark.**

A retweet carries the *original* post's ID, which can be years old, and the feed is not
in date order. "Newer than the last ID I saw" therefore silently discards most
retweets. `tests/adversarial/test_properties.py` states this as a law and lets
hypothesis hunt for counterexamples. Full evidence in
[`research.md`](specs/001-tweet-to-whatsapp/research.md).

## Tests

```bash
docker compose run --rm --entrypoint python relay -m pytest                      # 660 tests, no network
docker compose run --rm --entrypoint python relay -m pytest tests/adversarial -v # hostile input
docker compose run --rm --entrypoint python relay -m pytest -m live              # real mirrors (opt-in)
TELEGRAM_LIVE=1 docker compose run --rm -e TELEGRAM_LIVE --entrypoint python relay -m pytest -m live -k telegram  # sends one real message
```

The adversarial suite exists because the relay parses XML from volunteer-run third
parties and sends the result in a request whose URL carries your bot token. It covers XXE
and entity-expansion attacks, forged links and identifiers, parameter injection, SSRF
via configuration, state corruption, concurrent writers, and network failure.

It has already earned its place twice. It caught a real credential leak, where `httpx`
logged request URLs at INFO and the API key travels as a query parameter (Amendment
A-3). And the first genuine WhatsApp send — after 261 tests were already green —
exposed a false-positive in delivery detection: CallMeBot's success response echoes
your message back, so a post whose own text contained "error" or "apikey" made a
*successful* delivery read as failed. That would have re-sent it every check forever
while blocking every post queued behind it (Amendment A-5). No mock caught that one —
mocks encode what you assume the service returns; only the live service could refute it.

## Deployment

Production runs on a **GitHub Actions schedule**, not a machine you have to keep on.
`.github/workflows/poll.yml` runs the same Docker image every 15 minutes via the
existing `run --once` flag — no application code changed for this. State moves from
the Docker volume to git commits (`state/seen.json` is tracked, updated only when it
changes). See plan Amendment A-6 for why this beat the alternatives (Oracle/GCP free
VMs need a new account and ongoing maintenance; Cloudflare Containers has no free
tier at all; Fly.io's free tier is gone).

Set two repository secrets before enabling it:

```bash
gh secret set TELEGRAM_BOT_TOKEN
gh secret set TELEGRAM_CHAT_ID
```

Then verify with a manual dry run before trusting the schedule:

```bash
gh workflow run poll.yml -f dry_run=true
gh run watch
```

`docker compose up -d` still works unchanged for local development — it just isn't
what's deployed. Don't run both against the same account at once: each keeps its own
copy of `seen.json`, so a post published after they diverge gets delivered twice.

## Caveats

- `HOST_UID`/`HOST_GID` in `.env` must match your own (`id -u`, `id -g`) or the
  container can't write `./state`. It fails loudly with the exact `chown` to run
  rather than silently — this bit the first real deployment (Amendment A-4.1).
- The mirrors are volunteer-run and unfunded. Three widely-recommended ones died during
  2026. Four are pinned and the relay fails over between them, but if all four die you
  will need to refresh the list — the relay messages you when that happens.
- No delivery while the machine is off. Posts still visible when it restarts are
  delivered; older ones are gone.
- Commands are read once per check, so replies arrive at the next scheduled run:
  minutes, sometimes hours when GitHub delays the schedule.
