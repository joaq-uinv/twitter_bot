# Tasks: Mirror Health & Status Page

**Plan:** `./plan.md` | **Baseline:** `main` at 204f6db, 351 tests green.

`PT` means `docker compose run --rm --entrypoint python relay -m pytest`.

- **"RED"** means the named tests fail for the stated reason, usually a missing
  module or function, never a typo.
- **"GREEN"** means those tests pass **and** the full suite stays green: `PT` reports
  `351 + new` passed, 0 failed.
- Per §2, every implementation task comes right after its test task.

**Parallelism.** `[P]` marks a *test+implementation pair* that touches no file
shared with another `[P]` pair. Inside a pair the order is always test, then
implementation. Pairs marked `[P]` may run concurrently once their stated
dependency is met.

---

## Phase 1: Shared fetch and reason labels (DD-1, DD-2)

**T001 Capture fixtures from research R-2.** ✅ 2026-10-11
- Files: `tests/fixtures/mirrors/feed_pp_ua.xml` (a valid feed),
  `access_queue_jaydenha.html` (200 + HTML), `forbidden_tiekoetter.html` (403 body),
  `d420_instances.json` (the list, R-1).
- Captured with `curl`, as in research.md. For the 307 challenge, record only the
  status and `Location` header, in `goaway_netbub.txt`.
- Verify: `ls tests/fixtures/mirrors | wc -l` gives `5`, and
  `grep -rlE "CALLMEBOT|apikey" tests/fixtures/mirrors` gives nothing.
- Covers: FR-3, E-6 (fixtures for §5).

**T002 Test the closed sets.** ✅ 2026-10-11 `tests/unit/test_mirror_models.py`
- `Reason` has exactly the 10 values in data-model.md, and `Role` and `Freshness`
  are exact.
- `ProbeOutcome` and `ProbeResult` have no `str` field except `host`, which is a
  validated `Host`.
- `ProbeResult` invariants: `freshness is None` if and only if `not usable`;
  `reason == STALE` if and only if `usable ∧ freshness == STALE`.
- Verify: RED with `ModuleNotFoundError: tweet_relay.mirrors`.
- Covers: FR-5, FR-6, FR-16.

**T003 Implement the models.** ✅ 2026-10-11 `src/tweet_relay/mirrors/__init__.py`, `mirrors/models.py`
- Verify: GREEN (T002).
- Covers: FR-5, FR-6.

**T004 Test `fetch_one` classification.** ✅ 2026-10-11 `tests/unit/test_fetch_one.py`, using respx
and the T001 fixtures. Each case raises `MirrorError` with exactly the reason given:
- timeout → `timed_out`
- `ConnectError` → `unreachable`
- 403 fixture → `refused_answer`
- 307 → `sent_elsewhere`
- oversized (both the declared and the streamed size) → `too_large`
- access-queue HTML → `malformed_content`
- a feed for a different account → `wrong_account`
- a feed with 0 valid items **returns `[]`** (amended 2026-10-11: the relay's
  source contract guarantee 3 treats an empty feed as a quiet account, not a
  failure, so the **probe** maps `[]` to `no_posts` in T009 instead)
- a valid feed returns tweets

`MirrorError` must be an instance of `SourceUnavailable`.
- Verify: RED with `ImportError: fetch_one`.
- Covers: FR-3, FR-5, E-5 to E-9.

**T005 Extract `fetch_one` and `MirrorError`.** ✅ 2026-10-11 `src/tweet_relay/sources/nitter_rss.py`
- `NitterRssSource.fetch` loops over `fetch_one`. Its log lines and its
  `SourceUnavailable` message stay unchanged for the relay.
- Verify: GREEN (T004), and `PT tests/unit/test_nitter_rss.py tests/adversarial`
  stays green.
- Covers: FR-3 (usable means what the relay accepts).

## Phase 2: Strict validator and the probe (DD-3, DD-4)

**T006 Test `validate_mirror_url`.** ✅ 2026-10-11 `tests/adversarial/test_mirror_url.py`
- Rejects:
  - `http://`
  - userinfo, a port, a path, a query or a fragment
  - IPv4 and IPv6 literals
  - hosts resolving to `100.64.0.1` (CGNAT) or `169.254.169.254`
  - bad hostname characters, labels over 63 characters, names over 253
  - an empty host
- Accepts the 4 `DEFAULT_INSTANCES` and an `xn--` host.
- DNS is monkeypatched, so there are no network calls (§5).
- Verify: RED with `ImportError`.
- Covers: FR-11, E-10.

**T007 Implement `validate_mirror_url`.** ✅ 2026-10-11 `src/tweet_relay/config.py`
- `_validate_instance` delegates to it (plan DD-3 tightens 001 E-20).
- Verify: GREEN (T006), and `PT tests/adversarial/test_ssrf.py tests/unit/test_config.py`
  stays green.
- Covers: FR-11.

**T008 Test the probe-time address refusal.** ✅ 2026-10-11 `tests/adversarial/test_probe_address.py`
- A resolver returning a private, loopback, link-local or CGNAT address gives
  `ProbeOutcome(usable=False, reason=REFUSED_ADDRESS, ms=None)`.
- The respx route records **0 calls**.
- Verify: RED with `ImportError: HttpMirrorProbe`.
- Covers: FR-11, E-10.

**T009 Test the probe's outcome mapping.** ✅ 2026-10-11 `tests/unit/test_mirror_probe.py`
- Each `MirrorError` reason from T004 maps to its outcome, and `[]` maps to `no_posts`.
- `ms` is measured with an injected clock.
- `newest` ignores posts dated more than 5 minutes in the future.
- Any non-`MirrorError` exception propagates (contract 2: check broken).
- Verify: RED.
- Covers: FR-3, FR-6, E-2, AC-1.7.

**T010 Implement `HttpMirrorProbe`.** ✅ 2026-10-11 `src/tweet_relay/mirrors/probe.py`
- Verify: GREEN (T008, T009).
- Covers: FR-1, FR-2, FR-3, FR-11.

## Phase 3: Health core, pure functions (DD-10) [P after T003]

**T011 Test freshness.** ✅ 2026-10-11 `tests/unit/test_health.py`
- The reference is the newest in-use `newest`.
- Stale when the newest post is more than 6 h behind the reference.
- `unknown` when no in-use result is usable.
- A quiet account (all mirrors equally old) gives fresh.
- Hypothesis property: **adding any candidate result never changes the reference**.
- Verify: RED.
- Covers: FR-4, E-1, E-2, E-3, E-4.

**T012 Implement `health.evaluate_round`.** ✅ 2026-10-11 `src/tweet_relay/mirrors/health.py`
- Verify: GREEN (T011).
- Covers: FR-4, FR-6, D-4 (`healthy = usable ∧ freshness ∈ {fresh, unknown}`).

**T013 Test the urgent verdict and episodes.** ✅ 2026-10-11 `tests/unit/test_health.py`
- `at_risk` exactly when in-use healthy < 2, including the boundary at 2.
- `in_use_total < 2` is always at risk (E-18).
- `at_risk_since` is set on the first at-risk round, kept while the risk lasts, and
  cleared on recovery.
- `all_clear` is true only on the round that clears it.
- Verify: RED.
- Covers: FR-7, AC-1.1, AC-1.2, AC-1.3, AC-1.6, E-18.

**T014 Implement the verdict and `EpisodeState` transitions.** ✅ 2026-10-11 `mirrors/health.py`
- Verify: GREEN (T013).
- Covers: FR-7, AC-1.6.

**T015 Test the soft-warning rule.** ✅ 2026-10-11 `tests/unit/test_health.py`
- Opens when **every** result in 24 h is unhealthy **and** there are at least 2.
- A host unhealthy for 23 h with one healthy result gives no warning.
- An open warning stays a single warning.
- Closes on the first healthy result, and **only** then (or when no longer in use): a thin
  window caused by delayed rounds never closes a warning (found while writing T015).
- Candidates and former hosts never open a warning; a former host's warning closes.
- A flapping host (alternating) never opens one.
- Verify: RED.
- Covers: AC-2.1 to AC-2.5, FR-10, E-15, E-16, E-17.

**T016 Implement `health.plan_warnings`.** ✅ 2026-10-11 (renamed from `desired_warnings`: it returns an open/update/close plan) `mirrors/health.py`
- Verify: GREEN (T015).
- Covers: FR-10.

## Phase 4: Discovery and roster (R-1, DD-11) [P after T007]

**T017 Test `StatusD420Directory`.** ✅ 2026-10-11 `tests/adversarial/test_directory.py`, respx
and the `d420_instances.json` fixture.
- The real fixture yields 9 hosts.
- These raise `DirectoryUnavailable`: a document over 1 MiB, non-JSON, a missing
  `hosts` key, more than 1000 entries, a redirect.
- These are dropped per entry with `rejected` incremented: a bad `url`, a `domain`
  that differs from `url`'s host, a non-https entry, a CGNAT entry.
- Only hosts are returned; there is no other field.
- Verify: RED.
- Covers: FR-11, FR-12, FR-16, E-11.

**T018 Implement `StatusD420Directory`.** ✅ 2026-10-11 `src/tweet_relay/mirrors/directory.py`
- Verify: GREEN (T017).
- Covers: AC-5.1, FR-12.

**T019 Test `build_roster`.** ✅ 2026-10-11 `tests/unit/test_roster.py`
- In-use first. Then former (from history), then discovered.
- De-duplicated. In-use hosts are never candidates.
- Capped at 25, with former taking priority over discovered.
- On `DirectoryUnavailable`, uses `latest.discovery.candidates` and keeps
  `last_ok` unchanged.
- **Never modifies the relay configuration**: the config object stays identical.
- Verify: RED.
- Covers: FR-13, FR-14, FR-15, AC-5.4, E-12, E-13, E-17, D-2.

**T020 Implement `roster.build_roster`.** ✅ 2026-10-11 `src/tweet_relay/mirrors/roster.py`
- Verify: GREEN (T019).
- Covers: FR-13, FR-14.

## Phase 5: History and status.json (DD-5) [P after T003]

**T021 Test `DirHistoryStore`.** `tests/unit/test_history.py`, using `tmp_path`.
- Round-trip works. Results older than 90 days are pruned on save.
- Writes are atomic: a crash between write and rename leaves the old file intact.
- Bad lines are dropped and counted. More than 50% bad gives an empty history with
  `corrupt=True`. A missing directory is an empty history.
- Verify: RED.
- Covers: FR-18, AC-4.3, E-20, E-21.

**T022 Implement `DirHistoryStore`.** `src/tweet_relay/mirrors/history.py`
- Verify: GREEN (T021).
- Covers: FR-18.

**T023 Test `build_status`.** `tests/unit/test_status.py`
- Fields exactly as in data-model.md.
- `uptime_7d` and `uptime_30d` count unknown freshness as healthy; null when there
  is no data.
- `trend` has at most 40 entries, newest last, with null for "not probed".
- Candidates are ordered healthy first, then by `uptime_30d` descending.
- `warnings` lists the open ones; `discovery` carries `last_ok`, `accepted` and
  `rejected`.
- Verify: RED.
- Covers: AC-3.1, AC-3.2, AC-3.4, AC-4.1, AC-4.2, AC-5.2, AC-5.3, D-4.

**T024 Implement `status.build_status`.** `src/tweet_relay/mirrors/status.py`
- Verify: GREEN (T023).
- Covers: the same as T023.

## Phase 6: Round orchestration and CLI (DD-6, DD-12)

Depends on T010, T014, T016, T018, T020, T022 and T024.

**T025 Test `run_round`.** `tests/unit/test_round.py`, wired with
`FixtureMirrorProbe`, `StaticDirectory`, `MemoryHistoryStore` and `FakeTracker`.
- Probes run sequentially, one per roster host.
- History is appended and `latest.json` updated.
- The tracker is reconciled: open the missing, update the persisting, close the
  recovered.
- **A tracker failure still saves and publishes, then reports check-broken.**
- **The relay's state file and sink are never touched**: no `CallMeBotSink` is
  constructed, and the `seen.json` bytes are unchanged.
- Verify: RED.
- Covers: FR-1, FR-2, FR-10, AC-2.3, AC-2.4, AC-5.1, contract warning-tracker 3.

**T026 Implement `mirrors/round.py:run_round`.**
- Verify: GREEN (T025).
- Covers: FR-1, FR-2.

**T027 Test the `probe-mirrors` CLI.** `tests/unit/test_cli.py`
- Exit `0` when ok, `3` when at risk, `1` on an unexpected exception or tracker
  failure, `2` on bad arguments.
- Stdout has a final `cause=ok|at_risk|check_broken` line.
- At risk, the summary names each in-use mirror with its health and reason.
- Runs with **no CallMeBot variables set**.
- Verify: RED.
- Covers: AC-1.1, AC-1.7, FR-7, FR-19.

**T028 Implement the `probe-mirrors` subcommand.** `src/tweet_relay/cli.py`
- Flags `--data` and `--site-out`. Writes `status.json` into `--site-out`.
- Verify: GREEN (T027).
- Covers: FR-7, AC-1.7.

**T029 Test: nothing third-party is published.** `tests/adversarial/test_no_third_party_text.py`
- Every fixture body, list entry field and error message is seeded with a unique
  marker, e.g. `ZZ-MARKER-<n>`.
- After a full `run_round`, no marker appears in `history.jsonl`, `latest.json`,
  `status.json`, any `FakeTracker` title, body or comment, or the CLI stdout.
- Verify: written to fail first against a deliberately leaky stub, then GREEN.
- Covers: FR-16, E-14.

## Phase 7: Warning tracker (DD-8) [P after T003]

**T030 Test `GitHubIssueTracker`.** `tests/unit/test_tracker.py`, with the GitHub
REST API faked by respx.
- `open` creates an issue with label `mirror-health` and the exact title.
- `open` on an existing open issue makes no request.
- `update` posts one comment.
- `close` comments, then patches `state=closed`.
- 401, 403 and 5xx raise `TrackerUnavailable`.
- **The token never appears** in the exception text or the logs.
- Verify: RED.
- Covers: FR-10, AC-2.3, AC-2.4, §6.

**T031 Implement `GitHubIssueTracker`.** `src/tweet_relay/mirrors/tracker.py`
- Verify: GREEN (T030).
- Covers: FR-10.

## Phase 8: Status page (DD-9) [P after T024 fixes the `status.json` shape]

**T032 Test the static safety checks.** `tests/unit/test_site_static.py`
- `site/app.js` contains none of `innerHTML`, `outerHTML`, `insertAdjacentHTML`,
  `document.write`, `eval(`, `new Function`.
- `site/index.html` has `<meta http-equiv="Content-Security-Policy"` with
  `default-src 'self'` and has no `http(s)://` `src` or `href`.
- Verify: RED (`site/` is missing).
- Covers: FR-17, E-14.

**T033 Implement `site/index.html`, `site/app.js` and `site/style.css`.**
- Banner (AC-3.1). In-use table (AC-3.2). Warnings with issue links (AC-3.4).
- Trend (AC-4.2). Candidates (AC-5.2). Discovery block (AC-5.3).
- **A stale-data banner when `generated_at` is more than 12 h old, judged in the
  browser at view time** (AC-3.3, E-22).
- A responsive layout (AC-3.5).
- Verify: GREEN (T032).
- Covers: the listed ACs.

**T034 Manual check of the page.** quickstart step 4.
- Desktop and a 390 px viewport. The stale banner appears after editing
  `generated_at`.
- Record the result with the date at the bottom of this file.
- Covers: AC-3.3, AC-3.5, E-22.

## Phase 9: Workflow and go-live (DD-5, DD-6, DD-7)

**T035 Write `.github/workflows/mirrors.yml`.**
- `cron: "17 */6 * * *"` plus `workflow_dispatch`.
- `concurrency: mirror-probe`, with no cancel-in-progress (E-19).
- Permissions: `contents: write`, `issues: write`, `pages: write`, `id-token: write`.
- Checks out `mirror-status` into `./data`, or starts it as an orphan branch.
- Runs `probe-mirrors`, then maps the exit code:
  - 0: ping Healthchecks;
  - 3: Healthchecks `/fail`, and the job fails;
  - 1 or 2: no ping, and the job fails.
- Writes a summary stating the cause.
- Force-pushes `./data` as a single commit.
- Uploads `site/` plus `status.json` and deploys Pages, even when at risk (the page
  must show the risk).
- The run-log scrub step mirrors `poll.yml`.
- Verify: `actionlint` is clean, and a dry review against plan DD-6 and DD-7.
- Covers: FR-1, FR-8, FR-9, AC-1.4, AC-1.5, AC-1.6, AC-3.6, E-19.

**T036 Operator setup** (quickstart step 1). Not automatable: it needs your accounts.
- Enable Pages with source "GitHub Actions".
- Create the second Healthchecks check (period 6 h, grace 18 h).
- `gh secret set HEALTHCHECKS_MIRRORS_PING_URL`.
- Verify: `gh api repos/joaq-uinv/twitter_bot/pages` returns 200 with
  `build_type: workflow`, and `gh secret list` shows the secret.
- Covers: FR-8, FR-9 (D-1), FR-19.

**T037 Run the local probe against real mirrors** (quickstart step 3).
- Verify: exit `0` or `3`; one result per roster host; every unhealthy result has a
  reason label; `status.json` contains no response text (spot check plus T029).
- Covers: AC-5.1, FR-3, FR-16.

**T038 Pre-merge review.** `superpowers:requesting-code-review` on the branch.
- Fix every Critical and Important finding.
- Record the outcome as an amendment in plan.md.
- Verify: the review verdict is "Yes", or "With fixes" with the fixes landed; `PT`
  is green.
- Covers: process (CLAUDE.md).

**T039 Live run** (quickstart step 6), after merge.
- `gh workflow run mirrors.yml`.
- The page is reachable without signing in at `https://joaq-uinv.github.io/twitter_bot/`.
- `mirror-status` has exactly 1 commit.
- The Healthchecks check shows a success ping.
- Verify: those 4 observations, recorded with the date.
- Covers: AC-3.6, FR-1, FR-9, FR-18, FR-19.

---

## Traceability

| Requirement | Tasks |
|---|---|
| FR-1 | T010, T025, T026, T035, T039 |
| FR-2 | T010, T025, T026 |
| FR-3 | T001, T004, T005, T009, T010, T037 |
| FR-4 | T011, T012 |
| FR-5 | T002, T003, T004 |
| FR-6 | T002, T003, T009, T012 |
| FR-7 | T013, T014, T027, T028 |
| FR-8 | T035, T036 |
| FR-9 | T035, T036, T039 |
| FR-10 | T015, T016, T025, T030, T031 |
| FR-11 | T006, T007, T008, T010, T017 |
| FR-12 | T017, T018 |
| FR-13 | T019, T020 |
| FR-14 | T019, T020 |
| FR-15 | T019 |
| FR-16 | T002, T017, T029, T037 |
| FR-17 | T032, T033 |
| FR-18 | T021, T022, T039 |
| FR-19 | T027, T036, T039 |
| AC-1.1, AC-1.2, AC-1.3 | T013 (+ T027 for 1.1) |
| AC-1.4, AC-1.5 | T035 |
| AC-1.6 | T013, T014, T035 |
| AC-1.7 | T009, T027, T028 |
| AC-2.1, AC-2.2, AC-2.5 | T015 |
| AC-2.3, AC-2.4 | T015, T025, T030 |
| AC-3.1, AC-3.2, AC-3.4 | T023, T033 |
| AC-3.3, AC-3.5 | T033, T034 |
| AC-3.6 | T035, T039 |
| AC-4.1, AC-4.2 | T023, T033 |
| AC-4.3 | T021 |
| AC-5.1 | T018, T025, T037 |
| AC-5.2, AC-5.3 | T023, T033 |
| AC-5.4 | T019 |
| E-1 to E-4 | T011 |
| E-5 to E-9 | T004 |
| E-10 | T006, T008 |
| E-11 | T017 |
| E-12, E-13 | T019 |
| E-14 | T029, T032 |
| E-15, E-16 | T015 |
| E-17 | T015, T019 |
| E-18 | T013 |
| E-19 | T035 |
| E-20, E-21 | T021 |
| E-22 | T033, T034 |

Every FR-1..19, AC-1.1..5.4 and E-1..22 maps to at least one task.

## Manual verification log

*(T034, T037 and T039 record their results here, with dates.)*

- 2026-10-11, Phase 1: full suite 376 passed. Live mirror tests (`-m live -k pinned_mirror`)
  pass for all 4 `DEFAULT_INSTANCES` through the refactored `fetch_one`.
  **Follow-up found:** `test_real_whatsapp_delivery` always errors at `Config()`,
  because the isolation fixture strips the required `X_PROFILE_URL`. It never skips.
  Nothing was sent, but if the isolation changed, any `-m live` run would send a real
  message. Fix it to skip unless explicitly opted in.
