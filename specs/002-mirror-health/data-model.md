# Data Model: Mirror Health

Every published field is a **validated host**, a member of a **closed set**, a
**time** or a **number** (FR-16). The table for each entity says which.

## `Host`

A bare hostname that has passed `validate_mirror_url()` (plan DD-3).

| Rule | Detail |
|---|---|
| Shape | Comes from `https://<host>` with no userinfo, no port, and no path beyond `/`, query or fragment |
| Charset | Lower-cased. `^[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?(\.[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?)+$`, at most 253 characters. No IP literals. Punycode (`xn--`) labels are allowed as ASCII |
| Address | Checked at **probe time**: every resolved address must satisfy `ip.is_global`, or the result is `refused_address` |

## `Role` (closed set)

`in_use` · `former` (D-2: in use earlier, not in the current config) · `candidate` (discovered)

## `Reason` (closed set, FR-5)

| Value | Raised when |
|---|---|
| `timed_out` | No complete answer within `REQUEST_TIMEOUT_SECONDS` (15 s) |
| `unreachable` | DNS failure, connection refused or reset, TLS failure |
| `refused_answer` | HTTP 4xx or 5xx |
| `sent_elsewhere` | HTTP 3xx (never followed) |
| `too_large` | The declared or streamed body exceeds `MAX_FEED_BYTES` |
| `malformed_content` | Not a well-formed feed, e.g. the HTML "Access Queue" page from R-2 |
| `wrong_account` | Well-formed, but the feed's title does not name `@<handle>` |
| `no_posts` | A valid feed with 0 valid items |
| `stale` | Usable, but `reference − newest_post > 6 h` (FR-4) |
| `refused_address` | The host resolves to a non-global address (FR-11) |

## `Freshness` (closed set)

`fresh` · `stale` · `unknown`. `unknown` is used only when no in-use result was
usable in the round (FR-4).

## `ProbeResult`, one line of `history.jsonl`

| Field | Type | Published? | Invariant |
|---|---|---|---|
| `t` | ISO-8601 UTC, seconds | yes | The round's start time; identical for every result in a round |
| `host` | `Host` | yes | |
| `role` | `Role` | yes | |
| `usable` | bool | yes | |
| `freshness` | `Freshness` \| null | yes | null if and only if `usable` is false |
| `reason` | `Reason` \| null | yes | null if and only if healthy. `stale` if and only if `usable ∧ freshness = stale` |
| `ms` | int ≥ 0 \| null | yes | Elapsed time to a complete answer; null for `refused_address` and `unreachable` |
| `newest` | ISO-8601 UTC \| null | yes | Newest **non-future** post time; null if not usable |

**Derived:** `healthy = usable ∧ freshness ∈ {fresh, unknown}` (D-4).

## `Round`, part of `latest.json`

| Field | Type | Notes |
|---|---|---|
| `t` | ISO-8601 | |
| `reference` | ISO-8601 \| null | The freshness reference (DD-10); null if no in-use result was usable |
| `in_use_healthy` | int | |
| `in_use_total` | int | |
| `at_risk` | bool | `in_use_healthy < 2` (FR-7; E-18 when `in_use_total < 2`) |

## `EpisodeState`, part of `latest.json`

| Field | Type | Notes |
|---|---|---|
| `at_risk_since` | ISO-8601 \| null | Set on the first at-risk round; cleared on the first round that is not at risk. Lets the summary say "at risk for 2 days" |

## `DiscoveryState`, part of `latest.json`

| Field | Type | Notes |
|---|---|---|
| `last_ok` | ISO-8601 \| null | Last time the list was read and parsed |
| `accepted` | int | Entries that passed validation in the last successful read |
| `rejected` | int | Entries dropped in the last successful read |
| `candidates` | list[`Host`] | The last good discovered set, kept on failure (FR-14) |

## `history.jsonl`

- Newline-delimited `ProbeResult`s, appended per round, sorted by `t`.
- Results with `t` older than 90 days are pruned on every round (FR-18).
- **Reading is hostile-tolerant:** a line that does not parse into a valid
  `ProbeResult` is dropped and counted. If more than half the lines are bad, the
  file is treated as corrupt: logged at ERROR, history restarts (E-20), and this
  round is still recorded.

## `status.json`, published with the page and built only from the above

```text
{ generated_at, round: Round, discovery: {last_ok, accepted, rejected},
  mirrors: [ { host, role, healthy, reason, ms, newest_age_s,
               uptime_7d, uptime_30d,          # fractions 0..1, null if no data
               trend: [bool|null] ×≤40 } ],    # newest last; null = not probed
  warnings: [ { host, since } ] }              # open soft warnings (AC-3.4)
```

`uptime = healthy results ÷ all results in the window` (D-4: unknown freshness
counts as healthy).

## Soft-warning rule (FR-10, AC-2.1–2.5)

For each `in_use` host: open a warning if **every** result in the last 24 h is
unhealthy **and** there are at least 2 such results. Close it on the host's first
healthy result. Hosts whose role is not `in_use` never open warnings, and any open
warning for a `former` host is closed (E-17).
