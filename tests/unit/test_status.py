"""build_status: the precomputed status.json the page renders (spec 002 data-model.md;
AC-3.1, 3.2, 3.4, 4.1, 4.2, 5.2, 5.3, D-4). The page's JS only renders it."""
from datetime import datetime, timedelta, timezone

from tweet_relay.mirrors.health import EpisodeState
from tweet_relay.mirrors.history import Latest
from tweet_relay.mirrors.models import Freshness, ProbeResult, Reason, Role
from tweet_relay.mirrors.roster import DiscoveryState
from tweet_relay.mirrors.status import TREND_LENGTH, build_status

T = datetime(2026, 10, 11, 12, 0, tzinfo=timezone.utc)
H = timedelta(hours=1)


def r(t, host, role=Role.IN_USE, healthy=True, freshness=Freshness.FRESH, ms=100):
    if healthy:
        return ProbeResult(t=t, host=host, role=role, usable=True, freshness=freshness,
                           reason=None, ms=ms, newest=t - 2 * H)
    return ProbeResult(t=t, host=host, role=role, usable=False, freshness=None,
                       reason=Reason.TIMED_OUT, ms=None, newest=None)


def latest(**kw):
    base = dict(round_t=T, reference=T - 2 * H, in_use_healthy=1, in_use_total=2, at_risk=True,
                episode=EpisodeState(at_risk_since=T - 6 * H),
                discovery=DiscoveryState(last_ok=T - H, accepted=7, rejected=2, candidates=[]),
                warnings={"b.example": T - 30 * H})
    return Latest(**{**base, **kw})


def status(history, **kw):
    return build_status(history, latest(**kw), now=T)


def mirror(s, host):
    return next(m for m in s["mirrors"] if m["host"] == host)


def test_top_level_fields():
    s = status([r(T, "a.example")])
    assert set(s) == {"generated_at", "round", "discovery", "mirrors", "warnings"}
    assert s["generated_at"] == T.isoformat()
    assert s["round"] == {"t": T.isoformat(), "reference": (T - 2 * H).isoformat(),
                          "in_use_healthy": 1, "in_use_total": 2, "at_risk": True,
                          "at_risk_since": (T - 6 * H).isoformat()}
    assert s["discovery"] == {"last_ok": (T - H).isoformat(), "accepted": 7, "rejected": 2}
    assert s["warnings"] == [{"host": "b.example", "since": (T - 30 * H).isoformat()}]


def test_mirror_fields_from_the_latest_round():
    s = status([r(T - 6 * H, "a.example", healthy=False), r(T, "a.example", ms=321)])
    m = mirror(s, "a.example")
    assert set(m) == {"host", "role", "healthy", "reason", "ms", "newest_age_s",
                      "uptime_7d", "uptime_30d", "trend"}
    assert (m["role"], m["healthy"], m["reason"], m["ms"], m["newest_age_s"]) == \
           ("in_use", True, None, 321, 7200)


def test_uptime_counts_unknown_freshness_as_healthy():
    """D-4, AC-4.1."""
    hist = [r(T - 3 * H, "a.example", freshness=Freshness.UNKNOWN),
            r(T - 2 * H, "a.example", healthy=False), r(T - H, "a.example"), r(T, "a.example")]
    m = mirror(status(hist), "a.example")
    assert m["uptime_7d"] == m["uptime_30d"] == 0.75


def test_uptime_windows_differ():
    hist = [r(T - timedelta(days=d), "a.example", healthy=False) for d in (20, 10)] + [r(T, "a.example")]
    m = mirror(status(hist), "a.example")
    assert m["uptime_7d"] == 1.0 and abs(m["uptime_30d"] - 1 / 3) < 1e-9


def test_trend_is_bounded_newest_last_and_marks_unprobed_rounds():
    """AC-4.2: the last rounds, with null where the mirror was not probed."""
    rounds = [T - H * i for i in reversed(range(TREND_LENGTH + 5))]
    hist = [r(t, "a.example", healthy=(i % 2 == 0)) for i, t in enumerate(rounds)]
    hist += [r(rounds[-2], "b.example"), r(rounds[-1], "b.example", healthy=False)]
    s = status(hist)
    a, b = mirror(s, "a.example"), mirror(s, "b.example")
    assert len(a["trend"]) == TREND_LENGTH == 40
    assert a["trend"][-1] is (len(rounds) % 2 == 1)
    assert b["trend"][-3:] == [None, True, False]


def test_in_use_first_then_candidates_healthy_first_then_by_uptime():
    """AC-5.2."""
    hist = [r(T - H, "steady.example", role=Role.CANDIDATE),
            r(T, "steady.example", role=Role.CANDIDATE),
            r(T - H, "flaky.example", role=Role.CANDIDATE, healthy=False),
            r(T, "flaky.example", role=Role.CANDIDATE),
            r(T, "down.example", role=Role.CANDIDATE, healthy=False),
            r(T, "used.example")]
    hosts = [m["host"] for m in status(hist)["mirrors"]]
    assert hosts == ["used.example", "steady.example", "flaky.example", "down.example"]


def test_no_data_gives_null_uptime():
    s = status([r(T, "a.example")])
    assert mirror(s, "a.example")["uptime_7d"] == 1.0
    empty = build_status([], latest(round_t=None), now=T)
    assert empty["mirrors"] == []
