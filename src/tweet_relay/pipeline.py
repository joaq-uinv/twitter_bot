"""One check: fetch, filter, order, cap, deliver, persist.

The ordering of steps is load-bearing:
  * sort before capping, so a backlog drains oldest-first (D-3);
  * persist after each successful send, so a crash or partial failure never
    re-delivers or loses a post (E-5, E-6, FR-12).
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone

from .formatter import render, render_bootstrap, render_outage, render_withheld
from .models import DeliveryFailed, SourceUnavailable, TweetKind
from .state import load_state, save_state, state_lock

log = logging.getLogger(__name__)


@dataclass
class RunResult:
    sent: int = 0
    withheld: int = 0
    bootstrapped: bool = False
    outage: bool = False
    failed: int = 0


class Pipeline:
    def __init__(self, config, source, sink):
        self.config = config
        self.source = source
        self.sink = sink

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

        # The lock spans the whole check so two concurrent runs cannot both decide a
        # post is undelivered and send it twice (E-17).
        with state_lock(cfg.STATE_PATH):
            state = load_state(cfg.STATE_PATH, handle)

            try:
                tweets = self.source.fetch(handle)
            except SourceUnavailable as exc:
                result.outage = True
                # Edge-triggered: notify on the transition into an outage only (DD-6).
                if not state.outage_notified:
                    try:
                        self.sink.send(render_outage(handle, str(exc)))
                    except DeliveryFailed as send_exc:
                        log.error("could not deliver outage notice: %s", send_exc)
                    state.outage_notified = True
                    save_state(cfg.STATE_PATH, state)
                else:
                    log.warning("sources still unavailable: %s", exc)
                return result

            if state.outage_notified:
                log.info("sources recovered")
                state.outage_notified = False   # re-arm for the next outage (AC-4.2)

            state.last_success = datetime.now(timezone.utc)

            # Bootstrap: adopt history as already-delivered so enabling the relay, or
            # retargeting it, cannot flood the operator (AC-3.1).
            if not state.bootstrapped:
                for t in tweets:
                    state.mark_seen(t.id)
                state.bootstrapped = True
                save_state(cfg.STATE_PATH, state)
                try:
                    self.sink.send(render_bootstrap(handle, len(tweets)))
                    result.sent = 1
                except DeliveryFailed as exc:
                    log.error("could not deliver liveness message: %s", exc)
                result.bootstrapped = True
                return result

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

            cap = cfg.max_messages_per_run
            batch, withheld = queue[:cap], queue[cap:]
            result.withheld = len(withheld)

            for t in batch:
                try:
                    self.sink.send(render(t, handle))
                except DeliveryFailed as exc:
                    # Stop the batch: the channel is unhealthy, and continuing would
                    # burn the daily quota. Unsent posts stay pending for next check.
                    log.error("delivery failed for %s, stopping batch: %s", t.id, exc)
                    result.failed = 1
                    break
                state.mark_seen(t.id)
                save_state(cfg.STATE_PATH, state)   # FR-12: persist per success
                result.sent += 1

            if withheld and not result.failed:
                try:
                    self.sink.send(render_withheld(len(withheld)))
                except DeliveryFailed as exc:
                    log.warning("could not deliver withheld notice: %s", exc)

            save_state(cfg.STATE_PATH, state)
            log.info("check complete: sent=%d withheld=%d", result.sent, result.withheld)
            return result
