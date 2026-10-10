# Implementation Plan: Mirror Health & Status Page

**Spec:** `./spec.md` (Clarified, 0 open questions, D-1..D-4) | **Research:** `./research.md`
**Created:** 2026-10-10

## Constitution Gate

Checked before design. Any "no" blocks the plan.

| Principle | Compliant? | Notes |
|-----------|-----------|-------|
| §1 Spec approved, no open clarifications | ✅ | 0 markers. D-1..D-4 recorded; D-3 revised at the operator's request. An automated scan finds no technology names in `spec.md` |
| §2 Test-first plan | ✅ | Every phase below starts with its failing tests. Real probe responses from R-2 become fixtures before any parsing code changes |
| §3 External systems behind adapters | ✅ | `MirrorProbe`, `MirrorDirectory`, `HistoryStore`, `WarningTracker`, plus a `Clock`. Contracts are in `contracts/`. The status page and Healthchecks are reached only from the workflow shell, behind the CLI's exit code (DD-6) |
| §4 Untrusted input validated | ✅ | The list, every host it names, and every mirror response are hostile. Strict URL validation, probe-time address checks (DD-4), size caps, the existing hardened parser, a closed set of labels, and **nothing third-party is published** (FR-16) |
| §5 Unit tests network-free | ✅ | Probe classification runs against fixtures captured on 2026-10-10. Real list and mirror probes are `@pytest.mark.live` only |
| §6 Secrets from env only | ✅ | The probe needs no credentials (FR-19). `GITHUB_TOKEN` (issues) and the Healthchecks URL arrive as env vars in the workflow and are covered by the existing scrub and leak tests |
| §7 Failures surface to operator | ✅ | At risk: the run fails, plus Healthchecks `/fail`. Check broken: the run fails. Check stopped: the Healthchecks grace period runs out. Discovery stale: shown on the page. Each is distinguishable (AC-1.7) |
| §8 No unjustified abstraction | ✅ | One new module per adapter, each with exactly one production caller. No new runtime dependency: httpx, defusedxml and pydantic already cover it. The page is three static files with no framework |

## Technical Context

| Choice | Justification against a requirement |
|---|---|
| **Same package, new CLI command `probe-mirrors`** | FR-3 requires usable to mean exactly what the relay accepts. Sharing the fetch and parse code makes that true by construction instead of by duplication |
| **Same Docker image** | One tested artefact. The probe has no dependencies the relay lacks |
| **A second workflow, `mirrors.yml`** (cron `17 */6 * * *`) | FR-1: independent of the relay's checks. A crash in either cannot stop the other. At 17 minutes past, it avoids colliding with the relay's `*/15` |
| **`status.d420.de` JSON API** as the community list | R-1: the only list that is current and machine-readable. Only `url` is read |
| **History on an orphan branch `mirror-status`**, rewritten as a single commit each round | FR-18 bounds the data, so git history adds nothing but growth. Keeping it off `main` means no commit noise and no conflicts with the relay's `seen.json` commits |
| **GitHub Pages deployed from Actions** | US-3: public, needs no sign-in, free on a public repo (R-4). The source lives in `main/site/`, and each round publishes `status.json` next to it |
| **GitHub Issues** for soft warnings | FR-10: durable, at most one per mirror, visible outside the page, and GitHub emails the operator on open and close |
| **Healthchecks.io**, a second check | FR-8 and FR-9: a state-change channel that does not depend on GitHub or CallMeBot, and doubles as the dead man's switch (period 6 h + grace 18 h = 24 h, D-1). The free plan has 18 checks spare (R-4) |

## Architecture

```
mirrors.yml (cron 17 */6) ── checkout main ── checkout mirror-status → ./data
        │
        ▼
 python -m tweet_relay.cli probe-mirrors --data ./data --site-out ./_site
        │
        ├─ MirrorDirectory.list()      status.d420.de → validate_mirror_url → ≤25 candidates
        │     (failure → keep last candidates from data/latest.json, FR-14)
        ├─ roster = in-use (config) ∪ former (history, D-2, priority) ∪ discovered, cap 25
        ├─ MirrorProbe.probe(host) × N     fetch_one() shared with NitterRssSource
        │     address check at probe time (DD-4) → ProbeResult(reason ∈ closed set)
        ├─ health.evaluate(results, clock)  freshness reference from in-use only (FR-4)
        ├─ HistoryStore.append + prune(90 d) → data/history.jsonl, data/latest.json
        ├─ status.build(history) → _site/status.json (uptime 7/30 d, trend, verdict)
        ├─ WarningTracker.sync(desired)     open/close issues (24 h rule, FR-10)
        └─ exit 0 = ok · 3 = AT RISK · 1 = check broken · 2 = config error
        │
        ▼
 workflow shell: commit+force-push data → deploy Pages (site/ + status.json)
                 → Healthchecks: exit 0 → ping · 3 → /fail · 1/2 → no ping (FR-9 via grace)
                 → job summary states the cause (AC-1.7)
```

**Functional core, imperative shell.** Freshness, health, uptime, the 24-hour rule,
episode state and the roster are pure functions of the results and a clock, and
are property-tested. Adapters only do I/O. The workflow only moves files and pings.

## Design Decisions

| # | Decision | Alternatives rejected | Why |
|---|----------|----------------------|-----|
| DD-1 | Extract `fetch_one(client, base, handle, cfg) -> list[Tweet]` from `NitterRssSource.fetch`, raising `MirrorError(reason)`, a subclass of `SourceUnavailable` | A separate probe fetcher; or calling `NitterRssSource` once per mirror | FR-3 needs the probe's "usable" to be *identical* to the relay's. A second fetcher would drift, and per-mirror sources lose the reason label. A subclass keeps the relay's `except SourceUnavailable` working unchanged |
| DD-2 | The reason set is a `StrEnum` of 10 values (data-model.md) | Free-text error strings (today's `SourceUnavailable` messages) | FR-5 and FR-16: labels are published, and free text could carry third-party bytes |
| DD-3 | `validate_mirror_url()`: https only, bare host, no userinfo, port or path beyond `/`, hostname charset, **`not ip.is_global` rejected**. Shared with the relay's config | Reuse `_validate_instance` as it is; or a separate stricter copy for discovery only | R-3 found that the current check misses CGNAT and accepts ports and paths. One validator means one place to get it right, and the relay's E-20 is tightened at the same time. Breaks nothing: no configured mirror has a port or path |
| DD-4 | Resolve the host at probe time; refuse if *any* resolved address is not global. **DNS rebinding between the check and the connect is accepted** (Risks) | Pinning the connection to the vetted IP | Pinning means custom TLS-SNI handling in httpx, which is complexity §8 rejects. What makes the remaining risk acceptable is FR-16: nothing from a response is published, so a successful rebinding yields a GET with no secrets and no visible result, on an ephemeral runner |
| DD-5 | History is `history.jsonl` (one result per line) plus `latest.json` (last round, last good candidate set, discovery status, episode state). The orphan branch is force-pushed as one commit | Append-only commits; an external database; Actions cache | It fits FR-18 (about 1.5 MB at 90 days). Free. Readable with `git show`. The cache is evictable, so it would lose history silently |
| DD-6 | Exit code **3** for at risk, distinct from **1** for broken. The workflow maps them to Healthchecks and to the summary's cause | Healthchecks calls from Python; or one shared failure code | AC-1.7 needs the two causes distinguishable. Keeping Healthchecks in the shell mirrors poll.yml (A-9) and keeps its URL out of the app. Only the at-risk path pings `/fail`, so Healthchecks' own up/down state machine gives the once-per-episode behaviour of D-3 for free |
| DD-7 | A broken run **does not** ping Healthchecks | Pinging `/fail` with "check broken" | FR-9 (D-1) wants "stopped" reported after 24 h and prefers a late warning to a false alarm. The run's own failure email already covers "broken" at once. An unpinged Healthchecks check reaches its 24 h grace naturally if the breakage lasts |
| DD-8 | `WarningTracker` is a Python adapter over the GitHub REST API (httpx + `GITHUB_TOKEN`). Issues carry the label `mirror-health` and the title `Mirror unhealthy for 24h: <host>` | `gh issue` calls from bash | §2: the open/close reconciliation is logic, so it belongs in tested code. The title is built only from a validated host (FR-16). Issues are matched by label plus exact title, so reruns are idempotent |
| DD-9 | The page is plain `index.html` + `app.js` + `style.css`. It builds the DOM with `textContent` only. A strict CSP `<meta>` allows `default-src 'self'`. `status.json` is **precomputed** by Python | Client-side uptime maths; a framework; a static-site generator | FR-17 is a second guard after FR-16: there is no `innerHTML` anywhere, and the CSP blocks inline and remote script. Precomputing keeps the logic in tested Python and the JavaScript render-only. The stale-data warning (AC-3.3) is the one view-time check in JavaScript |
| DD-10 | Freshness reference = max `newest_post` across usable **in-use** results, ignoring times more than 5 min in the future (clock skew). Stale if `reference − newest > 6 h` | Reference from all mirrors; median; wall-clock age | FR-4 and E-2: a hostile candidate cannot move the reference. Wall-clock age would mark everything stale when the account is quiet (E-4) |
| DD-11 | **Former** mirrors (D-2) are hosts that appear in history as in-use but are not in the current config. They take the first candidate slots, then the discovered ones, up to 25 | Tracking them separately in config | It is derived from data we already keep, with no new operator-maintained state |
| DD-12 | Probes run **sequentially**, with the relay's 15 s timeout | Concurrent probes | 25 × 15 s is at most about 6 min, inside a 15-minute job limit. These are volunteer servers (Out of Scope: politeness), and running one at a time also makes timing measurements honest |

## Risks

| Risk | Likelihood | Mitigation |
|---|---|---|
| `status.d420.de` dies or changes format | Medium (one person runs it) | FR-14: keep the last candidates, show discovery as stale, never fail the round. In-use monitoring, the core goal, does not depend on it |
| DNS rebinding reaches an internal address (DD-4) | Low | Nothing from responses is published (FR-16). GET only, no credentials, ephemeral runner. Re-evaluate if the probe ever gains a secret |
| GitHub disables the schedule on an inactive repo | Low–medium (R-5) | The Healthchecks grace period catches a stopped probe within 24 h whatever the cause (FR-9) |
| Mirrors block the runner's IP range | Medium | It appears as `refused answer` / `sent elsewhere`, a true statement about the mirror's usability *from where the relay runs* |
| A force-push race on `mirror-status` | Low | `concurrency: mirror-probe`, no cancel-in-progress (E-19) |
| A corrupt history file | Low | E-20: start a fresh history, log at ERROR, still record and publish this round |
| The page reveals which mirrors are used | Accepted | Already public through this repo's config and `.env.example` |

## Phases

Each phase is independently verifiable and starts with failing tests (§2).

1. **Shared fetch + reason labels** (DD-1, DD-2). Capture fixtures from R-2's
   responses: the 307 challenge, the HTML access queue, the 403, a valid feed.
   `fetch_one` classifies every reason. The relay's 328 tests stay green.
2. **Strict validator** (DD-3). Adversarial tests for CGNAT, ports, paths,
   userinfo, IP literals and IDN tricks. Applied to config and discovery.
3. **Health core** (DD-10). Pure functions for freshness, healthy, the urgent
   verdict, the 24 h soft rule, uptime (with D-4's "unknown counts as healthy") and
   episode transitions. Hypothesis property tests: a candidate never moves the
   reference; adding a healthy result never lowers uptime.
4. **Discovery adapter** (R-1). `MirrorDirectory` over `status.d420.de`: size cap,
   strict parse, per-entry drop, the `domain`/`url` consistency check, cap 25,
   fallback to the last good set. Adversarial: oversized, malformed, duplicates,
   internal addresses, 1000 entries.
5. **History + status.json** (DD-5, DD-11). Append, prune at 90 days, rebuild from
   a missing or corrupt file, the former-mirror roster. A test that **no
   third-party byte reaches `status.json`** (marker strings planted in every
   fixture).
6. **CLI `probe-mirrors`** (DD-6). Exit codes 0/1/2/3, job summary text that states
   the cause.
7. **WarningTracker** (DD-8). A fake GitHub API: open after 24 h with at least 2
   probes, one per mirror, auto-close, idempotent reruns, never for candidates.
8. **Status page** (DD-9). Render-only JavaScript, the CSP, a stale banner after
   12 h, mobile layout. Checks: no `innerHTML`/`eval` in `app.js`, plus a manual
   check on a phone.
9. **Workflow `mirrors.yml`** + Pages enablement + the second Healthchecks check.
   Then one live run, verified with `quickstart.md`.

## Operational note (outside this feature)

R-2 found the relay at exactly 2 healthy in-use mirrors today. Replacing
`nitter.netbub.com` and `nitter.jaydenha.uk` with `shitter.thepixora.com` and
`nitter.pp.ua` in `NITTER_INSTANCES` would restore headroom immediately. It is a
configuration change, so it does not have to wait for this feature, but it is the
operator's call.
