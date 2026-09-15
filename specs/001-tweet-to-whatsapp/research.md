# Research: Tweet → WhatsApp Relay

**Date of probing:** 2026-09-15. All findings below were **observed by making real
requests**, not read from documentation. Published guidance on this topic is heavily
stale — several widely-recommended services in 2026 listicles are dead.

Re-verify before trusting any of this after ~2026-12.

## R-1: Post retrieval — the constraint that shapes everything

FR-14 requires zero operating cost. That removes the obvious answer first.

### Official X API — **excluded**

X replaced tiered pricing with pay-per-use on 2026-02-06. There is no free tier for
new developers; legacy Basic ($200/mo) was force-migrated after 2026-06-01 and legacy
Pro after 2026-09-01.

Rates: $0.005 per post read, $0.010 per user read, $10 minimum prepaid credit.

For this workload the cost would be genuinely small — with incremental polling, one
account at ~19 posts/day is roughly **$1.50/month** — but it is not zero, and the
operator excluded paid services. Recorded because it is the natural fallback if every
free route dies; adopting it is a config + one-adapter change, not a redesign.

### Public mirrors — **selected**

The mirrors every 2026 guide recommends are dead:

| Instance | Probed result |
|---|---|
| `xcancel.com` | HTTP 451 — "XCancel service is suspended" |
| `nitter.net` | Connection refused |
| `nitter.poast.org` | NXDOMAIN |

A community health endpoint, `https://status.d420.de/api/v1/instances`, lists 8 hosts
of which 5 are healthy with feeds enabled. Probed directly against the target account:

| Instance | Country | Result |
|---|---|---|
| `nitter.kareem.one` | 🇸🇬 | **HTTP 200, 19 items** |
| `nitter.meowing.monster` | 🇸🇪 | **HTTP 200, 19 items** |
| `nitter.netbub.com` | 🇺🇸 | **HTTP 200, 19 items** |
| `nitter.jaydenha.uk` | 🇸🇬 | **HTTP 200, 19 items** |
| `shitter.thepixora.com` | 🇨🇦 | HTTP 400, unparseable |

Four independent working mirrors returning **identical content** is what makes the
zero-cost constraint satisfiable. Satisfies FR-9 (failover) without a paid fallback.

Caveats carried into the risk register: these are volunteer-run, unfunded, and the
historical death rate is high. The health endpoint itself returned **HTTP 429** on two
of four attempts, so it must be cached and its failure must be non-fatal.

### Unofficial syndication endpoint — **deferred, unverified**

`syndication.twitter.com/srv/timeline-profile/screen-name/<handle>` is free and
requires no credentials. It returned **HTTP 429 "Rate limit exceeded" on every attempt**
from this network, so it could not be confirmed to return data at all.

Specified as an optional second source **behind a verification gate**: if it cannot be
made to produce data during implementation, it is deleted rather than shipped as a
dead adapter.

## R-2: Feed structure — three findings that drive the design

Captured fixture: `tests/fixtures/santtiagom_.xml`, 28,398 bytes, 19 items, real.

Item fields: `title`, `link`, `guid`, `pubDate`, `description`, `dc:creator`.

### F-1: `guid` is the bare post ID

e.g. `2099612045347848465` — a snowflake integer, not a URL. Usable directly as the
identity key.

### F-2: The feed is **not** ordered by publication time

Observed in the first four items as delivered:

| Position | pubDate |
|---|---|
| 1 | Mon, 14 Sep 2026 21:31:35 GMT |
| 2 | Tue, 15 Sep 2026 06:10:14 GMT |
| 3 | Tue, 15 Sep 2026 11:54:04 GMT |
| 4 | Tue, 15 Sep 2026 03:06:30 GMT |

Any "take everything above the newest one I saw" logic is therefore wrong. → FR-3.

### F-3: Retweets carry the **original** post's ID and author

Item 2's link is `/atrjava/status/2099742569009762599` — a different account — while
appearing in `@santtiagom_`'s feed. Titles carry an `RT by @santtiagom_:` prefix, but
that string is format-dependent; the **author segment of the link** is the reliable
signal.

The consequence is the single most important decision in this design:

> **A retweet's ID is the original post's ID, which may be years old.** Combined with
> F-2, this makes a `since_id` / high-water-mark watermark **incorrect** — it would
> permanently suppress every retweet of an older post. Since the operator wants
> retweets (AC-2.1), that would silently discard most of the traffic.
>
> **Therefore delivery history is a bounded set of seen IDs, tested by membership.**
> → FR-5, AC-2.2, E-2.

This is also why FR-5 is phrased as a prohibition: it is the mistake a reasonable
implementer makes by default.

## R-3: Delivery channel

| Option | Verdict |
|---|---|
| **CallMeBot** | **Selected.** Free, no account, single-recipient by design — which is exactly the requirement, not a limitation. One authenticated GET per message. ~80 messages/day. |
| Meta WhatsApp Cloud API | Rejected: business-initiated messages need pre-approved templates and per-message fees outside the 24h service window, plus a Meta Business account. Violates FR-14 and adds heavy setup. |
| Twilio WhatsApp | Rejected: sandbox requires re-sending a join code every 72h — an unattended relay would silently stop. Production requires payment. |
| `whatsapp-web.js` / Baileys | Rejected: unofficial automation of a personal WhatsApp session carries account-ban risk and requires holding a long-lived authenticated session. Disproportionate risk for a notification relay. |

Expected volume with retweets enabled: ~19/day against a ~80/day ceiling. Comfortable,
but FR-11's per-check cap matters during bursts.

**Behavioural note:** CallMeBot returns **HTML, not JSON**, and signals some errors in
the body of an HTTP 200. Success detection must inspect the body, not just the status
code. → E-19, FR-12.

## R-4: Security posture

The system parses XML from volunteer-run third parties and interpolates the result
into an outbound URL carrying the operator's API key. Both ends are exposed:

| Threat | Consequence | Control |
|---|---|---|
| XXE / entity expansion in feed | File disclosure, resource exhaustion | Hardened parser, never stdlib `ElementTree` (§4) |
| Oversized / compressed-bomb response | Memory exhaustion | Byte cap enforced before parse |
| Mirror serves another account's content | Operator misled about who posted | Channel identity checked against configured handle (FR-7) |
| Post text crafted to alter the outbound request | Parameter injection, key disclosure | Encoder-built URLs, never interpolation (FR-13, E-11) |
| Operator-supplied source address pointing inward | SSRF against local/cloud-metadata services | https-only allowlist, private and link-local ranges blocked (E-20) |
| Key reaching logs or tracebacks | Credential disclosure | Never logged; asserted by test (FR-13) |

Justifies constitution §4 as a standing principle rather than a one-off review item.

## R-5: Runtime

Operator requires everything in containers. A long-running container with an internal
scheduler is preferred over host-scheduled one-shot runs: it keeps scheduling inside
the artefact under test, and makes the relay portable to any Docker host unchanged.

Consequence accepted by the operator: no delivery while the machine is off. Because
delivery history is set-based rather than time-based, posts published during downtime
are delivered on next start rather than lost.
