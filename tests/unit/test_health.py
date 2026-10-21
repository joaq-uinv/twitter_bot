"""Health core: pure functions of one round's outcomes and a clock (spec 002 FR-4,
FR-7, FR-10; plan DD-10)."""
from datetime import datetime, timedelta, timezone

from hypothesis import given, strategies as st

from tweet_relay.mirrors.health import evaluate_round
from tweet_relay.mirrors.models import Freshness, ProbeOutcome, Reason, Role

T = datetime(2026, 10, 11, 12, 0, tzinfo=timezone.utc)
H = timedelta(hours=1)


def ok(newest, ms=100):
    return ProbeOutcome(usable=True, reason=None, ms=ms, newest=newest)


def bad(reason=Reason.TIMED_OUT):
    return ProbeOutcome(usable=False, reason=reason, ms=None, newest=None)


def by_host(results):
    return {r.host: r for r in results}


# ---------- T011: freshness (FR-4, E-1..E-4) ----------

def test_reference_is_newest_in_use_post():
    rnd = evaluate_round(T, [("a", Role.IN_USE, ok(T - 2 * H)), ("b", Role.IN_USE, ok(T - 1 * H))])
    assert rnd.reference == T - 1 * H


def test_more_than_six_hours_behind_is_stale():
    rnd = evaluate_round(T, [("a", Role.IN_USE, ok(T - H)),
                             ("b", Role.IN_USE, ok(T - H - 6 * H - timedelta(seconds=1)))])
    r = by_host(rnd.results)
    assert r["a"].freshness is Freshness.FRESH and r["a"].healthy
    assert r["b"].freshness is Freshness.STALE and r["b"].reason is Reason.STALE
    assert not r["b"].healthy


def test_exactly_six_hours_behind_is_fresh():
    rnd = evaluate_round(T, [("a", Role.IN_USE, ok(T)), ("b", Role.IN_USE, ok(T - 6 * H))])
    assert by_host(rnd.results)["b"].freshness is Freshness.FRESH


def test_quiet_account_is_not_stale():
    """E-4: no posts for a week, but every honest mirror agrees: all fresh."""
    week = T - timedelta(days=7)
    rnd = evaluate_round(T, [("a", Role.IN_USE, ok(week)), ("b", Role.CANDIDATE, ok(week))])
    assert all(r.freshness is Freshness.FRESH for r in rnd.results)


def test_no_usable_in_use_mirror_gives_unknown():
    """E-3: no reference, so freshness is unknown rather than guessed."""
    rnd = evaluate_round(T, [("a", Role.IN_USE, bad()), ("c", Role.CANDIDATE, ok(T - 30 * H))])
    assert rnd.reference is None
    c = by_host(rnd.results)["c"]
    assert c.freshness is Freshness.UNKNOWN and c.healthy        # D-4


def test_unusable_results_carry_their_reason():
    rnd = evaluate_round(T, [("a", Role.IN_USE, ok(T)), ("b", Role.IN_USE, bad(Reason.SENT_ELSEWHERE))])
    b = by_host(rnd.results)["b"]
    assert (b.usable, b.freshness, b.reason) == (False, None, Reason.SENT_ELSEWHERE)


def test_future_dated_newest_cannot_set_the_reference():
    """E-2, even if a probe let one through."""
    rnd = evaluate_round(T, [("a", Role.IN_USE, ok(T + 2 * H)), ("b", Role.IN_USE, ok(T - H))])
    assert rnd.reference == T - H


def test_all_results_share_the_round_time():
    rnd = evaluate_round(T, [("a", Role.IN_USE, ok(T)), ("c", Role.CANDIDATE, bad())])
    assert {r.t for r in rnd.results} == {T}


offsets = st.integers(min_value=-48 * 60, max_value=48 * 60).map(lambda m: T + timedelta(minutes=m))


@given(in_use=st.lists(offsets, min_size=1, max_size=4),
       candidates=st.lists(offsets, min_size=0, max_size=6))
def test_candidates_never_move_the_reference(in_use, candidates):
    """E-2: a hostile candidate (post-dated or not) cannot make honest mirrors stale."""
    base = [(f"u{i}", Role.IN_USE, ok(n)) for i, n in enumerate(in_use)]
    extra = [(f"c{i}", Role.CANDIDATE, ok(n)) for i, n in enumerate(candidates)]
    assert evaluate_round(T, base).reference == evaluate_round(T, base + extra).reference


# ---------- T013: urgent verdict and episodes (FR-7, AC-1.1..1.3, AC-1.6, E-18) ----------

from tweet_relay.mirrors.health import EpisodeState, Transition, next_episode, verdict  # noqa: E402


def _round(*in_use_ok, candidates_ok=()):
    outcomes = [(f"u{i}", Role.IN_USE, ok(T) if good else bad()) for i, good in enumerate(in_use_ok)]
    outcomes += [(f"c{i}", Role.CANDIDATE, ok(T) if good else bad())
                 for i, good in enumerate(candidates_ok)]
    return evaluate_round(T, outcomes)


def test_one_of_four_healthy_is_at_risk():
    v = verdict(_round(True, False, False, False))
    assert (v.in_use_healthy, v.in_use_total, v.at_risk) == (1, 4, True)


def test_exactly_two_healthy_is_not_at_risk():
    """AC-1.2: the boundary."""
    assert verdict(_round(True, True, False, False)).at_risk is False


def test_candidates_do_not_count_toward_safety():
    assert verdict(_round(True, False, candidates_ok=(True, True, True))).at_risk is True


def test_fewer_than_two_configured_is_always_at_risk():
    """E-18."""
    assert verdict(_round(True)).at_risk is True


def test_episode_starts_on_first_at_risk_round():
    state, tr = next_episode(EpisodeState(at_risk_since=None), verdict(_round(True, False)), T)
    assert tr is Transition.STARTED and state.at_risk_since == T


def test_episode_continues_without_resetting_its_start():
    started = EpisodeState(at_risk_since=T - 12 * H)
    state, tr = next_episode(started, verdict(_round(True, False)), T)
    assert tr is Transition.CONTINUING and state.at_risk_since == T - 12 * H


def test_episode_clears_once():
    """AC-1.3: told once that the risk has cleared."""
    started = EpisodeState(at_risk_since=T - 12 * H)
    state, tr = next_episode(started, verdict(_round(True, True)), T)
    assert tr is Transition.CLEARED and state.at_risk_since is None
    _, tr2 = next_episode(state, verdict(_round(True, True)), T + 6 * H)
    assert tr2 is Transition.NONE


# ---------- T015: soft warnings (FR-10, AC-2.1..2.5, E-15..E-17) ----------

from tweet_relay.mirrors.health import plan_warnings  # noqa: E402
from tweet_relay.mirrors.models import ProbeResult  # noqa: E402


def res(t, host="m", healthy=False, role=Role.IN_USE, reason=Reason.TIMED_OUT):
    if healthy:
        return ProbeResult(t=t, host=host, role=role, usable=True, freshness=Freshness.FRESH,
                           reason=None, ms=10, newest=t)
    return ProbeResult(t=t, host=host, role=role, usable=False, freshness=None,
                       reason=reason, ms=None, newest=None)


def every_6h(n, **kw):
    """n rounds ending at T, 6 h apart."""
    return [res(T - 6 * H * i, **kw) for i in reversed(range(n))]


def test_unhealthy_for_every_round_in_24h_opens_a_warning():
    p = plan_warnings(every_6h(5), now=T, open_now=set())
    assert set(p.open) == {"m"}
    since, reason = p.open["m"]
    assert since == T - 18 * H and reason is Reason.TIMED_OUT   # earliest result in window


def test_one_healthy_round_in_the_window_prevents_it():
    """AC-2.2."""
    history = every_6h(5)
    history[2] = res(history[2].t, healthy=True)
    assert plan_warnings(history, now=T, open_now=set()).open == {}


def test_a_single_unhealthy_round_is_not_enough():
    """AC-2.1: at least 2 rounds."""
    assert plan_warnings([res(T)], now=T, open_now=set()).open == {}


def test_open_warning_is_updated_not_duplicated():
    """AC-2.3."""
    p = plan_warnings(every_6h(5, reason=Reason.SENT_ELSEWHERE),
                      now=T, open_now={"m"})
    assert p.open == {} and p.update == {"m": Reason.SENT_ELSEWHERE} and p.close == set()


def test_first_healthy_round_closes_it():
    """AC-2.4."""
    history = every_6h(4) + [res(T + 6 * H, healthy=True)]
    p = plan_warnings(history, now=T + 6 * H, open_now={"m"})
    assert p.close == {"m"} and p.update == {}


def test_late_rounds_do_not_close_a_warning():
    """Only a healthy result closes one; a thin window (delayed schedule) does not."""
    p = plan_warnings([res(T)], now=T, open_now={"m"})
    assert p.close == set() and p.update == {"m": Reason.TIMED_OUT}


def test_candidates_never_raise_warnings():
    """AC-2.5."""
    assert plan_warnings(every_6h(5, role=Role.CANDIDATE), now=T, open_now=set()).open == {}


def test_former_mirror_warning_is_closed():
    """E-17: removed from the configuration while a warning was open."""
    history = every_6h(4) + [res(T + 6 * H, role=Role.FORMER)]
    assert plan_warnings(history, now=T + 6 * H, open_now={"m"}).close == {"m"}


def test_flapping_mirror_never_opens_a_warning():
    """E-15."""
    history = [res(T - 6 * H * i, healthy=(i % 2 == 0)) for i in reversed(range(12))]
    assert plan_warnings(history, now=T, open_now=set()).open == {}
