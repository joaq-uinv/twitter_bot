"""Pipeline behaviour added by spec 003: cards, the chat check, the switch
announcement, commands, pause and /status. Over doubles only (§5)."""
import json
from datetime import datetime, timedelta, timezone

import pytest

from tests.doubles import (OPERATOR, FakeSource, RecordingSink, ScriptedInbox, batch,
                           msg, tweet)
from tweet_relay.models import InboxUnavailable, TweetKind
from tweet_relay.pipeline import Pipeline
from tweet_relay.state import RelayState, load_state, save_state

H = "santtiagom_"
NOW = datetime(2026, 10, 21, 18, 0, tzinfo=timezone.utc)


def pipe(config, source, sink, inbox=None, **kw):
    return Pipeline(config, source, sink, inbox=inbox, operator_chat_id=OPERATOR,
                    clock=lambda: NOW, **kw)


def ready(config, **fields):
    """A state as it is today on main: bootstrapped, announced unless overridden."""
    base = dict(handle=H, seen_ids=[1], bootstrapped=True, announced=True)
    save_state(config.STATE_PATH, RelayState(**{**base, **fields}))


def state(config):
    return load_state(config.STATE_PATH, H)


# ---------- T024: cards (FR-2, AC-1.2) and posts without text (AC-7.2) ----------

def test_every_post_carries_its_card_url_and_notices_do_not(config):
    ready(config)
    posts = [tweet(i, minutes=i) for i in range(2, 15)]          # 13 new: 10 + withheld
    sink = RecordingSink()
    pipe(config, FakeSource([tweet(1)] + posts), sink).run_once()
    assert sink.previews[:10] == [t.preview_url for t in posts[:10]]
    assert "more" in sink.sent[10] and sink.previews[10] is None


def test_a_post_without_text_is_delivered_once(config):
    from tweet_relay.models import Tweet
    ready(config)
    bare = Tweet(id=5, author=H, text="", published_at=NOW, kind=TweetKind.ORIGINAL)
    sink = RecordingSink()
    for _ in range(2):
        pipe(config, FakeSource([bare]), sink).run_once()
    assert sink.sent == [f"New post from @{H} (no text)\n\n{bare.url}"]


# ---------- T026: private chat check (D-4) and switch announcement (D-2) ----------

def test_nothing_is_sent_to_a_chat_that_is_not_private(config, caplog):
    """E-14: the run fails loudly and names no id."""
    ready(config)
    sink = RecordingSink(private=False)
    result = pipe(config, FakeSource([tweet(1), tweet(2, minutes=2)]), sink).run_once()
    assert sink.sent == [] and result.failed == 1
    assert "not a private chat" in caplog.text and str(OPERATOR) not in caplog.text
    assert state(config).is_new(2), "an unsent post stays pending"


def test_the_chat_is_checked_once_per_run(config):
    ready(config)
    sink = RecordingSink()
    pipe(config, FakeSource([tweet(i, minutes=i) for i in range(1, 6)]), sink).run_once()
    assert sink.chat_checks == 1


def test_a_run_with_nothing_to_send_makes_no_chat_check(config):
    ready(config)
    sink = RecordingSink()
    pipe(config, FakeSource([tweet(1)]), sink).run_once()
    assert sink.chat_checks == 0


def test_the_switch_is_announced_once_before_the_stuck_posts(config):
    """AC-2.2, AC-2.3, D-2: the state on main today has no `announced` field."""
    ready(config, announced=False)
    src = FakeSource([tweet(1), tweet(2, minutes=2), tweet(3, minutes=3)])
    sink = RecordingSink()
    pipe(config, src, sink).run_once()
    assert "now delivers here" in sink.sent[0] and H in sink.sent[0]
    assert [s.splitlines()[0] for s in sink.sent[1:]] == ["post 2", "post 3"]
    sink.sent.clear()
    pipe(config, src, sink).run_once()
    assert sink.sent == []


def test_a_failed_announcement_is_retried_next_check(config):
    ready(config, announced=False)
    sink = RecordingSink(fail_on={1})
    result = pipe(config, FakeSource([tweet(1)]), sink).run_once()
    assert result.failed == 1 and not state(config).announced
    pipe(config, FakeSource([tweet(1)]), sink).run_once()
    assert "now delivers here" in sink.sent[0] and state(config).announced


def test_a_fresh_bootstrap_is_its_own_announcement(config):
    sink = RecordingSink()
    pipe(config, FakeSource([tweet(1)]), sink).run_once()
    assert len(sink.sent) == 1 and "live" in sink.sent[0].lower()
    assert state(config).announced


def test_announcement_still_comes_while_paused(config):
    """E-18: stuck posts wait for /resume."""
    ready(config, announced=False, paused_since=NOW - timedelta(hours=1))
    sink = RecordingSink()
    pipe(config, FakeSource([tweet(1), tweet(2, minutes=2)]), sink).run_once()
    assert len(sink.sent) == 1 and "now delivers here" in sink.sent[0]
    assert state(config).is_new(2)


# ---------- T028: commands (FR-6..FR-10, US-6, DD-5, DD-6) ----------

STRANGER = 999888777


def test_pause_is_saved_before_the_reply_is_sent(config):
    """DD-5, FR-9: a failed reply loses the reply, never re-applies the command."""
    ready(config, update_offset=100)
    sink = RecordingSink(fail_on={1})
    result = pipe(config, FakeSource([tweet(1)]), sink,
                  ScriptedInbox(batch(msg(100, "/pause")))).run_once()
    s = state(config)
    assert s.paused_since == NOW and s.update_offset == 101 and result.failed == 1


def test_a_strangers_command_has_no_effect(config, caplog):
    """AC-6.1, E-4: no reply, no state change, nothing logged about it."""
    ready(config, update_offset=50)
    sink = RecordingSink()
    with caplog.at_level("DEBUG"):
        pipe(config, FakeSource([tweet(1)]), sink,
             ScriptedInbox(batch(msg(50, "/pause SECRETMARK", chat_id=STRANGER)))).run_once()
    s = state(config)
    assert sink.sent == [] and s.paused_since is None and s.update_offset == 51
    assert "SECRETMARK" not in caplog.text and str(STRANGER) not in caplog.text


def test_the_operators_id_in_a_group_is_not_the_operator(config):
    """E-5: identity is the private chat, never a claim."""
    ready(config)
    sink = RecordingSink()
    pipe(config, FakeSource([tweet(1)]), sink,
         ScriptedInbox(batch(msg(5, "/pause", chat_type="group")))).run_once()
    assert sink.sent == [] and state(config).paused_since is None


def test_strangers_do_not_hide_the_operators_commands(config):
    """AC-6.2."""
    ready(config)
    sink = RecordingSink()
    pipe(config, FakeSource([tweet(1)]), sink, ScriptedInbox(batch(
        msg(1, "/pause", chat_id=STRANGER), msg(2, "/help"), msg(3, "hi", chat_id=STRANGER),
    ))).run_once()
    assert len(sink.sent) == 1 and "/status" in sink.sent[0]
    assert state(config).update_offset == 4


@pytest.mark.parametrize("texts,paused", [
    (["/pause", "/resume"], False),     # E-1
    (["/resume", "/pause"], True),      # E-2
])
def test_commands_apply_in_the_order_sent(config, texts, paused):
    ready(config, seen_ids=[1])
    sink = RecordingSink()
    src = FakeSource([tweet(1), tweet(2, minutes=2)])
    result = pipe(config, src, sink, ScriptedInbox(batch(
        *[msg(i + 1, t) for i, t in enumerate(texts)]))).run_once()
    assert (state(config).paused_since is not None) is paused
    replies = [s for s in sink.sent if not s.startswith("post")]
    assert len(replies) == 2
    assert result.paused is paused
    assert any(s.startswith("post 2") for s in sink.sent) is (not paused)


def test_at_most_twenty_commands_per_check(config):
    """DD-6, FR-10, E-3: the rest wait for the next check."""
    ready(config, update_offset=1)
    sink = RecordingSink()
    inbox = ScriptedInbox(batch(*[msg(i, "/help") for i in range(1, 26)]))
    pipe(config, FakeSource([tweet(1)]), sink, inbox).run_once()
    assert len(sink.sent) == 20 and state(config).update_offset == 21
    pipe(config, FakeSource([tweet(1)]), sink,
         ScriptedInbox(batch(*[msg(i, "/help") for i in range(21, 26)]))).run_once()
    assert len(sink.sent) == 25 and state(config).update_offset == 26


def test_an_unreadable_inbox_fails_the_run_but_posts_still_go(config):
    ready(config)
    sink = RecordingSink()
    result = pipe(config, FakeSource([tweet(1), tweet(2, minutes=2)]), sink,
                  ScriptedInbox(error=InboxUnavailable("getUpdates: HTTP 502"))).run_once()
    assert result.failed == 1 and sink.sent[0].startswith("post 2")


def test_a_handled_command_is_not_handled_again(config):
    """FR-9, E-8: the same updates read twice (a crash after saving) act once."""
    ready(config)
    sink = RecordingSink()
    same = batch(msg(7, "/help"))
    pipe(config, FakeSource([tweet(1)]), sink, ScriptedInbox(same)).run_once()
    inbox = ScriptedInbox(same)
    pipe(config, FakeSource([tweet(1)]), sink, inbox).run_once()
    assert len(sink.sent) == 1 and inbox.offsets == [8]


def test_malformed_updates_still_move_the_offset(config):
    ready(config, update_offset=10)
    pipe(config, FakeSource([tweet(1)]), RecordingSink(),
         ScriptedInbox(batch(next_offset=14))).run_once()
    assert state(config).update_offset == 14


def test_an_unknown_command_gets_one_pointer_to_help(config):
    """AC-5.2, E-6: never echoed."""
    ready(config)
    sink = RecordingSink()
    pipe(config, FakeSource([tweet(1)]), sink,
         ScriptedInbox(batch(msg(1, "rm -rf ECHOMARK")))).run_once()
    assert len(sink.sent) == 1 and "/help" in sink.sent[0] and "ECHOMARK" not in sink.sent[0]


# ---------- T030: pause (US-4, FR-13..FR-15) ----------

def test_paused_checks_deliver_nothing_and_mark_nothing(config):
    """AC-4.1, AC-4.2, FR-13, FR-14: no posts, no withheld notice, across checks."""
    ready(config, paused_since=NOW - timedelta(hours=2))
    src = FakeSource([tweet(1)] + [tweet(i, minutes=i) for i in range(2, 15)])
    sink = RecordingSink()
    for _ in range(3):
        result = pipe(config, src, sink).run_once()
        assert result.paused and result.sent == 0 and not result.failed
    assert sink.sent == [] and state(config).seen_ids == [1]


def test_pause_never_hides_an_outage(config):
    """AC-4.3."""
    ready(config, paused_since=NOW - timedelta(hours=2))
    sink = RecordingSink()
    result = pipe(config, FakeSource(error="all mirrors failed"), sink).run_once()
    assert result.outage and result.paused
    assert len(sink.sent) == 1 and "cannot reach" in sink.sent[0]


def test_resume_reports_the_wait_and_drains_it(config):
    """AC-4.4: 13 waiting, 10 now oldest first, 3 on the next check."""
    ready(config, paused_since=NOW - timedelta(hours=1))
    src = FakeSource([tweet(1)] + [tweet(i, minutes=i) for i in range(2, 15)])
    sink = RecordingSink()
    pipe(config, src, sink, ScriptedInbox(batch(msg(1, "/resume")))).run_once()
    assert sink.sent[0] == "▶️ Resumed. 13 posts waiting; up to 10 arrive now."
    assert [s.splitlines()[0] for s in sink.sent[1:11]] == [f"post {i}" for i in range(2, 12)]
    assert "3 more" in sink.sent[11]
    sink.sent.clear()
    pipe(config, src, sink).run_once()
    assert [s.splitlines()[0] for s in sink.sent] == ["post 12", "post 13", "post 14"]


@pytest.mark.parametrize("pause_vs_oldest_listed,warned", [(-60, True), (1, False)])
def test_resume_warns_only_when_early_posts_may_be_gone(config, pause_vs_oldest_listed, warned):
    """AC-4.5, E-15: warn when the pause began before the oldest post still listed
    (minutes; the oldest listed post in the doubles is 2026-09-15 12:00)."""
    ready(config, paused_since=datetime(2026, 9, 15, 12, tzinfo=timezone.utc)
          + timedelta(minutes=pause_vs_oldest_listed))
    sink = RecordingSink()
    pipe(config, FakeSource([tweet(1), tweet(2, minutes=2)]), sink,
         ScriptedInbox(batch(msg(1, "/resume")))).run_once()
    assert ("may no longer be retrievable" in sink.sent[0]) is warned


def test_pause_twice_and_resume_while_running_say_already(config):
    """AC-4.6."""
    since = NOW - timedelta(hours=3)
    ready(config, paused_since=since)
    sink = RecordingSink()
    pipe(config, FakeSource([tweet(1)]), sink, ScriptedInbox(batch(
        msg(1, "/pause"), msg(2, "/resume"), msg(3, "/resume")))).run_once()
    assert sink.sent[0] == "Already paused since 2026-10-21 15:00 UTC."
    assert sink.sent[1].startswith("▶️ Resumed.") and sink.sent[2] == "Already running."
    assert state(config).paused_since is None


# ---------- T032: /status inputs (AC-3.1..AC-3.3, E-17) ----------

def mirror_file(tmp_path, healthy=3, total=4):
    from tweet_relay.mirrors.history import EMPTY_LATEST, DirHistoryStore, History
    from dataclasses import replace
    d = tmp_path / "mirror"
    latest = replace(EMPTY_LATEST, round_t=NOW, in_use_healthy=healthy, in_use_total=total)
    DirHistoryStore(d).save(History(results=[], latest=latest), NOW)
    return str(d / "latest.json")


def test_each_completed_check_records_what_it_delivered(config):
    ready(config)
    pipe(config, FakeSource([tweet(1), tweet(2, minutes=2), tweet(3, minutes=3)]),
         RecordingSink()).run_once()
    assert state(config).last_check == (NOW, 2)


def test_status_reports_the_previous_check_waiting_pause_and_mirrors(config, tmp_path):
    ready(config, last_check=(NOW - timedelta(minutes=15), 4))
    sink = RecordingSink()
    pipe(config, FakeSource([tweet(1), tweet(2, minutes=2)]), sink,
         ScriptedInbox(batch(msg(1, "/status"))),
         mirror_latest_path=mirror_file(tmp_path),
         status_page_url="https://example.test/page/").run_once()
    reply = sink.sent[0]
    assert "2026-10-21 17:45 UTC, delivered 4" in reply
    assert "Waiting: 1" in reply and "running" in reply
    assert "3 of 4 healthy" in reply and "https://example.test/page/" in reply


@pytest.mark.parametrize("content", [None, "{broken", json.dumps({"round": "x"})])
def test_status_without_usable_mirror_data(config, tmp_path, content):
    """AC-3.2: missing or invalid file says "not available"."""
    path = tmp_path / "latest.json"
    if content is not None:
        path.write_text(content)
    ready(config)
    sink = RecordingSink()
    pipe(config, FakeSource([tweet(1)]), sink, ScriptedInbox(batch(msg(1, "/status"))),
         mirror_latest_path=str(path)).run_once()
    assert "health check not available" in sink.sent[0]


def test_status_is_answered_during_an_outage(config):
    """AC-3.3."""
    ready(config, outage_notified=True)
    sink = RecordingSink()
    pipe(config, FakeSource(error="down"), sink,
         ScriptedInbox(batch(msg(1, "/status")))).run_once()
    assert "unknown, sources unavailable" in sink.sent[0]


def test_status_before_any_check_says_none_yet(config):
    """E-17."""
    ready(config)
    sink = RecordingSink()
    pipe(config, FakeSource([tweet(1)]), sink, ScriptedInbox(batch(msg(1, "/status")))).run_once()
    assert "Last check: none yet" in sink.sent[0]


# ---------- T035: two checks at once (E-10, FR-9) ----------

def test_overlapping_checks_handle_each_command_once(config):
    import threading
    ready(config)
    sinks = [RecordingSink(), RecordingSink()]
    same = batch(msg(1, "/pause"), msg(2, "/help"))
    runs = [pipe(config, FakeSource([tweet(1)]), sink, ScriptedInbox(same)) for sink in sinks]
    threads = [threading.Thread(target=r.run_once) for r in runs]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    replies = sinks[0].sent + sinks[1].sent
    assert len(replies) == 2 and replies[0].startswith("⏸ Paused")
    s = state(config)
    assert s.paused_since == NOW and s.update_offset == 3
