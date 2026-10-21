"""Nothing a third party wrote is ever published (spec 002 FR-16, E-14).

Every byte a mirror or the community list can control is seeded with a unique marker.
A full round runs through the real probe, directory and history store, and no marker
may appear in history.jsonl, latest.json, status.json, the warning tracker's calls,
the command output or the logs (the Actions log of a public repo is public too).
"""
import json
import logging
import pathlib
import socket

import httpx
import pytest
import respx

from tests.doubles import FakeTracker
from tweet_relay import cli
from tweet_relay import config as config_module
from tweet_relay.mirrors.directory import StatusD420Directory

FIX = pathlib.Path(__file__).parent.parent / "fixtures" / "mirrors"
MARK = "ZZ-MARKER-"


def markers_in(text: str) -> list[str]:
    up = text.upper().replace(f"{MARK}8.INTERNAL-TEST", "")   # a validated hostname: allowed (FR-16)
    return sorted({up[i:i + len(MARK) + 1] for i in range(len(up)) if up.startswith(MARK, i)})


def test_the_detector_finds_a_planted_marker():
    """The leaky stub: proves this file's check can fail at all."""
    assert markers_in(json.dumps({"mirrors": [{"host": f"x{MARK}1"}]})) == [f"{MARK}1"]


@pytest.fixture
def hostile_world(monkeypatch, tmp_path):
    def dns(host, port, *a, **kw):
        ip = "10.0.0.9" if host.endswith(".internal-test") else "93.184.216.34"
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, port))]
    monkeypatch.setattr(config_module.socket, "getaddrinfo", dns)
    monkeypatch.setenv("X_PROFILE_URL", "@santtiagom_")
    monkeypatch.setenv("NITTER_INSTANCES", "https://m1.example,https://m2.example,https://m3.example")

    feed = (FIX / "feed_pp_ua.xml").read_bytes()
    feed = feed.replace(b"<description>", f"<description>{MARK}1 ".encode())
    feed = feed.replace(b"santi / @santtiagom_", f"santi / @santtiagom_ {MARK}2".encode(), 1)
    feed = feed.replace(b"://nitter.pp.ua/", f"://{MARK.lower()}b.example/".encode())
    respx.get("https://m1.example/santtiagom_/rss").mock(httpx.Response(200, content=feed))
    respx.get("https://m2.example/santtiagom_/rss").mock(
        httpx.Response(403, text=f"<h1>{MARK}3 forbidden</h1>"))
    respx.get("https://m3.example/santtiagom_/rss").mock(
        httpx.Response(307, headers={"location": f"https://{MARK}4.example/"}))
    respx.get("https://cand.example/santtiagom_/rss").mock(
        httpx.Response(200, text=f"<html><title>{MARK}5</title></html>"))
    respx.get(StatusD420Directory.URL).mock(httpx.Response(200, json={"hosts": [
        {"url": "https://cand.example", "domain": "cand.example", "country": f"{MARK}6",
         "version": f"{MARK}7"},
        {"url": f"https://{MARK.lower()}8.internal-test", "domain": f"{MARK.lower()}8.internal-test"},
        {"url": "https://m1.example", "domain": "m1.example", "note": f"{MARK}9"},
    ], "last_update": f"{MARK}A"}))
    return tmp_path


@respx.mock
def test_a_full_round_publishes_no_third_party_text(hostile_world, monkeypatch, capsys, caplog):
    tracker = FakeTracker()
    monkeypatch.setattr(cli, "_warning_tracker", lambda: tracker)
    data, site = hostile_world / "data", hostile_world / "site"
    with caplog.at_level(logging.DEBUG, logger="tweet_relay.mirrors"):
        with caplog.at_level(logging.INFO):
            code = cli.main(["probe-mirrors", "--data", str(data), "--site-out", str(site)])
    assert code in (0, 3)

    published = {
        "history.jsonl": (data / "history.jsonl").read_text(),
        "latest.json": (data / "latest.json").read_text(),
        "status.json": (site / "status.json").read_text(),
        "tracker": repr(tracker.calls),
        "stdout": capsys.readouterr().out,
    }
    for name, text in published.items():
        assert markers_in(text) == [], f"third-party text reached {name}"
    # Logs at INFO and above reach the public Actions log; DEBUG stays local.
    public_log = "\n".join(r.getMessage() for r in caplog.records if r.levelno >= logging.INFO)
    assert markers_in(public_log) == []

    status = json.loads(published["status.json"])
    reasons = {m["host"]: m["reason"] for m in status["mirrors"]}
    assert reasons == {"m1.example": None, "m2.example": "refused_answer",
                       "m3.example": "sent_elsewhere", "cand.example": "malformed_content",
                       f"{MARK.lower()}8.internal-test": "refused_address"}
