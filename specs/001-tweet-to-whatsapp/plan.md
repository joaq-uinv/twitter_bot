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

