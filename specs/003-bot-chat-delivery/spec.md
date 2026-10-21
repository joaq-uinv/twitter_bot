# Feature Specification: Bot Chat Delivery & Commands

**Feature:** `003-bot-chat-delivery` | **Status:** Draft | **Created:** 2026-10-21

> Constitution §1: this document describes **behaviour**, not implementation.
> No language, library, protocol or vendor names. Those belong in `plan.md`. The
> messaging app the operator chose is named in `plan.md`, not here.
>
> This feature changes feature 001 in two ways:
> - It **replaces** 001's delivery channel. Every 001 requirement that talks about
>   "delivery" now means delivery into the new chat, and the old channel is removed.
> - It **lifts** 001's "two-way interaction" exclusion, for the four commands below
>   only.
>
> Everything else in 001 (what counts as a new post, exactly-once delivery,
> ordering, the per-check limit, the outage notice, hostile input) is unchanged.

## Problem

The relay's only delivery channel stopped delivering on 2026-10-20: the free
service behind it ran out of messages and now asks the operator to subscribe. Since
then every check has failed, and posts are piling up undelivered. The relay
classified this correctly as a failure and kept the posts, but the operator gets
nothing until the channel is replaced.

The operator wants posts to arrive in a **private chat between themselves and a
bot**, in a messaging app they already use, at no cost. Moving the channel is also
a chance to let the operator steer the relay without editing configuration: check
its health, and pause and resume deliveries.

One constraint shapes the command design: the relay is **not always running**. It
wakes for one check, then stops. A command can only be read, and answered, at the
next check. Checks are nominally a few minutes apart, but the scheduler has
delivered them hours late. The design accepts that delay instead of adding an
always-on service.

## User Scenarios

### US-1: Receive posts in the bot chat
**As** the operator **I want** each new post delivered into my private chat with
the bot **so that** I keep following the account now that the old channel is gone.

**Acceptance criteria**
- **AC-1.1** Given a new post by the monitored account, when a check runs, then
  exactly one message for it appears in the operator's bot chat, with the same
  content as before (kind marker, text, link), and no message appears anywhere else.
- **AC-1.2** Given the delivered message contains the post's link, when the
  operator views it, then a preview card for the post is shown with the message.
  *(See Open Questions: C-1.)*
- **AC-1.3** Given the chat refuses a message, when the check runs, then the post
  is not recorded as delivered and the run reports a failure (001 FR-12, A-8).
- **AC-1.4** Given the old channel's credentials are no longer configured, when a
  check runs, then the relay runs normally; nothing requires or mentions them.

### US-2: Switch over without losing or repeating posts
**As** the operator **I want** the switch to pick up exactly where the old channel
stopped **so that** I neither miss the posts stuck since the old channel failed nor
get old posts again.

**Acceptance criteria**
- **AC-2.1** Given posts already delivered through the old channel, when the first
  check on the new channel runs, then none of them is delivered again.
- **AC-2.2** Given posts that were stuck undelivered when the old channel failed and
  are still in the account's recent posts, when the first check on the new channel
  runs, then they are delivered, oldest first, within the per-check limit.
- **AC-2.3** Given the first check on the new channel, when it runs, then the
  operator's chat shows that the relay is now delivering there. *(See C-2.)*

### US-3: Ask the relay how it is doing
**As** the operator **I want** to send `/status` and get a summary **so that** I can
tell whether the relay is running without opening anything else.

**Acceptance criteria**
- **AC-3.1** Given the operator sent `/status`, when the next check runs, then the
  bot replies with:
  - the time of the latest check;
  - how many posts that check delivered;
  - how many posts are waiting to be delivered;
  - whether deliveries are paused, and since when;
  - how many in-use sources were healthy in the latest source health check (002),
    and the address of the public status page.
- **AC-3.2** Given no source health check result is available, when `/status` is
  answered, then the source health line says so instead of showing a number.
- **AC-3.3** Given all sources fail during the check that reads `/status`, when the
  check runs, then the reply is still sent and states that sources are unavailable.

### US-4: Pause and resume deliveries
**As** the operator **I want** to pause and later resume deliveries **so that** I can
stop posts for a while, for example during a meeting or a trip, without losing them.

**Acceptance criteria**
- **AC-4.1** Given deliveries are running, when the operator sends `/pause` and the
  next check runs, then the bot confirms the pause and tells the operator to send
  `/resume` to restart, and that check delivers no posts.
- **AC-4.2** Given deliveries are paused, when later checks run, then no posts are
  delivered and none is recorded as delivered, until the operator resumes. The
  pause does not expire on its own.
- **AC-4.3** Given deliveries are paused and all sources fail, when a check runs,
  then the outage notice is still delivered (a pause never hides a broken relay).
- **AC-4.4** Given deliveries are paused, when the operator sends `/resume` and the
  next check runs, then the bot confirms, states how many posts are waiting, and
  that same check delivers them, oldest first, within the per-check limit (001
  FR-11). Any beyond the limit drain on following checks.
- **AC-4.5** Given the pause began before the oldest post the sources still list,
  when the operator resumes, then the confirmation warns that posts published early
  in the pause may no longer be retrievable.
- **AC-4.6** Given deliveries are paused, when the operator sends `/pause` again,
  then the bot replies that deliveries are already paused, since when. Likewise
  `/resume` while running replies that deliveries are already running.
- **AC-4.7** Given a check is paused, when it finishes, then the run's own report
  (the operator-facing summary of each check) states that deliveries are paused,
  so a check that sent nothing is not mistaken for a quiet account.

### US-5: Find out what the bot understands
**As** the operator **I want** `/help` **so that** I can recall the commands.

**Acceptance criteria**
- **AC-5.1** Given the operator sent `/help`, when the next check runs, then the bot
  replies with the four commands, one line each, and a note that replies arrive at
  the next check, which can take minutes or hours.
- **AC-5.2** Given the operator sent an unknown command or plain text, when the next
  check runs, then the bot replies once, briefly, pointing to `/help`.

### US-6: Nobody else can use the bot
**As** the operator **I want** the bot to obey only me **so that** a stranger who
finds it cannot pause my relay, read its status, or fill my logs.

**Acceptance criteria**
- **AC-6.1** Given anyone other than the operator writes to the bot, when a check
  runs, then nothing happens: no reply, no change of state, and nothing about the
  message (its sender, its text) appears in any log, report or published page.
- **AC-6.2** Given the operator's messages and a stranger's arrive between the same
  two checks, when the check runs, then the operator's commands are handled as if
  the stranger's did not exist.

## Functional Requirements

**Delivery**
- **FR-1** The system MUST deliver posts, the outage notice, the per-check-limit
  notice and command replies into one private chat between the operator and the
  bot, and nowhere else.
- **FR-2** The system MUST keep 001's message content for posts (kind marker, text,
  link) and MUST present the post's link so that a preview card is shown. *(C-1.)*
- **FR-3** The system MUST remove the old delivery channel entirely: its sending
  code, its configuration, its credentials, and the scheduled-run step that alerted
  through it. It MUST NOT need any of them to run.
- **FR-4** The system MUST keep its record of already-delivered posts across the
  switch, so no post is delivered twice and no stuck post is skipped.
- **FR-5** The system MUST treat a message the chat accepted as delivered only when
  the chat confirms it, never on the absence of an error (001 FR-12, E-19).

**Commands**
- **FR-6** The system MUST read the operator's messages to the bot once per check,
  before delivering posts, and handle each one in the order it was sent.
- **FR-7** The system MUST act only on messages from the operator's own chat. Every
  other message MUST be discarded without a reply, a state change, or a log record
  of its content or sender.
- **FR-8** The system MUST recognise exactly `/status`, `/pause`, `/resume` and
  `/help`, and MUST answer anything else from the operator with one short pointer to
  `/help`.
- **FR-9** The system MUST handle each operator message at most once, even if a
  check fails part way or two checks overlap.
- **FR-10** The system MUST bound the work per check: the number of messages read
  and replies sent per check is capped, and a flood of messages cannot delay post
  delivery indefinitely or exceed the chat's sending limits.
- **FR-11** The system MUST treat every byte of an incoming message as hostile
  input: size-capped, never interpreted, and never echoed back verbatim into a
  reply, a log line, or the run's report.

**Pause**
- **FR-12** The system MUST persist the paused state, and when it began, across
  checks, with the same durability as the delivered-posts record.
- **FR-13** While paused the system MUST NOT deliver posts or the per-check-limit
  notice, and MUST still deliver the outage notice and command replies.
- **FR-14** While paused the system MUST NOT record any post as delivered, so that
  posts published during a pause are delivered on resume if the sources still list
  them.
- **FR-15** The system MUST NOT store post content during a pause. Posts no longer
  listed by the sources when the operator resumes are not delivered (short pauses
  only; see Out of Scope).

**Secrets and alarms**
- **FR-16** The bot's credentials and the operator's chat identity MUST be treated
  as secrets: never logged, never in an error message, never in the run's report or
  any published page, and covered by the adversarial tests (001 FR-13, §6).
- **FR-17** The two alarms that do not depend on the delivery channel (the
  scheduler's failure email and the external dead-man's switch) MUST keep working
  unchanged, including while paused. A paused check counts as a healthy check.
- **FR-18** The system MUST continue to cost nothing to operate (001 FR-14).

## Edge Cases

| # | Situation | Required behaviour |
|---|-----------|--------------------|
| E-1 | Operator sends `/pause` then `/resume` between two checks | Both handled in order; the check ends unpaused and delivers normally; two replies |
| E-2 | Operator sends `/resume` then `/pause` between two checks | Ends paused; no posts delivered in that check; two replies |
| E-3 | The same command sent five times between checks | Each handled; replies are bounded by FR-10. Repeated `/pause` gives "already paused" (AC-4.6) |
| E-4 | A stranger finds the bot and sends `/pause` | Ignored entirely (FR-7, AC-6.1) |
| E-5 | A message claims to come from the operator in its text, or is forwarded from the operator by someone else | Identity comes only from the chat it arrived in, never from content. Ignored |
| E-6 | Operator message is huge, binary, or contains characters meaningful to the chat's formatting | Size-capped; treated as unknown text (AC-5.2); never echoed |
| E-7 | Command with extra words or different case (`/Pause now`, `/STATUS`) | [NEEDS CLARIFICATION: C-3 — accept leading command case-insensitively and ignore trailing words, or treat as unknown?] |
| E-8 | Command arrives while the check that reads it fails before replying | Not lost and not double-handled: handled by a later check exactly once (FR-9) |
| E-9 | Commands older than the chat's own retention, because checks were delayed for a long time | May be lost without trace. Accepted limitation; `/help` warns that replies wait for the next check |
| E-10 | Two checks run at once (manual run plus scheduled run) | Each command handled once; the paused state is not corrupted (001 E-17) |
| E-11 | Chat refuses a command reply but accepts posts, or the reverse | Same handling as any refused message: not counted as sent; run reports failure |
| E-12 | Operator blocks the bot or deletes the chat | Every delivery fails; run fails loudly; the independent alarms fire (FR-17) |
| E-13 | Bot credentials revoked or wrong | Every delivery fails; the failure reason in the run says the credentials were rejected, without revealing them |
| E-14 | Operator chat identity misconfigured (points at someone else's chat) | [NEEDS CLARIFICATION: C-4 — is there anything the relay can check, or is this the operator's setup responsibility, verified once at setup?] |
| E-15 | Paused for longer than the sources' recent window | On resume, the confirmation carries the warning in AC-4.5; posts no longer listed are not delivered |
| E-16 | Post link cannot produce a preview card (deleted post, blocked preview) | Message still delivered with its text and link; a missing card is never a delivery failure |
| E-17 | `/status` when no check has delivered anything yet, or the record is fresh | Reply states "none yet" instead of a time or count |
| E-18 | Paused, then the first check on the new channel runs | The switch announcement (AC-2.3) still appears; stuck posts wait for `/resume` |
| E-19 | Stranger's message contains a secret-looking string or a fake log line | Never logged (FR-7), so cannot reach any report |

## Out of Scope

- Long pauses: storing posts during a pause so none age out (FR-15).
- Instant replies. Commands are answered at the next check; an always-on listener is
  not built.
- Commands beyond the four: resending recent posts, changing the monitored account,
  quiet hours, triggering a check on demand.
- Group chats, channels, or more than one recipient.
- Delivering media files. Posts stay text plus a link; the preview card is the
  chat's own rendering of that link.
- Keeping the old channel as a backup.

## Open Questions

- **C-1** [NEEDS CLARIFICATION: The account's own post addresses often fail to
  produce a preview card in chat apps, because the post's site blocks preview
  services. A card can be obtained by linking through an intermediary address that
  shows the card and forwards readers to the post. Is it acceptable for the
  delivered link to be such an intermediary address (a third party then sees which
  posts the operator opens), or must the link stay the post's own address, accepting
  that the card will sometimes be missing?]
- **C-2** [NEEDS CLARIFICATION: Should the first check on the new channel send a one-time
  "now delivering here" message, or should the first message the operator sees be
  the first post?]
- **C-3** See E-7.
- **C-4** See E-14.

## Success

- Within one check of the switch, the posts stuck since 2026-10-20 that the sources
  still list arrive in the bot chat, and none of the posts delivered before then
  arrives again.
- Over a week: every new post arrives in the bot chat, zero duplicates, zero cost.
- `/pause` stops deliveries and `/resume` brings the waiting posts, each answered at
  the next check.
- A stranger messaging the bot has no observable effect.
- When delivery breaks, the operator still learns about it from the scheduler's
  failure email and the dead-man's switch, without the chat.
