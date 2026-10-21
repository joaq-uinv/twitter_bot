"""Delivery history. DD-1 is the decision this module exists to enforce."""
import json, logging, os, pathlib, pytest
from datetime import datetime, timezone
from tweet_relay.state import RelayState, load_state, save_state

H = "santtiagom_"


def sp(tmp_path):
    return tmp_path / "seen.json"


def test_round_trips(tmp_path):
    p = sp(tmp_path)
    s = RelayState(handle=H, seen_ids=[3, 2, 1], bootstrapped=True)
    save_state(p, s)
    back = load_state(p, H)
    assert back.seen_ids == [3, 2, 1] and back.bootstrapped is True


def test_membership_not_high_water_mark(tmp_path):
    """DD-1, the core of the design. A retweet carries the ORIGINAL post's id, which
    may be far older than ids already delivered. A watermark would suppress it."""
    s = RelayState(handle=H, seen_ids=[9_000_000_000])
    assert s.is_new(42), "an old id must still count as new if never delivered"
    s.mark_seen(42)
    assert not s.is_new(42)
    assert s.is_new(8_999_999_999)


def test_seen_set_is_bounded_and_keeps_newest(tmp_path):
    """DD-2: the file is on a mounted volume and must not grow forever."""
    s = RelayState(handle=H)
    for i in range(1, 501):
        s.mark_seen(i)
    assert len(s.seen_ids) == 300
    assert 500 in s.seen_ids and 1 not in s.seen_ids


def test_missing_file_is_a_fresh_unbootstrapped_state(tmp_path):
    s = load_state(sp(tmp_path), H)
    assert s.seen_ids == [] and s.bootstrapped is False


def test_handle_change_resets_history(tmp_path):
    """AC-5.1: retargeting must re-bootstrap, not replay another account's history."""
    p = sp(tmp_path)
    save_state(p, RelayState(handle="olduser", seen_ids=[1, 2, 3], bootstrapped=True))
    s = load_state(p, H)
    assert s.handle == H and s.seen_ids == [] and s.bootstrapped is False


@pytest.mark.parametrize("junk", [
    "{ not json",
    '{"handle": "santtiagom_", "seen_ids": "not-a-list"}',
    '{"seen_ids": [1,2,3]}',
    '[]',
    '{"handle": "santtiagom_", "seen_ids": [1, "two", null, 3]}',
    "",
])
def test_corrupt_state_recovers_without_crashing(tmp_path, junk):
    """E-16: corruption must never crash-loop the container."""
    p = sp(tmp_path)
    p.write_text(junk)
    s = load_state(p, H)
    assert s.handle == H
    assert s.bootstrapped is False, "must re-bootstrap so corruption cannot flood"


def test_write_is_atomic(tmp_path):
    """E-6: a crash mid-write must leave the previous file intact."""
    p = sp(tmp_path)
    save_state(p, RelayState(handle=H, seen_ids=[1], bootstrapped=True))
    original = p.read_text()
    with pytest.raises(RuntimeError):
        save_state(p, RelayState(handle=H, seen_ids=[2]), _fail_after_write=True)
    assert p.read_text() == original
    assert not [f for f in os.listdir(tmp_path) if f.endswith(".tmp")]


def test_concurrent_writers_do_not_lose_updates(tmp_path):
    """E-17: two checks on one volume must not clobber each other."""
    import threading
    p = sp(tmp_path)
    save_state(p, RelayState(handle=H, bootstrapped=True))
    errors = []

    def worker(base):
        try:
            for i in range(base, base + 20):
                with_lock_update(p, H, i)
        except Exception as e:      # pragma: no cover
            errors.append(e)

    from tweet_relay.state import with_lock_update
    ts = [threading.Thread(target=worker, args=(b,)) for b in (100, 200, 300)]
    [t.start() for t in ts]; [t.join() for t in ts]
    assert not errors
    final = load_state(p, H)
    assert len(final.seen_ids) == 60, f"lost updates: {len(final.seen_ids)}"


def test_last_success_survives(tmp_path):
    p = sp(tmp_path)
    now = datetime.now(timezone.utc)
    s = RelayState(handle=H); s.last_success = now
    save_state(p, s)
    assert load_state(p, H).last_success == now


def test_outage_flag_persists(tmp_path):
    """DD-6: edge-triggered notification needs this across restarts."""
    p = sp(tmp_path)
    s = RelayState(handle=H); s.outage_notified = True
    save_state(p, s)
    assert load_state(p, H).outage_notified is True


def test_unwritable_state_directory_gives_an_actionable_error(tmp_path):
    """Found in T028: a host-owned bind mount is unwritable by the container user,
    which produced a bare PermissionError traceback instead of a fix (§7)."""
    import os
    from tweet_relay.state import StateUnwritable, state_lock
    locked = tmp_path / "ro"
    locked.mkdir()
    os.chmod(locked, 0o500)
    try:
        with pytest.raises(StateUnwritable, match="HOST_UID"):
            with state_lock(locked / "seen.json"):
                pass
    finally:
        os.chmod(locked, 0o700)


# ---------- spec 003: pause, command offset, announcement, last check ----------

T0 = datetime(2026, 10, 21, 18, 0, tzinfo=timezone.utc)


def test_new_fields_round_trip(tmp_path):
    p = sp(tmp_path)
    s = RelayState(handle=H, seen_ids=[1], bootstrapped=True, paused_since=T0,
                   update_offset=1006, announced=True, last_check=(T0, 4))
    save_state(p, s)
    back = load_state(p, H)
    assert (back.paused_since, back.update_offset, back.announced, back.last_check) == \
        (T0, 1006, True, (T0, 4))


def test_a_pre_003_file_loads_with_defaults_and_keeps_every_id(tmp_path):
    """AC-2.1, DD-10: the real seen.json from main before 003. No migration step."""
    raw = (pathlib.Path(__file__).parent.parent / "fixtures" / "seen_pre003.json").read_text()
    p = sp(tmp_path)
    p.write_text(raw)
    back = load_state(p, H)
    assert back.seen_ids == json.loads(raw)["seen_ids"] and back.bootstrapped
    assert (back.paused_since, back.update_offset, back.announced, back.last_check) == \
        (None, 0, False, None)


@pytest.mark.parametrize("field,value,attr,default", [
    ("paused_since", "2026-10-21T18:00:00", "paused_since", None),        # naive
    ("paused_since", "yesterday", "paused_since", None),
    ("update_offset", "5", "update_offset", 0),
    ("update_offset", -1, "update_offset", 0),
    ("update_offset", True, "update_offset", 0),
    ("announced", "yes", "announced", False),
    ("last_check", {"at": "2026-10-21T18:00:00+00:00", "sent": -2}, "last_check", None),
    ("last_check", {"at": "nope", "sent": 1}, "last_check", None),
    ("last_check", [1, 2], "last_check", None),
])
def test_invalid_new_fields_fall_back_safely(tmp_path, caplog, field, value, attr, default):
    """data-model.md: each bad value takes its safe default and is logged loudly."""
    p = sp(tmp_path)
    save_state(p, RelayState(handle=H, seen_ids=[7], bootstrapped=True))
    raw = json.loads(p.read_text())
    raw[field] = value
    p.write_text(json.dumps(raw))
    with caplog.at_level(logging.ERROR):
        back = load_state(p, H)
    assert getattr(back, attr) == default
    assert back.seen_ids == [7]
    assert any(r.levelno == logging.ERROR for r in caplog.records)


def test_handle_change_resets_the_new_fields_too(tmp_path):
    p = sp(tmp_path)
    save_state(p, RelayState(handle="other", bootstrapped=True, paused_since=T0,
                             update_offset=9, announced=True, last_check=(T0, 1)))
    back = load_state(p, H)
    assert (back.paused_since, back.update_offset, back.announced, back.last_check) == \
        (None, 0, False, None)
