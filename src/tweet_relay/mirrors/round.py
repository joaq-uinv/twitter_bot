"""One probe round, end to end (spec 002 plan Architecture).

The imperative shell around the pure core: load history, discover, build the roster,
probe sequentially, evaluate, reconcile warnings, save, build status. It is read-only
with respect to delivery: no sink is built and the relay's state is never opened (FR-2).
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime

from .directory import DirectoryUnavailable
from .health import Round, Transition, Verdict, evaluate_round, next_episode, plan_warnings, verdict
from .history import History, Latest
from .roster import build_roster
from .status import build_status
from .tracker import TrackerUnavailable

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class RoundOutcome:
    round: Round
    verdict: Verdict
    transition: Transition
    status: dict
    tracker_error: bool


def run_round(*, config, probe, directory, store, tracker, now: datetime) -> RoundOutcome:
    history = store.load()
    if history.corrupt:
        log.error("mirror history was unreadable; starting a fresh history (E-20)")

    try:
        found = directory.list()
    except DirectoryUnavailable as exc:
        log.warning("mirror list unavailable, keeping the last good candidates: %s", exc)
        found = None

    entries, discovery = build_roster(config.instances, history.results, found,
                                      history.latest.discovery, now)
    # DD-12: sequential, so volunteer servers see one request at a time.
    outcomes = [(host, role, probe.probe(host, config.handle)) for host, role in entries]

    rnd = evaluate_round(now, outcomes)
    v = verdict(rnd)
    episode, transition = next_episode(history.latest.episode, v, now)
    results = history.results + rnd.results

    warnings, tracker_error = _reconcile(tracker, results, now, history.latest.warnings)

    latest = Latest(round_t=now, reference=rnd.reference, in_use_healthy=v.in_use_healthy,
                    in_use_total=v.in_use_total, at_risk=v.at_risk, episode=episode,
                    discovery=discovery, warnings=warnings)
    store.save(History(results=results, latest=latest), now)
    return RoundOutcome(round=rnd, verdict=v, transition=transition,
                        status=build_status(results, latest, now), tracker_error=tracker_error)


def _reconcile(tracker, results, now, previous) -> tuple[dict[str, datetime], bool]:
    """Open what is missing, update what persists, close what recovered (FR-10).

    On tracker failure the round still records and publishes, keeping the last known
    warnings, and reports check-broken (contract warning-tracker 3).
    """
    try:
        open_now = tracker.open_warnings()
        plan = plan_warnings(results, now, set(open_now))
        for host, (since, reason) in plan.open.items():
            tracker.open(host, since, reason)
        for host, reason in plan.update.items():
            tracker.update(host, reason)
        for host in plan.close:
            tracker.close(host)
    except TrackerUnavailable as exc:
        log.error("warning tracker unavailable; soft warnings are not being tracked: %s", exc)
        return dict(previous), True
    except Exception as exc:
        # Review #2: whatever the tracker does, the round's results are still saved and
        # published (contract warning-tracker 3). Type only: the message could be anything.
        log.error("warning tracker failed unexpectedly (%s); soft warnings not updated",
                  type(exc).__name__)
        return dict(previous), True
    kept = {h: t for h, t in open_now.items() if h not in plan.close}
    # A newly opened warning is dated now, as its issue's created_at will be on every
    # later round, so the page's "open since" does not jump.
    return {**kept, **{h: now for h in plan.open}}, False
