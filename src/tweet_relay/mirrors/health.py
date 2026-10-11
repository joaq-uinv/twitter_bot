"""Health core: pure functions of one round's outcomes and a clock (spec 002).

No I/O here. Freshness, the urgent verdict, episodes and the soft-warning rule are
decided from data alone, so every rule is unit- and property-tested (plan:
functional core, imperative shell).
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum

from .models import Freshness, ProbeOutcome, ProbeResult, Reason, Role

STALE_AFTER = timedelta(hours=6)            # FR-4
FUTURE_TOLERANCE = timedelta(minutes=5)     # DD-10: clock skew, not a fresher mirror


@dataclass(frozen=True)
class Round:
    t: datetime
    reference: datetime | None
    results: list[ProbeResult]


def evaluate_round(t: datetime, outcomes: list[tuple[str, Role, ProbeOutcome]]) -> Round:
    """Turn one round's probe outcomes into results with freshness (FR-4, DD-10).

    The reference is the newest post among usable *in-use* results only, ignoring
    future-dated ones, so a candidate can never move it (E-2). Without a reference,
    freshness is unknown rather than guessed (E-3).
    """
    cutoff = t + FUTURE_TOLERANCE
    in_use_newest = [o.newest for _, role, o in outcomes
                     if role is Role.IN_USE and o.usable and o.newest <= cutoff]
    reference = max(in_use_newest, default=None)

    results = []
    for host, role, o in outcomes:
        if not o.usable:
            freshness, reason = None, o.reason
        elif reference is None:
            freshness, reason = Freshness.UNKNOWN, None
        elif reference - o.newest > STALE_AFTER:
            freshness, reason = Freshness.STALE, Reason.STALE
        else:
            freshness, reason = Freshness.FRESH, None
        results.append(ProbeResult(t=t, host=host, role=role, usable=o.usable,
                                   freshness=freshness, reason=reason, ms=o.ms,
                                   newest=o.newest))
    return Round(t=t, reference=reference, results=results)


# ---------- urgent verdict and episodes (FR-7, AC-1.1..1.3, AC-1.6) ----------

MIN_HEALTHY_IN_USE = 2


@dataclass(frozen=True)
class Verdict:
    in_use_healthy: int
    in_use_total: int
    at_risk: bool


def verdict(rnd: Round) -> Verdict:
    """At risk when fewer than 2 in-use mirrors are healthy, on the first bad round
    (FR-7). Fewer than 2 configured is at risk by definition (E-18); candidates never
    count toward safety."""
    in_use = [r for r in rnd.results if r.role is Role.IN_USE]
    healthy = sum(r.healthy for r in in_use)
    return Verdict(in_use_healthy=healthy, in_use_total=len(in_use),
                   at_risk=healthy < MIN_HEALTHY_IN_USE)


class Transition(StrEnum):
    NONE = "none"
    STARTED = "started"
    CONTINUING = "continuing"
    CLEARED = "cleared"


@dataclass(frozen=True)
class EpisodeState:
    at_risk_since: datetime | None


def next_episode(prev: EpisodeState, v: Verdict, t: datetime) -> tuple[EpisodeState, Transition]:
    """One at-risk episode per stretch of at-risk rounds, with one all-clear (AC-1.3)."""
    if v.at_risk:
        if prev.at_risk_since is None:
            return EpisodeState(at_risk_since=t), Transition.STARTED
        return prev, Transition.CONTINUING
    if prev.at_risk_since is not None:
        return EpisodeState(at_risk_since=None), Transition.CLEARED
    return prev, Transition.NONE


# ---------- soft warnings (FR-10, AC-2.1..2.5) ----------

SOFT_WINDOW = timedelta(hours=24)
SOFT_MIN_RESULTS = 2


@dataclass(frozen=True)
class WarningPlan:
    open: dict[str, tuple[datetime, Reason]]    # host -> (unhealthy since, latest reason)
    update: dict[str, Reason]                   # still unhealthy: latest reason (AC-2.3)
    close: set[str]                             # recovered, or no longer in use (AC-2.4, E-17)


def plan_warnings(history: list[ProbeResult], now: datetime, open_now: set[str]) -> WarningPlan:
    """Reconcile the soft warnings with history (data-model.md, soft-warning rule).

    Open: an in-use host unhealthy in *every* result of the last 24 h, with at least
    two such results (so a blip or flapping never opens one: AC-2.2, E-15). Close:
    only on a healthy result, or when the host is no longer in use (candidates never
    hold warnings: AC-2.5, E-17). A thin window from delayed rounds never closes one.
    """
    current = {r.host: r for r in history if r.t == now}
    close = {h for h in open_now
             if h not in current or current[h].role is not Role.IN_USE or current[h].healthy}
    update = {h: current[h].reason for h in open_now - close}

    window: dict[str, list[ProbeResult]] = {}
    for r in history:
        if now - SOFT_WINDOW < r.t <= now:
            window.setdefault(r.host, []).append(r)
    opened = {}
    for host, latest in current.items():
        if host in open_now or latest.role is not Role.IN_USE:
            continue
        rows = window.get(host, [])
        if len(rows) >= SOFT_MIN_RESULTS and not any(r.healthy for r in rows):
            opened[host] = (min(r.t for r in rows), latest.reason)
    return WarningPlan(open=opened, update=update, close=close)
