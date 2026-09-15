"""Parser behaviour against the real captured feed."""
import pytest
from datetime import datetime, timezone
from tweet_relay.models import TweetKind
from tweet_relay.sources.nitter_rss import parse_feed

H = "santtiagom_"


@pytest.fixture
def tweets(real_feed):
    return parse_feed(real_feed, H)


def test_parses_every_item(tweets):
    assert len(tweets) == 19


def test_guid_becomes_the_integer_id(tweets):
    """F-1: guid is the bare post ID, not a URL."""
    assert 2099612045347848465 in {t.id for t in tweets}
    assert all(isinstance(t.id, int) and t.id > 0 for t in tweets)


def test_classification_matches_amendment_a1(tweets):
    counts = {}
    for t in tweets:
        counts[t.kind] = counts.get(t.kind, 0) + 1
    assert counts.get(TweetKind.RETWEET) == 14   # 11 foreign-author + 3 self
    assert counts.get(TweetKind.QUOTE) == 4
    assert counts.get(TweetKind.ORIGINAL) == 1
    assert counts.get(TweetKind.REPLY, 0) == 0


def test_self_retweet_is_a_retweet_not_an_original(tweets):
    """Amendment A-1: link-author-differs alone would misclassify this."""
    t = next(t for t in tweets if t.id == 2099612045347848465)
    assert t.kind is TweetKind.RETWEET
    assert t.author == H          # own author, yet still a retweet


def test_foreign_retweet_keeps_original_author(tweets):
    t = next(t for t in tweets if t.id == 2099742569009762599)
    assert t.kind is TweetKind.RETWEET
    assert t.author == "atrjava"
    assert t.url == "https://x.com/atrjava/status/2099742569009762599"


def test_url_is_rewritten_to_x_com_without_fragment(tweets):
    """The feed's links are mirror-hosted and carry a #m fragment."""
    assert all(t.url.startswith("https://x.com/") for t in tweets)
    assert not any("#" in t.url or "nitter" in t.url for t in tweets)


def test_returns_chronological_order_regardless_of_feed_order(tweets):
    """F-2/FR-3: the source feed is genuinely out of date order."""
    times = [t.published_at for t in tweets]
    assert times == sorted(times)


def test_feed_really_is_unordered(real_feed):
    """Guards the guard: if this fails the fixture changed and the ordering test
    above is no longer proving anything."""
    import re
    raw = [datetime.strptime(m, "%a, %d %b %Y %H:%M:%S %Z").replace(tzinfo=timezone.utc)
           for m in re.findall(r"<pubDate>(.*?)</pubDate>", real_feed.decode())]
    assert raw != sorted(raw), "fixture is now ordered; ordering test is vacuous"


def test_all_timestamps_are_timezone_aware(tweets):
    assert all(t.published_at.tzinfo is not None for t in tweets)


def test_rejects_feed_for_a_different_account(real_feed):
    """FR-7/E-7: a mirror serving someone else's content is a broken mirror."""
    from tweet_relay.models import SourceUnavailable
    with pytest.raises(SourceUnavailable):
        parse_feed(real_feed, "someone_else")
