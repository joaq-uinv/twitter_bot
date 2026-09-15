# Feature Specification: Tweet → WhatsApp Relay

**Feature:** `001-tweet-to-whatsapp` | **Status:** Clarified | **Created:** 2026-09-15

> Constitution §1: this document describes **behaviour**, not implementation.
> X and WhatsApp appear as *required endpoints* (the operator named them), never as
> a chosen mechanism. How posts are retrieved and how messages are delivered are
> `plan.md` decisions.

## Problem

The operator wants to know promptly when a specific X account posts, without opening
X or granting a third party access to their accounts. Checking manually is
unreliable and X's own notifications require using the app. The operator already
reads WhatsApp continuously, so that is where the signal belongs.

A secondary requirement shapes everything: **the system must cost nothing to run.**
This rules out the account owner paying for post retrieval, which in turn means
retrieval depends on sources the operator does not control and cannot repair.

## User Scenarios

### US-1: Receive new posts

**As** the operator **I want** each new post from the monitored account delivered to
my WhatsApp **so that** I learn about it without checking X.

- **AC-1.1** Given the monitored account publishes a post, when the next check runs,
  then the operator receives one message containing the post's author, its text, and
  a link that opens the post on X.
- **AC-1.2** Given a post has already been delivered, when any later check runs, then
  it is never delivered again — including after the system restarts.
- **AC-1.3** Given several undelivered posts exist, when a check runs, then they are
  delivered **oldest first**, so the operator reads them in the order written.

### US-2: Retweets count as activity

**As** the operator **I want** retweets delivered too **so that** I see everything the
account amplifies, not just what it authors.

- **AC-2.1** Given the account retweets a post, when the next check runs, then the
  operator receives a message identifying it as a retweet and naming the original author.
- **AC-2.2** Given the account retweets a post **originally published years earlier**,
  when the next check runs, then it is still delivered. Age of the original must not
  suppress it.
- **AC-2.3** Given the account replies to someone, when a check runs, then no message
  is sent (replies are excluded by default).
- **AC-2.4** Given the account quote-posts — adding its own commentary above another
  post — when the next check runs, then the operator receives a message containing that
  commentary, identified as a quote. Quotes are delivered by default and can be
  disabled independently of originals and retweets. (D-1)

### US-3: Quiet first run

**As** the operator **I want** enabling the relay not to flood me with history **so
that** turning it on is safe.

- **AC-3.1** Given no prior delivery history and a monitored account with existing
  posts, when the first check runs, then those existing posts are recorded as
  already-delivered and **none of them is sent**.
- **AC-3.2** Given the conditions of AC-3.1, when the first check completes, then the
  operator receives exactly **one** confirmation message indicating the relay is live.
- **AC-3.3** Given the relay has already run for the monitored account, when it
  restarts for any reason, then **no** confirmation message is sent. The confirmation
  is once per monitored account, not once per start. (D-2)

### US-4: Know when it breaks

**As** the operator **I want** to be told when the relay cannot retrieve posts **so
that** silence always means "nothing was posted" and never "it broke".

- **AC-4.1** Given every retrieval source is unavailable, when a check runs, then the
  operator receives exactly one notification naming the failure.
- **AC-4.2** Given the conditions of AC-4.1, when sources recover, then only posts
  published during the outage are delivered — none are lost and none are duplicated.
- **AC-4.3** Given sources remain unavailable across consecutive checks, when those
  checks run, then the operator is **not** notified repeatedly for the same outage.

### US-5: Retarget without code changes

**As** the operator **I want** to change which account is monitored via configuration
**so that** I can point the relay elsewhere without editing or rebuilding code.

- **AC-5.1** Given the configured account is changed, when the system restarts, then
  it monitors the new account and applies US-3's quiet-first-run behaviour to it.
- **AC-5.2** Given an account identifier that is malformed, when the system starts,
  then it refuses to start and states what is wrong.

## Functional Requirements

- **FR-1** The system MUST check the monitored account for new posts on a recurring
  interval, configurable by the operator.
- **FR-2** The system MUST deliver each new post exactly once, across restarts.
- **FR-3** The system MUST order deliveries by publication time, oldest first, and
  MUST NOT rely on the order in which the source presents posts.
- **FR-4** The system MUST identify each post as an original, a retweet, a reply, or a
  quote, and MUST deliver each category according to operator configuration, each
  category being independently configurable.
- **FR-5** The system MUST NOT use post age or identifier ordering to decide whether a
  post is new. (A retweet of an old post is new activity — see AC-2.2.)
- **FR-6** The system MUST record delivery history durably, surviving restarts.
- **FR-7** The system MUST verify that retrieved content belongs to the monitored
  account, and MUST discard content that does not.
- **FR-8** The system MUST treat all retrieved content as untrusted: malformed,
  oversized, hostile or incomplete content MUST be discarded without crashing the
  check, corrupting delivery history, or altering an outgoing message's structure.
- **FR-9** The system MUST continue operating when an individual retrieval source
  fails, by trying other sources.
- **FR-10** The system MUST notify the operator when all retrieval sources fail, once
  per outage rather than once per check.
- **FR-11** The system MUST limit how many messages it sends per check, and MUST
  indicate when messages were withheld by that limit. Withheld posts MUST remain
  undelivered and MUST be delivered on subsequent checks, oldest first, until the
  backlog clears. The limit rate-limits delivery; it never discards a post. (D-3)
- **FR-12** The system MUST NOT mark a post as delivered unless delivery succeeded.
- **FR-13** The system MUST NOT expose operator credentials in logs, error messages,
  or any outbound content.
- **FR-14** The system MUST cost nothing to operate beyond hardware the operator
  already owns.

## Edge Cases

| # | Situation | Required behaviour |
|---|-----------|--------------------|
| E-1 | Source lists posts out of publication order | Reorder by publication time before delivering (FR-3) |
| E-2 | Retweet of a years-old post | Deliver it; age is irrelevant (AC-2.2, FR-5) |
| E-3 | Same post appears twice in one response | Deliver once |
| E-4 | Post appears, then is deleted before the next check | Already-delivered: no action. Not yet delivered: silently skipped, no error |
| E-5 | Delivery fails midway through a batch | Successful ones stay delivered; failed ones retry next check; no duplicates |
| E-6 | Process is killed mid-check | No post is delivered twice on restart |
| E-7 | Source returns content for a **different** account | Discard entirely; treat as source failure (FR-7) |
| E-8 | Content is malformed, truncated, or not the expected format | Discard, log, continue with other sources (FR-8) |
| E-9 | Content is enormous (memory-exhaustion attempt) | Refuse before processing (FR-8) |
| E-10 | Content embeds constructs designed to subvert the reader | Neutralised; never interpreted (FR-8) |
| E-11 | Post text contains characters meaningful to the delivery channel | Delivered as literal text; message structure unchanged (FR-8) |
| E-12 | Post carries a publication time in the future or unparseable | Discard the timestamp's authority; do not let it poison ordering |
| E-13 | Post text exceeds the delivery channel's message limit | Truncate with a clear indicator; the link always survives |
| E-14 | Account posts a large burst at once | Deliver up to the per-check limit oldest-first, indicate how many were withheld, and drain the remainder on following checks (FR-11, D-3) |
| E-15 | Monitored account is renamed, deleted, or made private | Treated as source failure; operator notified once (FR-10) |
| E-16 | Delivery history file is corrupt or truncated | Recover without crashing; log loudly; do not re-deliver history |
| E-17 | Two checks run concurrently against one history | No post delivered twice; no history entries lost |
| E-18 | A source is reachable but hangs indefinitely | Abandoned after a bounded wait; next source tried |
| E-19 | Delivery channel reports success but the body indicates an error | Treated as failure; post not marked delivered (FR-12) |
| E-20 | Operator configures a source address pointing at internal infrastructure | Refused (FR-8) |

## Out of Scope

- Monitoring more than one account per running instance.
- Delivering media, polls, or threads as anything richer than text plus a link.
- Two-way interaction — the operator cannot reply, search, or command the relay.
- Any web interface or dashboard.
- Guaranteed delivery while the operator's hardware is powered off. Posts published
  during downtime are delivered at next start, not lost.
- Historical backfill beyond what the source currently exposes.

## Decisions

Resolved 2026-09-15 via `/speckit-clarify`. Recorded here so the reasoning survives
context loss.

| # | Question | Decision | Reasoning |
|---|----------|----------|-----------|
| D-1 | How to treat quote-posts | Own category, delivered by default, independently disableable | The commentary is the account's own writing, so it is genuine activity — but grouping it with originals would make it impossible to silence without also silencing authored posts |
| D-2 | Frequency of the liveness confirmation | Once per monitored account, on first run only | Restarts are expected and frequent under an always-restart supervisor; a per-start message would spam hardest exactly when the system is unhealthy and restart-looping |
| D-3 | Fate of posts withheld by the per-check limit | Remain undelivered; drain on subsequent checks | Makes the limit a rate-limiter rather than a dropper, preserving FR-2's exactly-once guarantee. A 30-post burst clears over 3 checks instead of being lost |

## Success

- A post published by the monitored account reaches the operator's WhatsApp within
  one check interval.
- Over a week of operation: zero duplicate deliveries, zero missed posts while the
  hardware was running, and zero recurring cost.
- When the relay breaks, the operator finds out from the relay rather than by noticing
  its silence.
