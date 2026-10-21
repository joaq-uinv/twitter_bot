"""One check: fetch, filter, order, cap, deliver, persist.

The ordering of steps is load-bearing:
  * sort before capping, so a backlog drains oldest-first (D-3);
  * persist after each successful send, so a crash or partial failure never
    re-delivers or loses a post (E-5, E-6, FR-12).

Spec 003 adds, in this order: the one-time switch announcement, then the operator's
commands (after the fetch, because /resume reports what is waiting; before delivery,
because /pause must stop this check), then the pause gate before delivery.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from .commands import (Command, parse, render_help, render_pause, render_resume,
                       render_status, render_unknown)
from .formatter import (render, render_announcement, render_bootstrap, render_minimal,
                        render_outage, render_withheld)
from .mirrors.history import latest_from_json
from .models import (DeliveryFailed, InboxUnavailable, MessageRejected, SourceUnavailable,
                     TweetKind)
from .state import load_state, save_state, state_lock

log = logging.getLogger(__name__)

DEFAULT_STATUS_PAGE = "https://joaq-uinv.github.io/twitter_bot/"
MAX_COMMANDS_PER_CHECK = 20     # plan DD-6
MAX_READS_PER_CHECK = 10        # review P-3: pages of stranger updates read past


@dataclass
class RunResult:
    sent: int = 0
    withheld: int = 0
    bootstrapped: bool = False
    outage: bool = False
    failed: int = 0
    paused: bool = False


class Pipeline:
    def __init__(self, config, source, sink, *, inbox=None,
                 operator_chat_id: int | None = None,
                 mirror_latest_path: str | None = None,
                 status_page_url: str = DEFAULT_STATUS_PAGE,
                 clock=lambda: datetime.now(timezone.utc)):
        self.config = config
        self.source = source
        self.sink = sink
        # Spec 003: where the operator's commands come from and who the operator is.
        self.inbox = inbox
        self.operator_chat_id = operator_chat_id
        self.mirror_latest_path = mirror_latest_path
        self.status_page_url = status_page_url
        self.clock = clock
        self._chat_checked = False

    def _send(self, message: str, *, preview_url: str | None = None) -> None:
        """Every message goes through here, so the chat check precedes the first send
        of the run (spec D-4, plan DD-7) and costs nothing on a run that sends nothing.
        """
        if not self._chat_checked:
            if not self.sink.chat_is_private():
                raise DeliveryFailed("the configured chat is not a private chat")
            self._chat_checked = True
        self.sink.send(message, preview_url=preview_url)

    def _deliver(self, t, handle: str) -> None:
        """Send one post. Raises DeliveryFailed if it was not delivered in any form.

        E-21/D-4: a post the channel refuses outright is retried once in minimal form,
        so one refused text cannot block every post queued behind it.
        """
        try:
            self._send(render(t, handle), preview_url=t.preview_url)
        except MessageRejected as exc:
            log.warning("message refused for %s, retrying in minimal form: %s", t.id, exc)
            # Failure propagates as usual. No card: the retry carries only what is
            # essential, so nothing optional can be the reason it is refused (review P-3).
            self._send(render_minimal(t, handle))
            log.warning("delivered in minimal form tweet_id=%s", t.id)

    def _wanted(self, kind: TweetKind) -> bool:
        if kind is TweetKind.RETWEET:
            return self.config.include_retweets
        if kind is TweetKind.REPLY:
            return self.config.include_replies
        if kind is TweetKind.QUOTE:
            return self.config.include_quotes
        return True

    def run_once(self) -> RunResult:
        cfg = self.config
        handle = cfg.handle
        result = RunResult()
        self._chat_checked = False

        # The lock spans the whole check so two concurrent runs cannot both decide a
        # post is undelivered and send it twice (E-17).
        with state_lock(cfg.STATE_PATH):
            state = load_state(cfg.STATE_PATH, handle)

            try:
                tweets, outage = self.source.fetch(handle), None
            except SourceUnavailable as exc:
                tweets, outage = None, exc

            # Spec 003 D-2: once ever, before anything else this channel carries. A
            # fresh install is announced by its bootstrap message instead.
            if state.bootstrapped and not state.announced:
                try:
                    self._send(render_announcement(handle))
                    state.announced = True
                    save_state(cfg.STATE_PATH, state)
                except DeliveryFailed as exc:
                    log.error("could not deliver the switch announcement: %s", exc)
                    result.failed = 1

            if outage is not None:
                result.outage = True
                # Edge-triggered: notify on the transition into an outage only (DD-6).
                # Also while paused: a pause never hides a broken relay (003 AC-4.3).
                if not state.outage_notified:
                    try:
                        self._send(render_outage(handle, str(outage)))
                    except DeliveryFailed as send_exc:
                        log.error("could not deliver outage notice: %s", send_exc)
                    state.outage_notified = True
                    save_state(cfg.STATE_PATH, state)
                else:
                    log.warning("sources still unavailable: %s", outage)
                self._handle_commands(state, None, None, result)       # AC-3.3
                result.paused = state.paused_since is not None
                log.info("check complete: outage (no sources reachable)")
                return self._finish(state, result)

            if state.outage_notified:
                log.info("sources recovered")
                state.outage_notified = False   # re-arm for the next outage (AC-4.2)

            state.last_success = self.clock()

            # Bootstrap: adopt history as already-delivered so enabling the relay, or
            # retargeting it, cannot flood the operator (AC-3.1).
            if not state.bootstrapped:
                for t in tweets:
                    state.mark_seen(t.id)
                state.bootstrapped = True
                save_state(cfg.STATE_PATH, state)
                try:
                    self._send(render_bootstrap(handle, len(tweets)))
                    result.sent = 1
                    state.announced = True
                except DeliveryFailed as exc:
                    log.error("could not deliver liveness message: %s", exc)
                    result.failed = 1      # A-10: a paused channel on a first run is not green
                result.bootstrapped = True
                self._handle_commands(state, [], tweets, result)
                result.paused = state.paused_since is not None
                log.info("check complete: bootstrapped %d existing posts as seen",
                         len(tweets))
                return self._finish(state, result)

            # Membership test, never a high-water mark (DD-1).
            pending = [t for t in tweets if state.is_new(t.id)]

            # Excluded kinds are marked seen, not left pending: they were never
            # queued, so they must not resurface if the operator flips a toggle.
            excluded = [t for t in pending if not self._wanted(t.kind)]
            for t in excluded:
                state.mark_seen(t.id)
            if excluded:
                save_state(cfg.STATE_PATH, state)

            queue = sorted((t for t in pending if self._wanted(t.kind)),
                           key=lambda t: (t.published_at, t.id))

            self._handle_commands(state, queue, tweets, result)

            # Spec 003 FR-13, FR-14: while paused nothing is delivered or marked seen,
            # so the queue is still there on /resume.
            if state.paused_since is not None:
                result.paused = True
                log.info("check complete: paused, %d posts waiting", len(queue))
                return self._finish(state, result)

            cap = cfg.max_messages_per_run
            batch, withheld = queue[:cap], queue[cap:]
            result.withheld = len(withheld)

            for t in batch:
                try:
                    self._deliver(t, handle)
                except DeliveryFailed as exc:
                    # Stop the batch: the channel is unhealthy, and continuing would
                    # burn the daily quota. Unsent posts stay pending for next check.
                    log.error("delivery failed for %s, stopping batch: %s", t.id, exc)
                    result.failed = 1
                    break
                state.mark_seen(t.id)
                save_state(cfg.STATE_PATH, state)   # FR-12: persist per success
                result.sent += 1
                log.info("delivered tweet_id=%s", t.id)   # traced by the run summary

            if withheld and not result.failed:
                try:
                    self._send(render_withheld(len(withheld)))
                except DeliveryFailed as exc:
                    log.error("could not deliver withheld notice: %s", exc)
                    result.failed = 1      # A-8 applies to every delivery, notices included

            log.info("check complete: sent=%d withheld=%d", result.sent, result.withheld)
            return self._finish(state, result)

    def _handle_commands(self, state, queue, tweets, result: RunResult) -> None:
        """The operator's commands, oldest first (spec 003 FR-6..FR-10).

        `queue` is what is waiting to be delivered, or None when the sources are down.
        Each command's effect and offset are saved *before* its reply goes out (DD-5):
        a crash or a failed reply can lose a reply, never apply a command twice.
        """
        if self.inbox is None:
            return
        handled = 0
        # Review P-3: a stranger can fill whole pages; keep reading past them, a bounded
        # number of times, so they cannot starve the operator's commands (AC-6.2).
        for _page in range(MAX_READS_PER_CHECK):
            try:
                inbox = self.inbox.read(state.update_offset)
            except InboxUnavailable as exc:
                log.error("could not read the operator's commands: %s", exc)
                result.failed = 1
                break
            handled, finished = self._handle_page(inbox, state, queue, tweets, result, handled)
            if not (finished and inbox.more):
                break
        save_state(self.config.STATE_PATH, state)

    def _handle_page(self, inbox, state, queue, tweets, result: RunResult,
                     handled: int) -> tuple[int, bool]:
        """One page of updates. Returns the running count of handled commands and
        whether the whole page was consumed (so the next page may be read)."""
        for message in inbox.messages:
            if message.update_id < state.update_offset:
                continue                               # FR-9: handled in an earlier check
            if not self._from_operator(message):
                # FR-7: skipped without a reply, a state change or a log line.
                state.update_offset = max(state.update_offset, message.update_id + 1)
                continue
            if handled == MAX_COMMANDS_PER_CHECK:
                return handled, False                  # DD-6: the rest wait a check
            command = parse(message.text)
            reply = self._apply(command, state, queue, tweets)
            state.update_offset = max(state.update_offset, message.update_id + 1)
            save_state(self.config.STATE_PATH, state)
            handled += 1
            log.info("handled command %s", command.value)
            try:
                self._send(reply)
            except DeliveryFailed as exc:
                log.error("could not deliver the reply to %s: %s", command.value, exc)
                result.failed = 1
                return handled, False
        # Everything read was handled or skipped, malformed updates included.
        state.update_offset = max(state.update_offset, inbox.next_offset)
        return handled, True

    def _from_operator(self, message) -> bool:
        return (self.operator_chat_id is not None
                and message.chat_id == self.operator_chat_id
                and message.chat_type == "private")

    def _apply(self, command: Command, state, queue, tweets) -> str:
        """Change state for `command` and return its reply (data-model.md "Replies")."""
        waiting = len(queue) if queue is not None else None
        if command is Command.PAUSE:
            before = state.paused_since
            if before is None:
                state.paused_since = self.clock()
            return render_pause(before)
        if command is Command.RESUME:
            before = state.paused_since
            state.paused_since = None
            # Reposts carry the original post's date, which can be years old, so they
            # say nothing about how far back the sources reach (review P-3).
            own = [t.published_at for t in (tweets or []) if t.kind is not TweetKind.RETWEET]
            oldest = min(own, default=None)
            return render_resume(before, waiting=waiting,
                                 cap=self.config.max_messages_per_run, oldest_listed=oldest)
        if command is Command.STATUS:
            return render_status(last_check=state.last_check, waiting=waiting,
                                 paused_since=state.paused_since,
                                 mirrors=self._mirror_health(),
                                 page_url=self.status_page_url)
        if command is Command.HELP:
            return render_help()
        return render_unknown()

    def _mirror_health(self) -> tuple[int, int] | None:
        """In-use mirrors healthy / total from spec 002's latest round, which the
        workflow copies in (plan DD-11). Missing or invalid means "not available"."""
        if not self.mirror_latest_path:
            return None
        try:
            raw = Path(self.mirror_latest_path).read_text(encoding="utf-8")
            latest = latest_from_json(json.loads(raw))
        except FileNotFoundError:
            return None
        except Exception:                      # hostile-tolerant, as in 002 E-20
            log.warning("mirror health file is unreadable; /status will say so")
            return None
        if latest.round_t is None:
            return None
        return latest.in_use_healthy, latest.in_use_total

    def _finish(self, state, result: RunResult) -> RunResult:
        # What /status reports as "the last check" on the next run (spec 003 AC-3.1).
        state.last_check = (self.clock(), result.sent)
        save_state(self.config.STATE_PATH, state)
        return result
