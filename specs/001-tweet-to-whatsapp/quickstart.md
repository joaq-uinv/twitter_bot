# Quickstart: Tweet → WhatsApp Relay

Everything runs in Docker. No host Python needed.

## 1. Get a CallMeBot key (one-time, ~1 minute)

1. Save **+34 644 51 95 23** as a WhatsApp contact.
2. Send it exactly: `I allow callmebot to send me messages`
3. It replies with your API key.

Free, no account, and it only ever messages the number that opted in.

## 2. Configure

```bash
cp .env.example .env
```

Edit `.env` — at minimum `CALLMEBOT_PHONE` (E.164, e.g. `+34600111222`) and
`CALLMEBOT_APIKEY`. To watch a different account, change `X_PROFILE_URL`; nothing else
needs touching.

## 3. Verify before sending anything

```bash
docker compose build
docker compose run --rm relay pytest                    # full suite, no network
docker compose run --rm relay check-source              # which mirror answered
docker compose run --rm relay run --once --dry-run      # renders, sends nothing
```

`check-source` prints the mirror that responded and each parsed post with its kind.
If every mirror is down, this is where you find out — see Troubleshooting.

## 4. Send one real message

```bash
docker compose run --rm relay test-whatsapp
```

A message should reach your phone within seconds. If not, the key or phone number is
wrong — the command says which.

## 5. Run it

```bash
docker compose up -d
docker compose logs -f relay
```

The first cycle records existing posts as already-seen and sends **one** "relay is
live" message. It does not replay history, and it will not send that confirmation
again on restart.

## Verifying the behaviour that matters

| Check | Command | Expected |
|---|---|---|
| Dedup holds | `run --once` twice in a row | Second run sends nothing |
| Old retweets survive | Remove a retweet's ID from `state/seen.json`, then `run --once` | Exactly that one post is delivered, despite its old ID |
| Retargeting works | Change `X_PROFILE_URL`, `docker compose up -d` | Monitors the new account, re-bootstraps quietly |
| Outage alerting | `NITTER_INSTANCES=https://nitter.invalid`, `run --once` | One failure notification, and only one on repeat runs |
| Restart safety | `docker compose restart` | No post re-delivered, no liveness message |

## 6. Deploy without keeping your machine on (recommended)

Steps 1-5 verify everything works locally. For production, run it on GitHub Actions
instead — no VM, no account beyond GitHub, no code changes (see Amendment A-6 in
`plan.md` for why this beat Oracle/GCP free VMs and why Cloudflare/Fly.io don't fit).

```bash
gh secret set CALLMEBOT_PHONE      # paste the number you tested with above
gh secret set CALLMEBOT_APIKEY     # paste the key from step 1
gh workflow run poll.yml -f dry_run=true   # verify before it can send anything
gh run watch
```

Confirm the dry run's log shows a normal check with no errors, then:

```bash
gh workflow run poll.yml -f dry_run=false  # one real cycle
gh run watch
git pull   # the workflow just committed state/seen.json back
```

The `schedule` trigger in `.github/workflows/poll.yml` is now live and runs every 15
minutes on its own. Stop the local container so the two don't both deliver the same
post:

```bash
docker compose down
```

## Troubleshooting

**No messages arriving.** Check `docker compose logs relay`. Silence in the logs plus
no messages usually means the account genuinely has not posted — that is the designed
behaviour (§7: silence means healthy). A real outage sends you a notification.

**"All sources unavailable".** Mirrors are volunteer-run and die regularly. Refresh
the candidate list:

```bash
curl -s https://status.d420.de/api/v1/instances \
  | python3 -c "import json,sys; [print(h['url']) for h in json.load(sys.stdin)['hosts'] if h.get('healthy') and h.get('rss')]"
```

Put working ones in `NITTER_INSTANCES` (comma-separated) and restart. If none work at
all, see `research.md` R-1 for the fallbacks.

**Messages stop after a busy day.** CallMeBot allows ~80/day. Lower the volume by
setting `INCLUDE_RETWEETS=false`.

**Posts missed while the machine was off.** Expected — the relay only runs when Docker
runs. Posts still visible in the source when it restarts are delivered; older ones are
gone.
