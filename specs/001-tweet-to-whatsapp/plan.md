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
| DD-3 | Classify post kind from the **author segment of the link** | `RT by @` title prefix | The prefix is presentation text and format-dependent; the link path is structural (F-3) |
| DD-4 | Verify channel title names the configured handle | Trust the mirror | FR-7, E-7 — a mirror could serve the wrong or a spoofed account |
| DD-5 | Reject links not matching `/<handle>/status/<digits>` before rewriting to `x.com` | Rewrite host blindly | Blind rewriting turns an attacker-chosen path into a plausible x.com link delivered to the operator (E-10) |
| DD-6 | Outage notification is **edge-triggered** (state carries `outage_notified`) | Notify every failed check | AC-4.3 — a multi-day outage would otherwise send hundreds of messages |
| DD-7 | Per-check cap withholds rather than drops | Drop as stale; ignore cap | D-3; preserves FR-2 exactly-once while respecting the ~80/day ceiling |
| DD-8 | Long-running container with internal scheduler | Host cron invoking one-shot container | R-5 — keeps scheduling inside the artefact under test and portable to any Docker host |
| DD-9 | `syndication.py` gated for deletion | Ship it anyway | It returned 429 on every probe. §8 — an unverifiable adapter is speculative complexity |

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
