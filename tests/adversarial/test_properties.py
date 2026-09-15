"""Property-based invariants.

The bugs these target are the ones example tests miss: they only appear for some
orderings or some id distributions. Stating them as laws lets hypothesis search for
the counterexample instead of us guessing it.
"""
import itertools
import random
from datetime import datetime, timedelta, timezone

from hypothesis import HealthCheck, given, settings, strategies as st

from tweet_relay.models import Tweet, TweetKind
from tweet_relay.pipeline import Pipeline
from tweet_relay.state import load_state
from tests.doubles import FakeSource, RecordingSink

H = "santtiagom_"
BASE = datetime(2026, 9, 1, tzinfo=timezone.utc)
SLOW = settings(max_examples=40, deadline=None,
                suppress_health_check=[HealthCheck.function_scoped_fixture])

# ids deliberately span a huge range and do NOT correlate with time: that is exactly
# the retweet case (research F-3) that a high-water mark gets wrong.
ids = st.lists(st.integers(min_value=1, max_value=9_999_999_999_999),
               min_size=1, max_size=25, unique=True)


_counter = itertools.count()


def fresh(config, **overrides):
    """A config with its own state file.

    Hypothesis runs many examples inside ONE function call, so a function-scoped
    tmp_path fixture is shared by all of them and history leaks between examples.
    Each example must start from empty state or the invariants are untestable.
    """
    import pathlib
    base = pathlib.Path(config.STATE_PATH).parent
    path = base / f"seen-{next(_counter)}.json"
    return config.model_copy(update={"STATE_PATH": str(path), **overrides})


def build(id_list, shuffle_seed=0):
    tweets = [
        Tweet(id=i, author=H, text=f"post {i}",
              published_at=BASE + timedelta(minutes=n), kind=TweetKind.ORIGINAL)
        for n, i in enumerate(id_list)
    ]
    random.Random(shuffle_seed).shuffle(tweets)
    return tweets


@given(id_list=ids, seed=st.integers(0, 10_000))
@SLOW
def test_delivery_is_independent_of_source_order(config, id_list, seed):
    """FR-3/E-1: the real feed is unordered, so order must not change WHAT arrives."""
    sink = RecordingSink()
    src = FakeSource(build(id_list, seed))
    cfg = fresh(config, MAX_MESSAGES_PER_RUN=50)

    Pipeline(cfg, FakeSource([]), sink).run_once()      # bootstrap on an empty feed
    sink.sent.clear(); sink.attempts = 0
    Pipeline(cfg, src, sink).run_once()

    delivered = {int(m.split("\n")[0].split()[1]) for m in sink.sent if m.startswith("post")}
    assert delivered == set(id_list)


@given(id_list=ids)
@SLOW
def test_delivery_is_always_chronological(config, id_list):
    """AC-1.3: ids are uncorrelated with time, so sorting must use time, not id."""
    sink = RecordingSink()
    cfg = fresh(config, MAX_MESSAGES_PER_RUN=50)
    tweets = build(id_list, 7)
    by_id = {t.id: t.published_at for t in tweets}

    Pipeline(cfg, FakeSource([]), sink).run_once()
    sink.sent.clear(); sink.attempts = 0
    Pipeline(cfg, FakeSource(tweets), sink).run_once()

    order = [int(m.split("\n")[0].split()[1]) for m in sink.sent if m.startswith("post")]
    times = [by_id[i] for i in order]
    assert times == sorted(times)


@given(id_list=ids, runs=st.integers(2, 6))
@SLOW
def test_repeated_checks_deliver_each_post_exactly_once(config, id_list, runs):
    """FR-2/AC-1.2: the exactly-once guarantee, under repetition."""
    sink = RecordingSink()
    cfg = fresh(config, MAX_MESSAGES_PER_RUN=50)
    src = FakeSource(build(id_list, 3))

    Pipeline(cfg, FakeSource([]), sink).run_once()
    sink.sent.clear(); sink.attempts = 0
    for _ in range(runs):
        Pipeline(cfg, src, sink).run_once()

    delivered = [int(m.split("\n")[0].split()[1]) for m in sink.sent if m.startswith("post")]
    assert sorted(delivered) == sorted(id_list)
    assert len(delivered) == len(set(delivered))


@given(id_list=ids, cap=st.integers(1, 5))
@SLOW
def test_capped_backlog_always_drains_completely(config, id_list, cap):
    """D-3/FR-11: the cap rate-limits and must never drop a post, for any cap."""
    sink = RecordingSink()
    cfg = fresh(config, MAX_MESSAGES_PER_RUN=cap)
    src = FakeSource(build(id_list, 11))

    Pipeline(cfg, FakeSource([]), sink).run_once()
    sink.sent.clear(); sink.attempts = 0

    # Enough checks to clear any backlog of this size.
    for _ in range(len(id_list) + 2):
        Pipeline(cfg, src, sink).run_once()

    delivered = [int(m.split("\n")[0].split()[1]) for m in sink.sent if m.startswith("post")]
    assert sorted(delivered) == sorted(id_list)
    assert len(delivered) == len(set(delivered))


@given(existing=st.integers(1, 9_999_999_999), old=st.integers(1, 1000))
@SLOW
def test_a_post_with_a_low_id_is_never_suppressed(config, existing, old):
    """DD-1 stated as a law: an id far BELOW everything already delivered is still
    new if it has not been delivered. This is precisely the retweet case."""
    sink = RecordingSink()
    cfg = fresh(config)
    seed = Tweet(id=existing + 10_000, author=H, text="seed",
                 published_at=BASE, kind=TweetKind.ORIGINAL)
    Pipeline(cfg, FakeSource([seed]), sink).run_once()
    sink.sent.clear(); sink.attempts = 0

    retweet = Tweet(id=old, author="other", text=f"post {old}",
                    published_at=BASE + timedelta(hours=1), kind=TweetKind.RETWEET)
    Pipeline(cfg, FakeSource([seed, retweet]), sink).run_once()
    assert len(sink.sent) == 1 and f"post {old}" in sink.sent[0]


@given(st.lists(st.integers(1, 10**12), min_size=0, max_size=400, unique=True))
@settings(max_examples=25, deadline=None)
def test_history_stays_bounded_however_much_arrives(id_list):
    """DD-2: the file lives on a mounted volume and must not grow without limit."""
    from tweet_relay.state import RelayState, MAX_SEEN
    state = RelayState(handle=H)
    for i in id_list:
        state.mark_seen(i)
    assert len(state.seen_ids) <= MAX_SEEN
    assert len(state.seen_ids) == len(set(state.seen_ids))
    for i in id_list[-min(len(id_list), MAX_SEEN):]:
        assert not state.is_new(i), "most recent ids must still be remembered"
