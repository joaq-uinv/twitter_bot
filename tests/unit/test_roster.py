"""build_roster: which mirrors a round probes, and in what role (spec 002 FR-13..15,
AC-5.4, E-12, E-13, E-17, D-2; plan DD-11)."""
from datetime import datetime, timedelta, timezone

from tweet_relay.mirrors.directory import DirectoryRead
from tweet_relay.mirrors.models import ProbeResult, Reason, Role
from tweet_relay.mirrors.roster import CANDIDATE_CAP, DiscoveryState, build_roster

T = datetime(2026, 10, 11, 12, 0, tzinfo=timezone.utc)
IN_USE = ["https://nitter.kareem.one", "https://nitter.pp.ua"]
EMPTY = DiscoveryState(last_ok=None, accepted=0, rejected=0, candidates=[])


def seen(host, role=Role.IN_USE, t=T - timedelta(days=1)):
    return ProbeResult(t=t, host=host, role=role, usable=False, freshness=None,
                       reason=Reason.TIMED_OUT, ms=None, newest=None)


def roles(entries):
    return {h: r for h, r in entries}


def test_in_use_come_first_then_discovered():
    entries, _ = build_roster(IN_USE, [], DirectoryRead(["c1.example", "c2.example"], 2, 0), EMPTY, T)
    assert entries == [("nitter.kareem.one", Role.IN_USE), ("nitter.pp.ua", Role.IN_USE),
                       ("c1.example", Role.CANDIDATE), ("c2.example", Role.CANDIDATE)]


def test_in_use_mirrors_are_never_candidates():
    """E-12: the list also names mirrors we use; they are probed once, as in use."""
    entries, _ = build_roster(IN_USE, [], DirectoryRead(["nitter.pp.ua", "c.example"], 2, 0), EMPTY, T)
    assert [h for h, _ in entries].count("nitter.pp.ua") == 1
    assert roles(entries)["nitter.pp.ua"] is Role.IN_USE


def test_removed_mirror_comes_back_as_former_ahead_of_discovered():
    """E-17, D-2: probed even if the list does not name it, and outranks discovery."""
    history = [seen("nitter.netbub.com"), seen("nitter.kareem.one")]
    entries, _ = build_roster(IN_USE, history, DirectoryRead(["c.example"], 1, 0), EMPTY, T)
    hosts = [h for h, _ in entries]
    assert roles(entries)["nitter.netbub.com"] is Role.FORMER
    assert hosts.index("nitter.netbub.com") < hosts.index("c.example")


def test_candidates_are_capped_with_former_first():
    history = [seen(f"old{i}.example") for i in range(3)]
    found = DirectoryRead([f"new{i}.example" for i in range(40)], 40, 0)
    entries, _ = build_roster(IN_USE, history, found, EMPTY, T)
    extra = [(h, r) for h, r in entries if r is not Role.IN_USE]
    assert len(extra) == CANDIDATE_CAP == 25
    assert [r for _, r in extra[:3]] == [Role.FORMER] * 3


def test_successful_discovery_is_recorded():
    _, disc = build_roster(IN_USE, [], DirectoryRead(["c.example"], 1, 4), EMPTY, T)
    assert disc == DiscoveryState(last_ok=T, accepted=1, rejected=4, candidates=["c.example"])


def test_unavailable_list_keeps_last_good_candidates():
    """FR-14, E-13: discovery staleness is shown, the round is not failed."""
    prev = DiscoveryState(last_ok=T - timedelta(days=3), accepted=2, rejected=1,
                          candidates=["c1.example", "c2.example"])
    entries, disc = build_roster(IN_USE, [], None, prev, T)
    assert disc == prev
    assert [h for h, r in entries if r is Role.CANDIDATE] == ["c1.example", "c2.example"]


def test_relay_configuration_is_never_modified():
    """FR-15, AC-5.4: discovery suggests, it never acts."""
    in_use = list(IN_USE)
    build_roster(in_use, [], DirectoryRead(["c.example"], 1, 0), EMPTY, T)
    assert in_use == IN_USE
