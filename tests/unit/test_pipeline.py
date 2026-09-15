"""End-to-end pipeline behaviour over fake adapters."""
import pytest
from tweet_relay.models import TweetKind
from tweet_relay.pipeline import Pipeline
from tweet_relay.state import load_state
from tests.doubles import FakeSource, RecordingSink, tweet

H = "santtiagom_"


def build(config, source, sink):
    return Pipeline(config, source, sink)


def bootstrapped(config, source, sink):
    """Run once to get past bootstrap, then reset the sink."""
    Pipeline(config, source, sink).run_once()
    sink.sent.clear(); sink.attempts = 0


# ---------- bootstrap (US-3) ----------

def test_first_run_sends_only_the_liveness_message(config):
    src = FakeSource([tweet(i, minutes=i) for i in range(1, 20)])
    sink = RecordingSink()
    result = build(config, src, sink).run_once()
    assert result.bootstrapped is True
    assert len(sink.sent) == 1                      # AC-3.2
    assert "live" in sink.sent[0].lower()
    assert "post 1" not in sink.sent[0]             # AC-3.1: no history replayed


def test_first_run_marks_existing_posts_seen(config):
    src = FakeSource([tweet(i, minutes=i) for i in range(1, 20)])
    build(config, src, RecordingSink()).run_once()
    state = load_state(config.STATE_PATH, H)
    assert len(state.seen_ids) == 19 and state.bootstrapped is True


def test_restart_sends_no_liveness_message(config):
    """AC-3.3/D-2: once per account, not once per start."""
    src = FakeSource([tweet(1, minutes=1)])
    sink = RecordingSink()
    bootstrapped(config, src, sink)
    build(config, src, sink).run_once()
    assert sink.sent == []


# ---------- delivery (US-1) ----------

def test_new_posts_are_delivered(config):
    src = FakeSource([tweet(1, minutes=1)])
    sink = RecordingSink()
    bootstrapped(config, src, sink)
    src.tweets.append(tweet(2, minutes=2))
    build(config, src, sink).run_once()
    assert len(sink.sent) == 1 and "post 2" in sink.sent[0]


def test_delivered_posts_are_never_redelivered(config):
    """AC-1.2 across repeated runs."""
    src = FakeSource([tweet(1, minutes=1)])
    sink = RecordingSink()
    bootstrapped(config, src, sink)
    src.tweets.append(tweet(2, minutes=2))
    for _ in range(3):
        build(config, src, sink).run_once()
    assert len(sink.sent) == 1


def test_delivery_is_oldest_first_regardless_of_source_order(config):
    """AC-1.3/FR-3: the real feed is unordered."""
    src = FakeSource([tweet(1, minutes=1)])
    sink = RecordingSink()
    bootstrapped(config, src, sink)
    src.tweets += [tweet(50, minutes=50), tweet(10, minutes=10), tweet(30, minutes=30)]
    build(config, src, sink).run_once()
    assert [m.split("\n")[0] for m in sink.sent] == ["post 10", "post 30", "post 50"]


def test_old_retweet_is_delivered_despite_low_id(config):
    """AC-2.2/DD-1 — the case a since_id watermark would silently swallow."""
    src = FakeSource([tweet(9_000_000_000, minutes=1)])
    sink = RecordingSink()
    bootstrapped(config, src, sink)
    src.tweets.append(tweet(42, kind=TweetKind.RETWEET, minutes=5, author="someone"))
    build(config, src, sink).run_once()
    assert len(sink.sent) == 1 and "post 42" in sink.sent[0]


# ---------- filtering (US-2) ----------

@pytest.mark.parametrize("kind,setting,expected", [
    (TweetKind.RETWEET, {"INCLUDE_RETWEETS": True}, 1),
    (TweetKind.RETWEET, {"INCLUDE_RETWEETS": False}, 0),
    (TweetKind.REPLY, {"INCLUDE_REPLIES": False}, 0),
    (TweetKind.REPLY, {"INCLUDE_REPLIES": True}, 1),
    (TweetKind.QUOTE, {"INCLUDE_QUOTES": True}, 1),
    (TweetKind.QUOTE, {"INCLUDE_QUOTES": False}, 0),
    (TweetKind.ORIGINAL, {"INCLUDE_RETWEETS": False}, 1),
])
def test_kind_filtering(config, kind, setting, expected):
    cfg = config.model_copy(update=setting)
    src = FakeSource([tweet(1, minutes=1)])
    sink = RecordingSink()
    Pipeline(cfg, src, sink).run_once(); sink.sent.clear(); sink.attempts = 0
    src.tweets.append(tweet(2, kind=kind, minutes=2, author="other"))
    Pipeline(cfg, src, sink).run_once()
    assert len(sink.sent) == expected


def test_filtered_posts_are_marked_seen_not_left_pending(config):
    """A filtered post must not reappear if the operator later enables that kind
    mid-backlog — it was never 'pending', it was excluded."""
    cfg = config.model_copy(update={"INCLUDE_REPLIES": False})
    src = FakeSource([tweet(1, minutes=1)])
    sink = RecordingSink()
    Pipeline(cfg, src, sink).run_once()
    src.tweets.append(tweet(2, kind=TweetKind.REPLY, minutes=2))
    Pipeline(cfg, src, sink).run_once()
    assert 2 in load_state(cfg.STATE_PATH, H).seen_ids


# ---------- per-check cap (FR-11, D-3) ----------

def test_cap_withholds_and_reports(config):
    cfg = config.model_copy(update={"MAX_MESSAGES_PER_RUN": 3})
    src = FakeSource([tweet(1, minutes=1)])
    sink = RecordingSink()
    Pipeline(cfg, src, sink).run_once(); sink.sent.clear(); sink.attempts = 0
    src.tweets += [tweet(i, minutes=i) for i in range(10, 20)]
    result = Pipeline(cfg, src, sink).run_once()
    assert result.withheld == 7
    assert len(sink.sent) == 4                       # 3 posts + 1 withheld notice
    assert "more" in sink.sent[-1].lower()


def test_withheld_posts_drain_on_later_checks(config):
    """D-3: the cap rate-limits; it must never drop a post."""
    cfg = config.model_copy(update={"MAX_MESSAGES_PER_RUN": 3})
    src = FakeSource([tweet(1, minutes=1)])
    sink = RecordingSink()
    Pipeline(cfg, src, sink).run_once(); sink.sent.clear(); sink.attempts = 0
    src.tweets += [tweet(i, minutes=i) for i in range(10, 19)]   # 9 new
    delivered = []
    for _ in range(4):
        Pipeline(cfg, src, sink).run_once()
        delivered += [m for m in sink.sent if m.startswith("post")]
        sink.sent.clear()
    ids = sorted(int(m.split()[1]) for m in delivered)
    assert ids == list(range(10, 19)), "every withheld post must eventually arrive"


# ---------- partial failure (E-5, FR-12) ----------

def test_failed_send_is_retried_and_earlier_ones_are_not(config):
    src = FakeSource([tweet(1, minutes=1)])
    sink = RecordingSink()
    Pipeline(config, src, sink).run_once(); sink.sent.clear(); sink.attempts = 0
    src.tweets += [tweet(i, minutes=i) for i in (10, 11, 12, 13, 14)]

    sink.fail_on = {3}                       # third send fails
    Pipeline(config, src, sink).run_once()
    first_pass = [m.split("\n")[0] for m in sink.sent]
    assert first_pass == ["post 10", "post 11"]

    state = load_state(config.STATE_PATH, H)
    assert 10 in state.seen_ids and 11 in state.seen_ids
    assert 12 not in state.seen_ids          # FR-12: not delivered, not marked

    sink.fail_on = set(); sink.sent.clear(); sink.attempts = 0
    Pipeline(config, src, sink).run_once()
    assert [m.split("\n")[0] for m in sink.sent] == ["post 12", "post 13", "post 14"]


# ---------- outage (US-4) ----------

def test_total_source_failure_notifies_once(config):
    """AC-4.1 and AC-4.3 together."""
    src = FakeSource([tweet(1, minutes=1)])
    sink = RecordingSink()
    Pipeline(config, src, sink).run_once(); sink.sent.clear(); sink.attempts = 0

    down = FakeSource(error="all mirrors failed")
    Pipeline(config, down, sink).run_once()
    assert len(sink.sent) == 1 and "⚠️" in sink.sent[0]

    Pipeline(config, down, sink).run_once()
    Pipeline(config, down, sink).run_once()
    assert len(sink.sent) == 1, "an ongoing outage must not notify repeatedly"


def test_outage_state_untouched_and_rearms_after_recovery(config):
    """AC-4.2: nothing lost, nothing duplicated across an outage."""
    src = FakeSource([tweet(1, minutes=1)])
    sink = RecordingSink()
    Pipeline(config, src, sink).run_once(); sink.sent.clear(); sink.attempts = 0

    before = load_state(config.STATE_PATH, H).seen_ids
    down = FakeSource(error="down")
    Pipeline(config, down, sink).run_once()
    assert load_state(config.STATE_PATH, H).seen_ids == before

    src.tweets.append(tweet(7, minutes=7))
    sink.sent.clear()
    Pipeline(config, src, sink).run_once()
    assert any("post 7" in m for m in sink.sent)

    sink.sent.clear()
    Pipeline(config, down, sink).run_once()
    assert len(sink.sent) == 1, "a new outage after recovery must notify again"


def test_empty_account_is_silent_not_an_outage(config):
    """§7: silence must mean healthy. An empty result is not a failure."""
    sink = RecordingSink()
    Pipeline(config, FakeSource([]), sink).run_once()
    sink.sent.clear()
    result = Pipeline(config, FakeSource([]), sink).run_once()
    assert sink.sent == [] and result.outage is False


def test_every_run_path_logs_completion(config, caplog):
    """Observability: 'check complete' must appear on the bootstrap and outage paths
    too, not only the normal one — otherwise log-based monitoring silently misses them."""
    import logging
    with caplog.at_level(logging.INFO):
        Pipeline(config, FakeSource([tweet(1, minutes=1)]), RecordingSink()).run_once()
    assert "check complete" in caplog.text            # bootstrap path

    caplog.clear()
    with caplog.at_level(logging.INFO):
        Pipeline(config, FakeSource(error="down"), RecordingSink()).run_once()
    assert "check complete" in caplog.text            # outage path

    caplog.clear()
    with caplog.at_level(logging.INFO):
        Pipeline(config, FakeSource([tweet(1, minutes=1)]), RecordingSink()).run_once()
    assert "check complete" in caplog.text            # normal path
