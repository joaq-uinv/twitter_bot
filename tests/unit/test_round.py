"""run_round: one probe round, end to end over test doubles (spec 002 FR-1, FR-2,
FR-10, AC-2.3, AC-2.4, AC-5.1; contract warning-tracker.md 3)."""
import pathlib
from datetime import datetime, timedelta, timezone

import pytest

from tests.doubles import FakeTracker, FixtureMirrorProbe, MemoryHistoryStore, StaticDirectory
from tweet_relay.mirrors.directory import DirectoryRead, DirectoryUnavailable
from tweet_relay.mirrors.health import Transition
from tweet_relay.mirrors.history import EMPTY_LATEST, History
from tweet_relay.mirrors.models import ProbeOutcome, ProbeResult, Reason, Role
from tweet_relay.mirrors.round import run_round

T = datetime(2026, 10, 11, 12, 0, tzinfo=timezone.utc)
H = timedelta(hours=1)


def ok():
    return ProbeOutcome(usable=True, reason=None, ms=100, newest=T - H)


def bad(reason=Reason.TIMED_OUT):
    return ProbeOutcome(usable=False, reason=reason, ms=None, newest=None)


@pytest.fixture
def cfg(config):
    return config.model_copy(update={
        "NITTER_INSTANCES": "https://a.example,https://b.example,https://c.example"})


def _run(cfg, outcomes, *, found=DirectoryRead(["cand.example"], 1, 0), dir_error=None,
         history=None, tracker=None):
    probe = FixtureMirrorProbe(outcomes)
    store = MemoryHistoryStore(history)
    tracker = tracker or FakeTracker()
    out = run_round(config=cfg, probe=probe, directory=StaticDirectory(found, dir_error),
                    store=store, tracker=tracker, now=T)
    return out, probe, store, tracker


ALL_OK = {"a.example": ok(), "b.example": ok(), "c.example": ok(), "cand.example": ok()}


def test_every_roster_host_is_probed_once_in_order(cfg):
    """FR-1, AC-5.1, DD-12."""
    _, probe, _, _ = _run(cfg, ALL_OK)
    assert probe.calls == ["a.example", "b.example", "c.example", "cand.example"]


def test_results_are_appended_and_latest_updated(cfg):
    out, _, store, _ = _run(cfg, ALL_OK)
    assert [r.host for r in store.saved.results] == ["a.example", "b.example", "c.example",
                                                     "cand.example"]
    assert store.saved.latest.round_t == T and store.saved.latest.in_use_total == 3
    assert out.verdict.at_risk is False and out.status["round"]["at_risk"] is False


def test_at_risk_round_starts_an_episode(cfg):
    out, _, store, _ = _run(cfg, {**ALL_OK, "b.example": bad(), "c.example": bad()})
    assert out.verdict.at_risk and out.transition is Transition.STARTED
    assert store.saved.latest.episode.at_risk_since == T


def test_unavailable_list_still_completes_the_round(cfg):
    """FR-14: discovery failure never fails the round."""
    out, probe, _, _ = _run(cfg, ALL_OK, found=None, dir_error=DirectoryUnavailable("down"))
    assert out.tracker_error is False and "cand.example" not in probe.calls


def _unhealthy_history(host, rounds=4):
    results = [ProbeResult(t=T - 6 * H * i, host=host, role=Role.IN_USE, usable=False,
                           freshness=None, reason=Reason.TIMED_OUT, ms=None, newest=None)
               for i in range(1, rounds + 1)]
    return History(results=results, latest=EMPTY_LATEST)


def test_soft_warning_is_opened_through_the_tracker(cfg):
    out, _, store, tracker = _run(cfg, {**ALL_OK, "c.example": bad()},
                                  history=_unhealthy_history("c.example"))
    assert [c[:2] for c in tracker.calls] == [("open", "c.example")]
    assert "c.example" in store.saved.latest.warnings


def test_open_warning_is_updated_then_closed_on_recovery(cfg):
    """AC-2.3, AC-2.4."""
    tracker = FakeTracker(open_now={"c.example": T - 30 * H})
    _run(cfg, {**ALL_OK, "c.example": bad()}, history=_unhealthy_history("c.example"),
         tracker=tracker)
    assert tracker.calls[-1][:2] == ("update", "c.example")
    _run(cfg, ALL_OK, tracker=tracker)
    assert tracker.calls[-1] == ("close", "c.example")


def test_tracker_failure_still_saves_and_reports_check_broken(cfg):
    """Contract warning-tracker 3."""
    out, _, store, _ = _run(cfg, ALL_OK, tracker=FakeTracker(fail=True))
    assert out.tracker_error is True
    assert store.saved is not None and out.status["mirrors"]


def test_relay_state_and_sink_are_never_touched(cfg, monkeypatch):
    """FR-2: read-only with respect to delivery."""
    from tweet_relay.sinks import callmebot
    monkeypatch.setattr(callmebot.CallMeBotSink, "__init__",
                        lambda *a, **k: pytest.fail("the probe built a delivery sink"))
    _run(cfg, ALL_OK)
    assert not pathlib.Path(cfg.STATE_PATH).exists()
