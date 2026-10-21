# Implementation Plan: Tweet → WhatsApp Relay

**Spec:** `./spec.md` (Clarified, 0 open questions) | **Research:** `./research.md`
**Created:** 2026-09-15

## Constitution Gate

Checked before design. Any "no" blocks the plan.

| Principle | Compliant? | Notes |
|-----------|-----------|-------|
| §1 Spec approved, no open clarifications | ✅ | 3 resolved via `/speckit-clarify`, recorded as D-1..D-3. Automated check confirms no technology named in `spec.md` |
| §2 Test-first plan | ✅ | `tasks.md` orders every test before its implementation; fixture captured before any code |
| §3 External systems behind adapters | ✅ | `TweetSource`, `MessageSink`, `StateStore`, `Clock` — contracts in `contracts/` |
| §4 Untrusted input validated | ✅ | Hardened parser, byte caps, field validation, encoder-built URLs; `tests/adversarial/` enforces |
| §5 Unit tests network-free | ✅ | All unit + adversarial tests run against `tests/fixtures/`; live tests marked and excluded by default |
| §6 Secrets from env only | ✅ | `.env` gitignored; a test asserts the key never reaches log output |
| §7 Failures surface to operator | ✅ | FR-10 outage notification, edge-triggered per AC-4.3 |
| §8 No unjustified abstraction | ✅ | One package. `syndication.py` is the only speculative piece and is gated for deletion |

## Technical Context

| Choice | Justification against a requirement |
|---|---|
| **Python 3.12** | The work is XML parsing + HTTP + light scheduling. `defusedxml` is the mature hardened-XML option (§4) and `hypothesis` gives property-based coverage for FR-3/FR-5 ordering invariants |
| **uv** | Reproducible locked installs; fast container rebuilds. Lives only in the image — no host Python needed |
| **httpx** | Explicit per-request timeouts (E-18) and redirect control (§4), and a params encoder so URLs are never string-built (FR-13) |
| **defusedxml** | §4 mandates a hardened parser. Stdlib `ElementTree` is vulnerable to entity attacks |
| **pydantic-settings** | Config validation at startup, giving AC-5.2 (refuse to start on a malformed identifier) for free |
| **pytest + hypothesis** | §2; property tests encode "order must not matter" as a law rather than examples |
| **Docker Compose** | Operator requirement. Internal scheduler keeps scheduling inside the tested artefact (R-5) |

No web framework, no database, no ORM, no task queue — §8.

## Architecture

```
                  ┌──────────── scheduler (interval + jitter, SIGTERM-aware)
                  ▼
   ┌──────────► pipeline ──────────────────────────────────┐
   │              │                                        │
   │   ┌──────────┴───────────┐                            ▼
   │   ▼                      ▼                        formatter
TweetSource              StateStore                        │
   │                     (seen-ID set,                      ▼
   ├─ NitterRssSource     atomic + locked)              MessageSink
   │   └─ 4 mirrors, failover                            ├─ CallMeBotSink
   └─ SyndicationSource (gated)                          └─ ConsoleSink (--dry-run)
```

**Flow:** scheduler fires → source returns validated `Tweet`s → filter by `kind` per
config → drop IDs already in state → **sort ascending by `published_at`** → cap at
`MAX_MESSAGES_PER_RUN` → format → send one at a time → **mark seen only after each
success** → persist.

Ordering matters: capping *after* sorting is what makes D-3's backlog drain
oldest-first; marking seen *after* each send is what gives E-5 and FR-12.

## Design Decisions

| # | Decision | Alternatives rejected | Why |
|---|----------|----------------------|-----|
| DD-1 | **Delivery history is a bounded set of seen IDs** | `since_id` high-water mark; timestamp cursor | Research F-3: a retweet's ID is the *original* post's ID and may be years old. A watermark would permanently suppress retweets — most of the traffic, given AC-2.1. Timestamps fail on F-2's out-of-order feed. **This is the load-bearing decision.** |
| DD-2 | Bound the set at 300 IDs, newest-first | Unbounded; 20 | Unbounded grows forever on a volume-mounted file. 300 ≫ the 19-item feed window, so an ID cannot be evicted while still visible in the feed and be re-delivered |
| DD-3 | Classify by **marker prefix first, link author as corroboration** — see amendment below | Link author alone; title prefix alone | **Amended 2026-09-15 during T005.** Either signal alone is wrong: the account retweets *itself*, so link-author-differs misses self-retweets (3 of 19 fixture items); and quote-posts are indistinguishable from originals by prefix alone |
| DD-4 | Verify channel title names the configured handle | Trust the mirror | FR-7, E-7 — a mirror could serve the wrong or a spoofed account |
| DD-5 | Reject links not matching `/<handle>/status/<digits>` before rewriting to `x.com` | Rewrite host blindly | Blind rewriting turns an attacker-chosen path into a plausible x.com link delivered to the operator (E-10) |
| DD-6 | Outage notification is **edge-triggered** (state carries `outage_notified`) | Notify every failed check | AC-4.3 — a multi-day outage would otherwise send hundreds of messages |
| DD-7 | Per-check cap withholds rather than drops | Drop as stale; ignore cap | D-3; preserves FR-2 exactly-once while respecting the ~80/day ceiling |
| DD-8 | Long-running container with internal scheduler | Host cron invoking one-shot container | R-5 — keeps scheduling inside the artefact under test and portable to any Docker host |
| DD-9 | `syndication.py` **deleted, gate failed** — see A-2 | Ship it unverified | Returned 429 on every probe from two networks. §8 — an adapter that cannot be shown to work is speculative complexity |
| DD-10 | **GitHub Actions cron as a second deployment target**, replacing the long-running container for production use | Oracle/GCP Always-Free VMs (real but need a new account, a card, and ongoing OS patching); Cloudflare Containers (no free tier — requires Workers Paid at $5/mo minimum, and billed per-active-ms, wrong shape for a persistent poller); Fly.io free tier (discontinued in 2024, now a 7-day trial) | Zero new accounts, zero cards, zero application code changes — `cli.py`'s existing `--once`/`--dry-run` flags were already the right interface. State moves from a Docker volume to git commits, which is *more* durable (versioned, inspectable) not less. This repo is public, so Actions minutes are unconditionally free regardless of run frequency |

## Risks

| Risk | Likelihood | Mitigation |
|------|-----------|------------|
| All four mirrors die | **Medium** — three well-known ones died this year | 4-way failover + cached health-endpoint discovery + FR-10 alerting. If all die: self-host a mirror, or adopt the X API (~$1.50/mo). `TweetSource` keeps either a one-adapter change |
| A mirror is compromised and serves forged posts | Low | DD-4 identity check, DD-5 link validation; optional `VERIFY_ACROSS_INSTANCES` cross-checks two mirrors and warns on divergence |
| Mirrors rate-limit this host | Medium | Jittered interval (DD-8), failover, 900s default — polite relative to the feed's advertised 40min TTL |
| CallMeBot changes its response format | Low | Body-content success detection is already defensive; sink is behind an adapter |
| Operator's machine off for days | Certain | Accepted (R-5). Set-based history means resume, not loss — though posts aged out of the 19-item feed window are genuinely gone |

## Phases

| Phase | Content | Verifiable by |
|---|---|---|
| **P1** Foundations | Package skeleton, config + handle validation, models, Docker image | `pytest tests/unit/test_config.py`; image builds |
| **P2** Source | RSS parsing, classification, URL normalisation, failover | Parses the real fixture into 19 correctly-classified posts |
| **P3** State | Bounded seen-set, atomic write, locking, corruption recovery | Dedup and crash-recovery tests |
| **P4** Sink + format | CallMeBot adapter, truncation, console sink | Encoded-URL and truncation tests |
| **P5** Pipeline | Filter, order, cap, send, persist, bootstrap, outage notification | End-to-end tests over the fixture |
| **P6** Adversarial | The full `tests/adversarial/` suite | Every case in spec §Edge Cases has a test |
| **P7** Runtime | Scheduler, compose, healthcheck, live verification | `docker compose up`; real message received |

`syndication.py`'s gate is evaluated in P2: if it cannot return data, it is deleted and
DD-9 is recorded as resolved-by-deletion.

---

## Amendment A-1 — classification rules (2026-09-15, during T005)

Implementing the parser against the real fixture falsified DD-3 as originally written.
Recorded here rather than silently implemented, per `speckit-implement`.

**What was assumed:** a post is a retweet iff the link's author differs from the
monitored handle, and the `RT by @` title prefix is unreliable presentation text.

**What the fixture shows:** 3 of 19 items carry the `RT by @` prefix *with the
monitored handle as the link author* — the account retweeting its own earlier posts.
The link-author rule classifies these as originals. Separately, quote-posts carry no
prefix and the monitored handle as author, making them indistinguishable from
originals unless the body is inspected.

**Revised rules**, applied in order:

1. `REPLY` — title begins `R to @`
2. `RETWEET` — title begins `RT by @` **or** link author ≠ monitored handle.
   The prefix is Nitter's own structural template, not user content, and it is the
   only signal that catches a self-retweet.
3. `QUOTE` — link author == monitored handle, no prefix, and the body embeds another
   post. Verified: items 3 and 7 embed *other* accounts' posts, while item 6 embeds
   nothing and is a genuine original.
4. `ORIGINAL` — everything else.

**What this permits that the original decision did not:** treating the title prefix as
a trusted signal. Justified because it is emitted by the mirror's template rather than
supplied by the post's author — but it is still mirror-controlled, so the link-author
check is retained as a second condition rather than replaced.

**Fixture distribution under the revised rules:** 14 retweets (11 foreign-author +
3 self), 4 quotes, 1 original, 0 replies.

## Amendment A-2 — syndication adapter deleted (2026-09-15, T009 gate)

The gate defined in DD-9 and T009 was evaluated by probing
`syndication.twitter.com/srv/timeline-profile/screen-name/santtiagom_` three times
from inside the container. All three returned **HTTP 429 "Rate limit exceeded"**,
matching the earlier probes from the host network.

**Resolution: the adapter is not implemented.** Shipping an unexercised code path that
we have never seen succeed would violate §8, and it would be worse than absent — it
would look like redundancy that does not exist, weakening the operator's judgement
about how exposed the relay really is.

Redundancy therefore rests entirely on the four verified mirrors (research R-1). This
is recorded honestly in the risk register rather than papered over: if all four die,
the remaining options are self-hosting a mirror or adopting the paid API.

The endpoint may be IP-reputation-limited rather than dead, so it remains a candidate
if the mirrors fail. `TweetSource` keeps that a single new file.

## Amendment A-3 — credential leak found by test, fixed (2026-09-15, T014)

The FR-13 assertion in `test_callmebot.py` failed on first run, for a real reason
rather than a test defect.

**The leak:** CallMeBot requires the API key as a **query parameter**, and `httpx`
logs every request URL at INFO level. The key therefore appeared in ordinary
application logs — the exact disclosure §6 and FR-13 forbid. Nothing in the
application code logged it; a dependency did.

**The fix** (`logging_setup.py`), in two layers because silencing one library does not
generalise:

1. `httpx`/`httpcore` loggers are raised to WARNING, applied on import of the sink so
   it holds even if the app never configures logging.
2. A `SecretRedactingFilter` on the root handler replaces the key — and its
   URL-encoded form — anywhere in any record, whatever library emitted it.

**Why this is recorded:** it is evidence that FR-13 needed to be an asserted test
rather than a coding convention. A reviewer reading only the application code would
have concluded the key was never logged, and been wrong.

## Amendment A-4 — deployment defects found by running it (2026-09-15, T028)

Two defects that every unit test passed straight through, found only by executing the
quickstart against the real container. Recorded because they are the argument for
keeping T028 in the plan at all.

**A-4.1 — the state volume was unwritable.** The image runs as its own non-root user
(uid 10001), but `./state` on the host is owned by the operator, so the first check
died with a bare `PermissionError` traceback on the state lock. This would have hit
the operator on their very first `docker compose up`.

Fixed by running the service as the host user (`user: "${HOST_UID:-1000}:${HOST_GID:-1000}"`,
documented in `.env.example`), and by turning the failure into an actionable
`StateUnwritable` message naming the exact `chown` to run. §7: a traceback is not an
error message.

**A-4.2 — misconfiguration became a restart loop.** `restart: unless-stopped` is
correct for transient failures, but a missing credential is permanent, so the
container exited immediately and restarted forever, flooding the log with the same
error. Restarting cannot fix configuration.

Fixed by pausing before exiting on configuration errors only, which keeps the
diagnostic readable without weakening restart resilience for genuine runtime faults.

**What this changes about the plan:** nothing structural — but it is evidence that
"the tests pass" and "it runs" are different claims. Both defects sat in the gap
between them.

**A-4.3 — the uid fix broke the test suite.** Running as the host uid left `/app`
unwritable for the image user, so pytest's cache and hypothesis's example database
could not be written. `filterwarnings = ["error"]` promoted hypothesis's warning to a
failure, and six property tests started failing — after they had previously passed.

Both are redirected to `/tmp`. Recorded because it is a reminder that a deployment fix
can break the thing that verifies it, and that "it passed earlier" is not evidence:
the regression was only caught by re-running the full suite at the end.

## Amendment A-5 — delivery success detection was wrong (2026-09-15, first real send)

Found by sending one genuine message, after 261 tests were green. No mock caught it,
because the mocks encoded what I assumed the service returns.

**The real success body** (observed live):

    <p>Message to: +54…<p>Text to send: <OUR MESSAGE><p><b>Message queued.</b> …

**It echoes the message we sent.** The sink judged success by scanning the whole body
for error words, so any post whose own text contained "error", "invalid", "apikey",
"must provide" or "not registered" made a *successful* delivery read as failed.

The consequence was worse than a misreport. The post is genuinely delivered, but not
marked seen, and the pipeline stops the batch on a delivery failure — so that post
would be re-sent on every check, forever, while blocking every post queued behind it.
A duplicate-message loop plus a permanent stall, triggered by ordinary vocabulary for
an account that posts about software.

**Fix:** strip the echoed payload (raw and HTML-escaped) before judging, then require
the positive `queued` marker. An unrecognised body is now treated as *not delivered*,
per FR-12 — we never claim delivery on a response we do not understand.

**A-5.1 — the fix exposed a test-isolation defect.** With real credentials finally in
`.env`, pydantic-settings loaded them into tests asserting those values were absent,
and the suite failed because the machine was configured. Tests now disable `.env`
loading and clear the variables.

**What this changes about the plan:** it is the strongest evidence in this project for
`quickstart.md` step 4 existing at all. 261 passing tests, a full adversarial suite,
and end-to-end dry runs all missed a defect that one real message exposed immediately.
Mocks encode assumptions; only the live service refutes them.

## Amendment A-6 — GitHub Actions added as the production deployment (2026-09-17)

The operator wanted the relay to run without keeping a personal machine on. Two paid
services were ruled out immediately by research: Cloudflare Containers has no free
tier (Workers Paid, $5/mo minimum) and is billed per active millisecond — architecturally
wrong for a persistent poller, not just expensive. Fly.io's free tier was discontinued
in 2024; what remains is a 7-day trial requiring a card.

Real always-on free VMs exist (Oracle Cloud, Google Cloud e2-micro) and were seriously
considered, but both need a new cloud account, a card on file, and ongoing OS
maintenance the operator would then own. GitHub Actions needed none of that: this
repo is already public (unconditionally free Actions minutes), already has `gh`
authenticated, and `cli.py` already exposed `--once`/`--dry-run` — flags built during
the original implementation without anticipating this use, which turned out to be
exactly the interface a one-shot cron trigger needs.

**What changed, concretely:**
- `.github/workflows/poll.yml`: `schedule` cron every 15 minutes + `workflow_dispatch`
  with a `dry_run` input for manual verification. `concurrency: group: relay-poll` is
  the same principle as the state file lock (E-17) applied at the workflow level — two
  overlapping runs must not race on `state/seen.json`.
- **State moved from a Docker volume to git.** `state/seen.json` is no longer
  gitignored; each run commits it back only when it changed, avoiding noise on quiet
  cycles. This is a durability upgrade, not a compromise — git history is a better
  audit trail than an opaque volume ever was.
- `HOST_UID`/`HOST_GID` are computed from the runner (`id -u`/`id -g`) at run time,
  not copied from any developer's machine — getting this wrong reproduces Amendment
  A-4.1 in a new environment, so it's computed fresh every run rather than hardcoded.
- **A failure alert independent of the app.** FR-10's outage notice fires from inside
  the running container, so it can only fire once the container is actually running.
  A Docker build failure or an unhandled crash never reaches that code, so a separate
  `if: failure()` step curls CallMeBot directly — the one thing that would notice a
  failure the app itself never got the chance to report (§7).

**What did NOT change:** no application code, no test, no Dockerfile line.
`docker compose up -d` still works unchanged for local development. This is a pure
deployment-target addition, which is why it went through the constitution's Design
Decisions log rather than a new spec — the relay's behavioural contract (`spec.md`)
is identical either way.

**Operational note:** running both deployments concurrently against the same account
would double-delivery any post published after they diverge, since each maintains
its own copy of `seen.json` independently once local's on-disk file and git's
committed copy stop being the same bytes. The local container is stopped once the
Actions workflow is verified working end to end.

## Amendment A-7 — a paused account went unexplained for three weeks (2026-10-10)

From the A-6 deployment on 2026-09-17 until 2026-10-10, every scheduled run ended
`sent=0`. The workflow stayed green throughout, and nothing reached WhatsApp.

**Root cause, found by probing the live service:** CallMeBot had paused the account.
It answered **HTTP 208**, echoing our text and then adding:

    Your Account is Paused due to technical issues. Please send the word "resume"
    to your bot (+34 …) to re-enable the service for your number.

The sink behaved correctly under FR-12: no `queued` marker, so not delivered and not
marked seen. But the ERROR line quoted `body[:120]`, and the first 120 characters are
always our own echoed message, so the cause was cut off on every run. That violates
§7 ("degraded states are logged … with the reason"). It also misled the diagnosis:
the outage started at the same time as the move to Actions, so the first suspect was
GitHub's datacenter IPs. A send from the operator's machine failed the same way,
which ruled that out. The operator sent "resume", and delivery came back.

**Fix:** the failure reason is now the service's own words. The echo is stripped,
HTML is removed, and the result is capped at 300 characters
(`sinks/callmebot._reason`). The captured paused body is a fixture
(`tests/fixtures/callmebot_paused.html`).

**A-7.1 — the fix opened a leak path, so the tests came first.** Quoting more of the
body sends more third-party bytes into exception text and logs. The old code already
had this path: no test fed a 2xx body containing the key. The new
`tests/adversarial/test_secret_leaks.py` failed first: a key echoed in a 200 body
reached both `str(DeliveryFailed)` and the ERROR log, in raw, URL-encoded and
HTML-escaped form. The reason is now scrubbed of all three forms, before truncating
(a cut could expose part of the key) and again after unescaping. These tests do not
call `logging_setup.configure()`, so the sink cannot rely on root redaction.

**Still open:** the A-6 failure alert curls the same CallMeBot account and discards
the body, so it could not fire while the account was paused. The only signal that
reached the operator was GitHub's own failure email, sent for a Docker Hub 429 on an
unrelated run.

## Amendment A-8 — a failed delivery now fails the run (2026-10-10)

Follows A-7. Logging the reason solved half of §7. Nobody reads the logs of a run
that shows as green.

**Defect:** `Pipeline.run_once` recorded `result.failed`, but `run --once` only
exited non-zero on a source outage. Every paused-account run exited 0. GitHub only
emails on failed runs, so its email, the one alarm independent of the delivery
service, never fired. The one failure email that did arrive came from an unrelated
Docker Hub 429.

**Changes:**
- `run --once` exits 1 when `result.failed`, and the summary line prints `failed=N`.
- `poll.yml` "Persist state" runs on `!cancelled()`, not only on success. This defect
  was latent before the exit-code change, because outage runs already exited 1 and
  skipped it. With delivery failures also exiting 1, a batch that sent 3 posts and
  then failed would have lost those 3 seen IDs and re-sent them on the next run.
- `poll.yml` "Alert on workflow failure" reads CallMeBot's reply instead of
  discarding it. If the reply is not `queued`, it adds an `::error::` annotation to
  the run. It does not print the reply, which echoes the phone number.

**What this changes about the design:** the A-6 belief that the alert step "would
notice" a failure was wrong whenever the failing component *is* the alert channel.
Alerts now have two independent routes: WhatsApp (best effort) and GitHub's
failed-run email (independent of CallMeBot).

## Amendment A-9 — run summaries, a dead man's switch, traceability (2026-10-10)

A-7 and A-8 made failures visible *if someone looks*. A-9 removes the looking.

**Run summary.** A new `summarize` CLI subcommand (`report.py`) renders the run's
log as a GitHub job summary. It shows a headline verdict with counts, the mirror
that answered, a link per delivered post, the problem lines, and the full log in a
collapsed section. It is built from the log, not from in-process state, so it also
covers runs that crashed or failed to build. It loads no config, so it can also
explain runs that died on a bad `.env`. The log quotes third-party bytes, so all of
it is HTML-escaped inside `<pre>` blocks (§4). The tests try script injection,
breaking out of the `<pre>` block, and markdown injection.

**Dead man's switch (Healthchecks.io).** The workflow pings `/start`, then success
or `/fail`, with the run URL and log tail as the body. If no ping arrives, the
service alerts the operator. That covers failures the app can never report:
GitHub delaying or disabling the schedule, or a workflow too broken to run. The
alert goes through neither GitHub nor CallMeBot. The ping URL is a secret
(`HEALTHCHECKS_PING_URL`); if it is unset, the run gets a warning and no pings.

**Traceability.** `delivered tweet_id=N` is logged per successful send. State
commits carry the run URL, so `git log -p state/seen.json` links every tweet ID to
the run that delivered it and that run's summary. A per-line run ID was considered
and rejected (§8): every log line already sits in exactly one run's log.

**Leaving the masked log viewer.** GitHub masks secrets only in its own log viewer.
`run.log` now goes to the summary page (public repo) and to Healthchecks. Two
consequences:
- The failure reason now drops the phone number. CallMeBot's reply opens with
  `Message to: <phone>`. Adversarial test added.
- A workflow step removes the secret values from `run.log` before either reader
  sees it. This backstop covers output the app does not control, e.g. a pydantic
  config error echoing its input.

**Docker Hub 429.** The base image now comes from `public.ecr.aws/docker/library/`,
the same official image without Docker Hub's anonymous pull limit from shared CI
IPs. `# syntax=docker/dockerfile:1` was removed, because it made BuildKit pull its
frontend from Docker Hub too.

## Amendment A-10 — code review fixes before merging A-7..A-9 (2026-10-10)

A pre-merge review (superpowers:requesting-code-review) found no critical issues.
It did find that the new run summary could still claim deliveries that never
happened, which runs against the incident A-7..A-9 exist to fix (001 FR-12).

**I-1: forged summary lines.** `report.py` matched `delivered tweet_id=` and
`fetched N posts from` anywhere in the log. Third-party text reaches the log inside
WARNING lines (dropped-item reasons quote the input), so a hostile feed could make
the public summary show a fake mirror and fake "Delivered" links. The reviewer
reproduced this, and so did the new tests. Fixes:
- Every pattern is anchored to a whole line in our own log format.
- The *last* result line wins.
- `ConsoleSink` prefixes every line with `| `, so a dry-run post cannot pass for a
  log line.
- `tests/adversarial/test_report_forgery.py` covers each of these.

**I-2: a dry run read as a delivery.** The result line now carries `dry_run=`. A
dry-run summary says "dry run, would send N", and its post list is headed "Rendered
(dry run)".

**I-3: a failed liveness message gave a green run.** The bootstrap send and the
withheld notice now set `failed`, so A-8 covers every delivery, not just posts.
Without this, a paused channel on a first run (or after retargeting the account)
would reproduce A-7.

**I-4 (pre-existing and severe): dry runs swallowed pending posts.** The pipeline
marks rendered posts as seen whichever sink it is given, and the workflow committed
that state. So the documented "manual verification, sends nothing" run made every
pending post undeliverable. This was latent since A-6, and the planned post-merge
verification run would have triggered it. Fixes:
- `run --dry-run` now works on a throwaway copy of the history.
- The workflow's Persist step skips dry runs as a second guard.

**Minor fixes:**
- 4xx failures show the service's own words (A-7 had only covered 2xx).
- Secrets are scrubbed before the echo is stripped as well.
- Persist uses `always()`, so sends made before a job timeout are saved.
- The summary step never rebuilds a missing image.
- Dry runs do not ping Healthchecks, because a manual check is not a heartbeat.

**Accepted as intended (M-6):** during a long outage every scheduled run fails, so
GitHub sends a failure email each time. That is the deliberate trade-off of A-8.
Healthchecks alerts only on a change of state and stays the calm primary signal.

## Amendment A-11 — a message the channel refuses no longer blocks the queue (2026-10-10)

**Incident.** After the account was resumed, CallMeBot answered **HTTP 403** (an
Apache "Forbidden" page) for one post, `2108539369770672204`, on every attempt from
14:52 onward. It accepted a plain test message and the workflow's failure alert from
the same account in the same period. Delivery stops at the first failure (E-5), so
that one post blocked every post behind it indefinitely: 7 were queued when this was
found. The trigger inside the text is not known. Finding it would mean sending
variants to the operator's phone, and the flaw needs fixing whatever the trigger is.

**Decision (spec 001 E-21, D-4).** A refusal of *this message* (HTTP 4xx other than
429) raises `MessageRejected`, a subclass of `DeliveryFailed`. The pipeline then
retries that post once with `render_minimal()`: fixed wording plus the post link,
with no post text.
- If accepted, the post is marked seen, the queue moves on, and the log shows
  `delivered in minimal form tweet_id=N` at WARNING, which the run summary lists
  under Problems.
- If the minimal form is refused too, its fixed text cannot be the cause, so it is
  an ordinary delivery failure and the A-8 alerting applies.

Only 400/403/413/414/422 count as a refusal of the message, and only when the
scrubbed reason has no account or rate-limit wording (`too many`, `limit`, `quota`,
`blocked`, `paused`, `api key`, `invalid`, …). 401, 404, 429, 5xx, timeouts and
account-level replies (A-7's "paused") get no retry: they are about the channel, and
a retry only adds traffic. *Tightened after review, which found the first version
treating every 4xx except 429 as message-specific, including a 403 that said
"blocked: too many requests".*

**Accepted trade-off:** a one-off, channel-level 403 with no telltale wording will
permanently deliver that one post in minimal form, even though its text was fine.
The operator still gets the link, the WhatsApp message says the text could not be
delivered, and the run summary's headline shows ⚠️ with a count. That beats blocking
the queue.

**Unverified:** the cause of the 403 is a hypothesis, namely content filtering of
that post's text. It could not be confirmed without sending variants. The fix is
sound whichever cause it was.

**Found while investigating: two relays were running.** The local container retired
in A-6 was still up. `restart: unless-stopped` had brought it back on every boot
since. After the operator resumed CallMeBot, both it and the Actions run delivered
the backlog, and the operator confirmed duplicates. It also kept retrying the
refused post every 15 minutes. The container is now stopped. `docker compose down`
is needed to stop it returning on boot, and CLAUDE.md's warning about this was not
enough on its own.

**Mirrors.** `DEFAULT_INSTANCES` was re-verified (specs/002 research R-2):
- `nitter.netbub.com` (now a bot challenge) and `nitter.jaydenha.uk` (an HTML access
  queue) were replaced with `nitter.pp.ua` and `shitter.thepixora.com`.
- The list is ordered fastest first. `meowing.monster` (12 s) goes last.
- The live tests also caught `kareem.one` failing and then recovering within
  minutes. Failover covers that, and spec 002 will make it visible.

## Amendment A-12 — base image moved off AWS ECR Public (2026-10-21)

From 2026-10-20 the ECR Public mirror chosen in A-9 started refusing anonymous
pulls from GitHub's shared runner IPs: `429 Too Many Requests: Data limit
exceeded`. Three relay runs and the first mirror-health run (spec 002) failed at
the image build. This is the same failure as Docker Hub's, from a different
registry.

The base image now comes from `mirror.gcr.io/library/python:3.12-slim`, Google's
pull-through mirror of the same official Docker Hub image. Probed 2026-10-21: it
serves the manifest without authentication. Its rate limits are not documented.

Rejected: caching the built image in GitHub's own registry (ghcr.io). It avoids
third-party limits entirely, but it needs `packages: write`, a cache-key scheme and
login steps in both workflows (§8). It is the next step if this mirror rate-limits too.

## Amendment A-13 — delivery channel replaced by spec 003 (2026-10-21)

CallMeBot's free quota ran out on 2026-10-20 (`You have 0 messages left … subscribe`),
so every check failed from then on. Spec `003-bot-chat-delivery` replaces the channel
with a private Telegram bot chat and adds operator commands. Everything in this plan
that names CallMeBot (DD for the sink, A-3, A-5, A-7, A-11's refusal codes) is
historical from here; `MessageSink` is now specified by
`specs/003-bot-chat-delivery/contracts/message-sink.md`. The relay logic (dedup,
ordering, cap, outage notice, minimal-form retry) is unchanged. Spec 003 also stops
dropping posts that have no text of their own (003 US-7), changing this spec's
treatment of them as malformed.

## Amendment A-14 — second mirror swap (2026-10-21)

The spec 002 mirror check reported AT RISK (1 of 4 in-use healthy) on 2026-10-21. Probed
twice each from the operator's machine at about 19:40 UTC, then through the relay's own
`check-source`:

| Mirror | Result | Decision |
|---|---|---|
| `nitter.kareem.one` | 200, 19 posts | keep |
| `nitter.meowing.monster` | 200, 19 posts (502 earlier the same day) | keep, last |
| `nitter.pp.ua` | 403 both times | **out** |
| `shitter.thepixora.com` | 403 both times | **out** |
| `nitter.jaydenha.uk` | 200, 19 posts (an HTML access queue on 2026-10-10) | **in** |
| `nitter.mie.foundation` | 200, 19 posts; first seen as a 002 candidate | **in** |

This is the swap spec 002 was built to make easy: both replacements came from its
candidate list.
