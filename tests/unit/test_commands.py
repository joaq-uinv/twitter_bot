"""Operator commands (spec 003 US-3..US-5, FR-8, D-3, plan DD-12)."""
import inspect
import time
from datetime import datetime, timedelta, timezone

import pytest

from tweet_relay import commands as cmd
from tweet_relay.commands import Command, parse


@pytest.mark.parametrize("text,expected", [
    ("/status", Command.STATUS),
    ("/STATUS", Command.STATUS),
    ("/Pause now", Command.PAUSE),          # D-3: case and extra words ignored
    ("/resume@my_relay_bot", Command.RESUME),  # suffix added when tapped from the menu
    ("/help", Command.HELP),
    ("/pause\nplease", Command.PAUSE),
])
def test_known_commands_are_recognised(text, expected):
    assert parse(text) is expected


@pytest.mark.parametrize("text", [
    "/statusx", "status", "", " /pause", "/", "/start", "hi /pause",
    "\x00/pause", "/pаuse",                  # Cyrillic а: looks the same, is not
    "x" * 100_000,
])
def test_anything_else_is_unknown(text):
    assert parse(text) is Command.UNKNOWN


def test_only_the_start_of_a_huge_message_is_examined():
    """E-6: a hostile message cannot make parsing slow."""
    big = "/status " + "a" * 1_000_000
    start = time.perf_counter()
    assert parse(big) is Command.STATUS
    assert time.perf_counter() - start < 0.05


# ---------- replies (data-model.md "Replies") ----------

T = datetime(2026, 10, 21, 18, 30, tzinfo=timezone.utc)
PAGE = "https://joaq-uinv.github.io/twitter_bot/"


def status(**kw):
    base = dict(last_check=(T, 3), waiting=2, paused_since=None, mirrors=(3, 4), page_url=PAGE)
    return cmd.render_status(**{**base, **kw})


def test_status_reports_every_part():
    """AC-3.1."""
    out = status()
    assert "2026-10-21 18:30 UTC" in out and "delivered 3" in out
    assert "Waiting: 2" in out and "running" in out
    assert "3 of 4" in out and PAGE in out


def test_status_when_nothing_has_happened_yet():
    """E-17."""
    assert "none yet" in status(last_check=None)


def test_status_without_mirror_data():
    """AC-3.2: say so instead of showing a number."""
    out = status(mirrors=None)
    assert "not available" in out and " of " not in out.split("Mirrors:")[1].split(".")[0]


def test_status_during_an_outage():
    """AC-3.3."""
    assert "sources unavailable" in status(waiting=None)


def test_status_while_paused():
    assert "paused since 2026-10-21 12:00 UTC" in status(paused_since=T - timedelta(hours=6, minutes=30))


def test_pause_replies():
    """AC-4.1, AC-4.6."""
    assert cmd.render_pause(None) == "⏸ Paused. Send /resume to start again."
    assert cmd.render_pause(T) == "Already paused since 2026-10-21 18:30 UTC."


def test_resume_reply_states_what_will_arrive():
    """AC-4.4."""
    out = cmd.render_resume(T - timedelta(hours=1), waiting=13, cap=10,
                            oldest_listed=T - timedelta(days=2))
    assert out == "▶️ Resumed. 13 posts waiting; up to 10 arrive now."


def test_resume_warns_when_early_posts_may_have_aged_out():
    """AC-4.5, E-15: the pause began before the oldest post still listed."""
    out = cmd.render_resume(T - timedelta(days=3), waiting=20, cap=10,
                            oldest_listed=T - timedelta(days=1))
    assert "may no longer be retrievable" in out


def test_resume_when_running_and_when_sources_are_down():
    assert cmd.render_resume(None, waiting=5, cap=10, oldest_listed=None) == "Already running."
    out = cmd.render_resume(T, waiting=None, cap=10, oldest_listed=None)
    assert out.startswith("▶️ Resumed.") and "sources are unavailable" in out


def test_help_lists_the_commands_and_the_delay():
    """AC-5.1."""
    out = cmd.render_help()
    for c in ("/status", "/pause", "/resume", "/help"):
        assert c in out
    assert "next check" in out


def test_unknown_reply_points_to_help():
    """AC-5.2."""
    assert "/help" in cmd.render_unknown()


def test_no_reply_can_carry_operator_text():
    """FR-11: replies are fixed templates. No builder takes free text, only numbers,
    times, our own page URL, or nothing."""
    builders = [cmd.render_status, cmd.render_pause, cmd.render_resume,
                cmd.render_help, cmd.render_unknown]
    for b in builders:
        for name, p in inspect.signature(b).parameters.items():
            assert p.annotation != "str" or name == "page_url", (b.__name__, name)
