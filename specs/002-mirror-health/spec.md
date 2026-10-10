# Feature Specification: Mirror Health & Status Page

**Feature:** `002-mirror-health` | **Status:** Clarified | **Created:** 2026-10-10

> Constitution §1: this document describes **behaviour**, not implementation.
> No language, library, protocol or vendor names. Those belong in `plan.md`.
>
> Feature 001 placed "any web interface or dashboard" out of scope. This feature
> lifts that exclusion **for retrieval-source health only**. The relay itself still
> has no interface, and nothing here changes how posts are retrieved or delivered.

## Problem

The relay retrieves posts from third-party sources ("mirrors") that are run by
volunteers and die without notice. Three died in 2026 alone. The relay tries its
configured mirrors in order and stops at the first that works, so **it never learns
whether the backups still work.** The operator discovers a dead backup only at the
moment it is needed, which is too late. By then the relay may already be in a total
outage.

The operator also has no view of how reliable each mirror is over time, and no
systematic way to find replacements when mirrors die.

What this feature must give the operator, in priority order:

1. **Warning before failover breaks**: told while there is still time to act.
2. **Current status at a glance.**
3. **History and trends**: which mirrors are reliable over weeks, not just now.
4. **Replacement candidates**: mirrors not yet in use, ranked by health.

## Definitions

- **In-use mirror**: a mirror in the relay's configured list.
- **Candidate mirror**: a mirror found by discovery (US-5) that is not in use.
- **Probe**: one read-only attempt to retrieve the monitored account's posts from one
  mirror, producing one **result**.
- **Round**: one scheduled pass that probes every in-use and candidate mirror.
- **Usable**: a probe result that meets every condition in FR-3.
- **Fresh**: a usable result whose newest post is recent enough (FR-4).
- **Healthy**: usable, and either fresh or of unknown freshness (FR-4, D-4).

## User Scenarios

### US-1: Warned before the relay runs out of mirrors

**As** the operator **I want** an urgent warning when too few in-use mirrors work
**so that** I can replace mirrors before the relay stops relaying.

- **AC-1.1** Given 4 in-use mirrors of which 1 is healthy, when a round completes,
  then the operator receives an urgent alert naming each in-use mirror and why it is
  or is not healthy.
- **AC-1.2** Given 2 in-use mirrors are healthy, when a round completes, then no
  urgent alert is raised.
- **AC-1.3** Given the previous round was at risk, when a round finds 2 or more
  in-use mirrors healthy, then the operator is told **once** that the risk has
  cleared.
- **AC-1.6** Given the relay stays at risk across several rounds, then the urgent
  alert is sent **once per at-risk episode** on each channel, not once per round
  (D-3). While the episode lasts, the status page keeps showing the risk.
- **AC-1.4** The urgent alert reaches the operator through a channel that does not
  depend on the relay's message delivery working.
- **AC-1.5** Given rounds stop happening altogether, then the operator is alerted.
  Silence from the health check must never be mistaken for health (constitution §7).

### US-2: Soft warning for a persistently unhealthy mirror

**As** the operator **I want** to be told when one in-use mirror has been unhealthy
for a day **so that** I can replace it before it matters, without being alerted for
every brief blip.

- **AC-2.1** Given an in-use mirror was unhealthy in **every** round of the last 24
  hours, and there were at least 2 such rounds, then a warning is raised for that
  mirror.
- **AC-2.2** Given an in-use mirror was unhealthy for 23 hours but healthy in one
  round within the last 24, then no warning is raised.
- **AC-2.3** Given a warning is already open for a mirror, when it remains
  unhealthy, then no second warning is raised for it. The open warning is updated
  with the latest reason.
- **AC-2.4** Given a warning is open for a mirror, when a round finds it healthy,
  then the warning is resolved automatically.
- **AC-2.5** Candidate mirrors never raise warnings.

### US-3: Current status at a glance

**As** the operator **I want** a status page **so that** I can see at a glance
whether the relay's sources are healthy.

- **AC-3.1** The page opens with a single verdict: how many in-use mirrors are
  healthy out of how many, and whether the relay is **at risk** (fewer than 2
  healthy).
- **AC-3.2** For each in-use mirror the page shows its health, the reason when not
  healthy, its response time, and how old its newest post is.
- **AC-3.3** Given the most recent round is more than 12 hours old, then the page
  says prominently that its data is stale and the health check may have stopped.
  This is judged when the page is viewed, not when it was last updated.
- **AC-3.4** The page lists open warnings (US-2) with a way to reach each one.
- **AC-3.5** The page is readable on a phone.
- **AC-3.6** The page is publicly viewable without signing in.

### US-4: History and trends

**As** the operator **I want** to see each mirror's reliability over time **so that**
I prefer mirrors that stay up, not mirrors that happen to be up right now.

- **AC-4.1** For each mirror the page shows uptime over the last 7 days and the last
  30 days, as the share of results that were healthy. A usable result of unknown
  freshness counts as healthy (D-4).
- **AC-4.2** For each mirror the page shows its recent results as a trend that makes
  flapping visible.
- **AC-4.3** Results older than 90 days are discarded.

### US-5: Replacement candidates

**As** the operator **I want** to see mirrors I am not using, ranked by health **so
that** I know what to switch to when an in-use mirror dies.

- **AC-5.1** Given a public community-maintained list of mirrors, when a round runs,
  then the mirrors it names, apart from those already in use, are probed as
  candidates.
- **AC-5.2** The page lists candidates healthy first, then by 30-day uptime.
- **AC-5.3** The page shows when the community list was last read successfully, and
  how many of its entries were accepted and how many rejected.
- **AC-5.4** Given a candidate is healthy for 30 days, then it is still **never used
  for relaying** unless the operator adds it to the configuration. Discovery
  suggests; it never acts.

## Functional Requirements

### Probing

- **FR-1** The system MUST probe every in-use mirror and every accepted candidate
  once per round, on a schedule, independently of the relay's own checks.
- **FR-2** Probing MUST be read-only. It MUST NOT send any message to the operator's
  delivery channel, and MUST NOT change the relay's delivery history.
- **FR-3** A result MUST be **usable** only if the mirror answered within the same
  bounded wait the relay uses, answered directly rather than sending the request
  elsewhere, stayed within the relay's size limit, returned well-formed content
  belonging to the monitored account (as 001 FR-7 defines it), and contained at least
  one post. Otherwise the result MUST carry exactly one reason from a fixed set (FR-5).
- **FR-4** A usable result MUST be **fresh** only if its newest post is no more than
  6 hours older than the **reference time**. The reference time is the newest post
  time among usable **in-use** results in the same round. Post times in the future
  MUST be ignored, and candidate results MUST NOT affect the reference time. If no
  in-use result is usable, freshness MUST be recorded as **unknown** rather than
  guessed.
- **FR-5** The fixed set of reasons MUST distinguish at least: timed out, unreachable,
  refused answer, sent elsewhere, too large, malformed content, wrong account, no
  posts, stale, and refused address (FR-11). No reason may contain free text.
- **FR-6** Each result MUST record the mirror, the time, whether it is usable, its
  freshness, its reason when not healthy, its response time, and the time of its
  newest post.

### Alerting

- **FR-7** The system MUST raise the urgent alert (US-1) in the first round in which
  fewer than 2 in-use mirrors are healthy. It MUST NOT wait for a second round.
- **FR-8** The urgent alert MUST reach the operator through at least two channels,
  neither of which depends on the relay's message delivery working.
- **FR-9** The system MUST alert the operator when no round has completed within
  **24 hours**, which is about four missed rounds. A late warning is preferred to a
  false alarm (D-1).
- **FR-10** Soft warnings (US-2) MUST be durable, at most one open per mirror, and
  visible to the operator outside the status page.

### Discovery (all of it is hostile input, constitution §4)

- **FR-11** The system MUST treat the community list and every mirror it names as
  untrusted. Each entry MUST be accepted only if it is a bare address of a host on
  an encrypted connection, with no path, credentials, query or unusual port, and
  only permitted host-name characters. The same rules MUST apply as for the relay's
  configured mirrors (001 E-20). At probe time, a host that resolves to an address
  internal to the network the check runs on, or reserved for infrastructure, MUST be
  refused and recorded with the reason **refused address**.
- **FR-12** Malformed entries MUST be dropped one at a time. A bad entry MUST NOT
  cause the rest of the list to be rejected.
- **FR-13** Candidates MUST be de-duplicated, MUST exclude in-use mirrors, and MUST
  be capped at 25. Formerly in-use mirrors (E-17) take priority over discovered
  entries within that cap.
- **FR-14** If the community list is unavailable or unreadable, the system MUST keep
  the last accepted candidate set, MUST show on the page since when discovery has
  been stale, and MUST NOT treat this as a failed round.
- **FR-15** Discovered mirrors MUST NEVER be used for relaying automatically (AC-5.4).

### Publication

- **FR-16** Everything the system publishes (the status page, its data, and alert
  and warning text) MUST consist only of validated host names, reasons from the
  fixed set (FR-5), times and numbers. **No text taken from any mirror's response or
  from the community list may be published.**
- **FR-17** The status page MUST display its data as plain text. Nothing in the data
  may be interpreted as page structure or behaviour, even if it got past FR-16.
- **FR-18** Results older than 90 days MUST be discarded on every round.
- **FR-19** The feature MUST cost nothing to operate (as 001 FR-14), and MUST NOT
  expose the operator's credentials (as 001 FR-13). Probing needs no credentials.

## Edge Cases

| # | Situation | Required behaviour |
|---|-----------|--------------------|
| E-1 | A mirror answers quickly but serves a feed days old | Usable but **stale**: not healthy (FR-4) |
| E-2 | A candidate's posts are dated in the future, which would make honest mirrors look stale | Future times ignored; candidates never move the reference (FR-4) |
| E-3 | No in-use mirror is usable | Freshness **unknown** for all; urgent alert (FR-7); usable candidates count as healthy (D-4), so the page shows exactly which ones to switch to |
| E-4 | The monitored account has not posted for a week | All honest mirrors share the same newest post, so all are fresh; the account being quiet is not a mirror failure |
| E-5 | A mirror answers by sending the request to another address | Not usable, reason "sent elsewhere"; the other address is never contacted |
| E-6 | A mirror returns an error page, a rate-limit notice, or an empty feed with a success status | Not usable (malformed content / no posts) |
| E-7 | A mirror returns content for a different account | Not usable, reason "wrong account" |
| E-8 | A mirror returns enormous or hostile content | Refused per 001 E-9 and E-10; reason "too large" or "malformed content" |
| E-9 | A mirror hangs | Abandoned after the relay's bounded wait; reason "timed out"; the round continues |
| E-10 | The community list names a host that resolves to an internal or infrastructure address, including only at probe time | Refused, reason "refused address"; never contacted (FR-11) |
| E-11 | The community list is enormous, malformed, has duplicates, or names more than 25 new mirrors | Size-bounded; bad entries dropped individually; de-duplicated; capped at 25 (FR-12, FR-13) |
| E-12 | The community list includes in-use mirrors | They are probed once, as in-use, never also as candidates |
| E-13 | The community list disappears for a week | Last accepted candidates kept; discovery staleness shown; rounds not failed (FR-14) |
| E-14 | A response contains text designed to be shown on the page or in an alert | Never published (FR-16); displayed as plain text even if it were (FR-17) |
| E-15 | A mirror flaps healthy and unhealthy every round | No soft warning (AC-2.2); the trend shows the flapping (AC-4.2) |
| E-16 | A mirror is unhealthy for 3 days | One warning, raised once, updated, not repeated (AC-2.3) |
| E-17 | The operator removes a mirror from the configuration while a warning is open for it | Its open warning is resolved, its history is kept, and it becomes a **candidate** carrying that history, probed whether or not the community list names it. It takes priority over discovered entries within the cap of 25. If added back to the configuration, it is in use again with its full history (D-2) |
| E-18 | Fewer than 2 mirrors are configured at all | Permanently at risk by definition: the verdict says so and the urgent alert fires (FR-7) |
| E-19 | Two rounds overlap | Results are not lost or duplicated, and history is not corrupted |
| E-20 | The stored history is missing or corrupt | The round still runs and records results; history restarts; this is logged loudly, not silently |
| E-21 | A round fails partway, e.g. the process is killed | No partial history is published as if complete; the next round recovers |
| E-22 | The page is viewed long after rounds stopped | The stale-data warning shows (AC-3.3), because it is judged at view time |

## Out of Scope

- Using discovered mirrors automatically, or reordering in-use mirrors automatically.
- Changing how the relay retrieves or delivers posts. Only shared parts are reused.
- Monitoring anything other than retrieval mirrors (delivery-channel health,
  operator hardware).
- Probing more often than about every 6 hours. Mirrors are volunteer-run, and politeness
  is a requirement.
- Accounts, sign-in, or any operator controls on the page. It is read-only.
- History beyond 90 days.

## Open Questions

None. All resolved on 2026-10-10. See Decisions.

## Decisions

Resolved 2026-10-10 via `/speckit-clarify`. Recorded here so the reasoning survives
context loss.

| # | Question | Decision | Reasoning |
|---|----------|----------|-----------|
| D-1 | How long without a completed round before the "health check stopped" alert (FR-9) | **24 hours** | The operator prefers late warnings to false alarms. The scheduler already starts runs 4–7 hours apart, not every 6, so a 12-hour limit would fire on ordinary lateness. 24 hours is about four missed rounds: certainly broken, and still long before discovery staleness matters. |
| D-2 | What happens to a mirror removed from the configuration (E-17) | It **comes back as a candidate**, keeping its history; its open warning is resolved | The operator vetted it once, so it is a better replacement than an unknown discovered host, which is why it ranks ahead of them within the cap. Keeping its history means that adding it back to the configuration starts from real evidence rather than from zero. |
| D-3 | Urgent alert per round, or per at-risk episode (Q-3) | **Once per episode**, plus one all-clear | Matches how 001 FR-10 handles outages. An alert repeated every round trains the operator to ignore it. The page shows the ongoing risk throughout, so "once" never means "forgotten". This applies to **every** urgent channel (see the note below). |
| D-4 | Does unknown freshness count as healthy (Q-4) | **Yes**, folded into the definition of "healthy" | Unknown happens only when no in-use mirror is usable. Then a usable candidate is exactly what the operator needs to find, and counting it unhealthy would hide replacements during the very outage they are needed for. It cannot weaken the urgent alert: in-use mirrors are unusable whenever freshness is unknown, so they are never healthy. |

**Note for `plan.md` (from D-3):** a channel that fires on every failed scheduled run
cannot carry the urgent alert. While at risk, each round would count as a fresh
alert. The plan must use only channels that alert on a change of state, not on every
run. A failed run stays reserved for "the health check itself broke".

## Success

- When an in-use mirror dies, the operator knows within one round and before the
  relay runs out of mirrors, not when the relay stops relaying.
- At any moment, the operator can answer "is the relay at risk?" from one glance at
  one page.
- When a mirror needs replacing, the page already lists healthy candidates to switch
  to.
- No third-party text ever appears on the page or in any alert.
