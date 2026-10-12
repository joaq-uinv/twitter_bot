"""DirHistoryStore: history.jsonl + latest.json in a directory (spec 002 FR-18,
AC-4.3, E-20, E-21; contract history-store.md)."""
import json
from datetime import datetime, timedelta, timezone

import pytest

from tweet_relay.mirrors import history as history_module
from tweet_relay.mirrors.health import EpisodeState
from tweet_relay.mirrors.history import EMPTY_LATEST, DirHistoryStore, History, Latest
from tweet_relay.mirrors.models import Freshness, ProbeResult, Reason, Role
from tweet_relay.mirrors.roster import DiscoveryState

T = datetime(2026, 10, 11, 12, 0, tzinfo=timezone.utc)


def good(t, host="nitter.pp.ua"):
    return ProbeResult(t=t, host=host, role=Role.IN_USE, usable=True, freshness=Freshness.FRESH,
                       reason=None, ms=120, newest=t - timedelta(hours=1))


def bad(t, host="nitter.netbub.com"):
    return ProbeResult(t=t, host=host, role=Role.CANDIDATE, usable=False, freshness=None,
                       reason=Reason.SENT_ELSEWHERE, ms=40, newest=None)


LATEST = Latest(round_t=T, reference=T - timedelta(hours=1), in_use_healthy=1, in_use_total=1,
                at_risk=True, episode=EpisodeState(at_risk_since=T - timedelta(hours=6)),
                discovery=DiscoveryState(last_ok=T, accepted=5, rejected=1, candidates=["c.example"]),
                warnings={"nitter.kareem.one": T - timedelta(days=1)})


def test_round_trip(tmp_path):
    store = DirHistoryStore(tmp_path)
    store.save(History(results=[good(T), bad(T)], latest=LATEST), now=T)
    loaded = store.load()
    assert loaded.results == [good(T), bad(T)]
    assert loaded.latest == LATEST and loaded.corrupt is False


def test_missing_directory_is_an_empty_history(tmp_path):
    loaded = DirHistoryStore(tmp_path / "nope").load()
    assert loaded.results == [] and loaded.latest == EMPTY_LATEST and not loaded.corrupt


def test_results_older_than_90_days_are_pruned_on_save(tmp_path):
    """FR-18, AC-4.3."""
    store = DirHistoryStore(tmp_path)
    old, edge = T - timedelta(days=90, seconds=1), T - timedelta(days=90)
    store.save(History(results=[good(old), good(edge), good(T)], latest=LATEST), now=T)
    assert [r.t for r in store.load().results] == [edge, T]


def test_invalid_lines_are_dropped(tmp_path):
    store = DirHistoryStore(tmp_path)
    store.save(History(results=[good(T - timedelta(hours=6)), good(T)], latest=LATEST), now=T)
    path = tmp_path / "history.jsonl"
    lines = path.read_text().splitlines()
    path.write_text("\n".join([lines[0], '{"host": "<script>"}', lines[1]]) + "\n")
    loaded = store.load()
    assert len(loaded.results) == 2 and loaded.corrupt is False


@pytest.mark.parametrize("bad_line", [
    "not json", "[]", '{"t": "2026-10-11T12:00:00+00:00"}',
    json.dumps({"t": "2026-10-11T12:00:00+00:00", "host": "bad host!", "role": "in_use",
                "usable": False, "freshness": None, "reason": "timed_out", "ms": None,
                "newest": None}),
    json.dumps({"t": "2026-10-11T12:00:00+00:00", "host": "a.example", "role": "admin",
                "usable": False, "freshness": None, "reason": "timed_out", "ms": None,
                "newest": None}),
])
def test_each_kind_of_invalid_line_is_rejected(tmp_path, bad_line):
    (tmp_path / "history.jsonl").write_text(json.dumps(history_module.result_to_json(good(T))) +
                                            "\n" + bad_line + "\n" +
                                            json.dumps(history_module.result_to_json(good(T))) + "\n")
    assert len(DirHistoryStore(tmp_path).load().results) == 2


def test_mostly_garbage_file_is_treated_as_corrupt(tmp_path):
    """E-20: history restarts and the caller logs loudly."""
    (tmp_path / "history.jsonl").write_text("x\ny\nz\n" +
                                            json.dumps(history_module.result_to_json(good(T))) + "\n")
    loaded = DirHistoryStore(tmp_path).load()
    assert loaded.results == [] and loaded.corrupt is True


def test_unreadable_latest_is_empty_latest(tmp_path):
    (tmp_path / "latest.json").write_text("{broken")
    assert DirHistoryStore(tmp_path).load().latest == EMPTY_LATEST


def test_a_crash_mid_save_leaves_the_old_files_intact(tmp_path, monkeypatch):
    """E-21: written to a temporary file, then renamed."""
    store = DirHistoryStore(tmp_path)
    store.save(History(results=[good(T)], latest=LATEST), now=T)
    before = (tmp_path / "history.jsonl").read_bytes()

    def boom(*a, **kw):
        raise OSError("killed")
    monkeypatch.setattr(history_module.os, "replace", boom)
    with pytest.raises(OSError):
        store.save(History(results=[good(T), bad(T)], latest=LATEST), now=T)
    assert (tmp_path / "history.jsonl").read_bytes() == before


def test_latest_with_non_boolean_at_risk_is_rejected(tmp_path):
    store = DirHistoryStore(tmp_path)
    store.save(History(results=[good(T)], latest=LATEST), now=T)
    path = tmp_path / "latest.json"
    path.write_text(path.read_text().replace('"at_risk": true', '"at_risk": "yes"'))
    assert store.load().latest == EMPTY_LATEST
