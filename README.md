# tweet-relay

Relays new posts from an X profile to your own WhatsApp. Free to run, everything in
Docker, built Spec-Driven.

```bash
cp .env.example .env    # set CALLMEBOT_PHONE, CALLMEBOT_APIKEY, HOST_UID, HOST_GID
docker compose build
docker compose run --rm relay check-source     # verify retrieval works
docker compose run --rm relay test-whatsapp    # verify delivery works
docker compose up -d
```

Full setup, including how to get a CallMeBot key in a minute:
[`specs/001-tweet-to-whatsapp/quickstart.md`](specs/001-tweet-to-whatsapp/quickstart.md).

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
| `specs/001-tweet-to-whatsapp/spec.md` | Behaviour and acceptance criteria — no tech named |
| `specs/001-tweet-to-whatsapp/plan.md` | Design decisions, rejected alternatives, and 5 amendments recording where reality corrected the plan |
| `specs/001-tweet-to-whatsapp/research.md` | Live-probed evidence — which mirrors actually work, as of when |
| `.specify/memory/constitution.md` | The 8 principles every change is checked against |
| `.claude/skills/speckit-*` | The skills that drive spec → plan → tasks → implement |
| `docs/tweet-relay.architecture.html` | Interactive architecture diagram, with guided views for failover and dedup |

## How it works

```
scheduler → source (4 mirrors, failover) → filter → sort → cap → sink (WhatsApp)
                                              ↕
                                     state (seen-ID set)
```

An interactive version, with guided views for the failover and dedup cases, is at
[`docs/tweet-relay.architecture.html`](docs/tweet-relay.architecture.html).

Retrieval uses public mirrors rather than the X API, which has had no free tier since
February 2026. Delivery uses CallMeBot, which is free and single-recipient by design.

## The one thing to know before changing anything

**Delivery history is a set of seen post IDs, not a high-water mark.**

A retweet carries the *original* post's ID, which can be years old, and the feed is not
in date order. "Newer than the last ID I saw" therefore silently discards most
retweets. `tests/adversarial/test_properties.py` states this as a law and lets
hypothesis hunt for counterexamples. Full evidence in
[`research.md`](specs/001-tweet-to-whatsapp/research.md).

## Tests

```bash
docker compose run --rm relay pytest                      # 271 tests, no network
docker compose run --rm relay pytest tests/adversarial -v # hostile input
docker compose run --rm relay pytest -m live              # real mirrors (opt-in)
```

The adversarial suite exists because the relay parses XML from volunteer-run third
parties and puts the result into an outbound URL carrying your API key. It covers XXE
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

## Caveats

- `HOST_UID`/`HOST_GID` in `.env` must match your own (`id -u`, `id -g`) or the
  container can't write `./state`. It fails loudly with the exact `chown` to run
  rather than silently — this bit the first real deployment (Amendment A-4.1).
- The mirrors are volunteer-run and unfunded. Three widely-recommended ones died during
  2026. Four are pinned and the relay fails over between them, but if all four die you
  will need to refresh the list — the relay messages you when that happens.
- No delivery while the machine is off. Posts still visible when it restarts are
  delivered; older ones are gone.
- CallMeBot allows roughly 80 messages/day.
