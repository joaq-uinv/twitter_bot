"""A mirror that is reachable but lying."""
import pytest
from datetime import datetime, timedelta, timezone
from tweet_relay.models import SourceUnavailable, TweetKind
from tweet_relay.sources.nitter_rss import parse_feed
from tests.adversarial.test_hostile_xml import feed, item

H = "santtiagom_"


# ---------- identity ----------

@pytest.mark.parametrize("title", [
    "elonmusk / @elonmusk",
    "santi",
    "",
    "@santtiagom_evil",           # must not substring-match
    "santi / @santtiagom",        # prefix of our handle
])
def test_feed_for_another_account_is_refused(title):
    """FR-7/E-7: the operator must never be shown someone else's posts as this
    account's. Word-boundary matching also blocks near-miss handles."""
    with pytest.raises(SourceUnavailable):
        parse_feed(feed(item(), title=title), H)


# ---------- link forgery ----------

@pytest.mark.parametrize("link", [
    "https://nitter.example/../../admin",
    "https://nitter.example/santtiagom_/status/abc",
    "javascript:alert(1)",
    "https://nitter.example/santtiagom_/statuses/123",
    "https://nitter.example/toolonghandlename12345/status/1",
])
def test_unrecognised_links_are_dropped_never_rewritten(link):
    """DD-5/E-10: blind host-rewriting would hand the operator an attacker-chosen
    path dressed up as a genuine x.com link."""
    payload = feed(f"<item><title>x</title><link>{link}</link><guid>1</guid>"
                   f"<pubDate>Mon, 14 Sep 2026 21:31:35 GMT</pubDate></item>"
                   + item(id="777"))
    tweets = parse_feed(payload, H)
    assert [t.id for t in tweets] == [777]
    assert all(t.url.startswith("https://x.com/") for t in tweets)


@pytest.mark.parametrize("expected_host", [None, "nitter.example"])
def test_foreign_host_link_is_neutralised_by_rebuilding_the_url(expected_host):
    """DD-5: the emitted URL is constructed from validated parts, so an attacker's
    host never reaches the operator — with or without host pinning.

    Host pinning was implemented and then reverted: legitimate mirrors serve
    canonical links on other hosts, so rejecting them emptied a working feed
    silently, which is a worse failure than the risk it removed."""
    payload = feed("<item><title>x</title>"
                   "<link>https://evil.example.com/santtiagom_/status/123</link>"
                   "<guid>123</guid>"
                   "<pubDate>Mon, 14 Sep 2026 21:31:35 GMT</pubDate></item>")
    tweets = parse_feed(payload, H, expected_host=expected_host)
    assert tweets[0].url == "https://x.com/santtiagom_/status/123"
    assert "evil.example.com" not in tweets[0].url


def test_a_mirror_serving_canonical_links_still_works():
    """Regression for the reverted pinning: this feed must not come back empty."""
    payload = feed("<item><title>x</title>"
                   "<link>https://nitter.other-host.net/santtiagom_/status/55</link>"
                   "<guid>55</guid>"
                   "<pubDate>Mon, 14 Sep 2026 21:31:35 GMT</pubDate></item>")
    tweets = parse_feed(payload, H, expected_host="nitter.example")
    assert [t.id for t in tweets] == [55], "pinning must not silently empty a feed"


def test_every_emitted_url_is_on_x_com():
    tweets = parse_feed(feed("".join(item(id=str(i)) for i in range(1, 6))), H)
    assert all(t.url.startswith("https://x.com/") for t in tweets)


# ---------- identifier abuse ----------

@pytest.mark.parametrize("guid", ["abc", "-1", "0", "9" * 30, "", "1e10", "١٢٣"])
def test_hostile_guids_never_produce_a_bad_tweet(guid):
    """The id keys delivery history; a corrupt one could poison dedup permanently."""
    payload = feed(f"<item><title>x</title>"
                   f"<link>https://nitter.example/santtiagom_/status/555</link>"
                   f"<guid>{guid}</guid>"
                   f"<pubDate>Mon, 14 Sep 2026 21:31:35 GMT</pubDate></item>")
    for t in parse_feed(payload, H):
        assert isinstance(t.id, int) and 0 < t.id < 2**63


def test_duplicate_guids_in_one_feed_yield_one_post():
    """E-3."""
    tweets = parse_feed(feed(item(id="42") + item(id="42") + item(id="42")), H)
    assert [t.id for t in tweets] == [42]


def test_guid_disagreeing_with_link_trusts_the_validated_link():
    payload = feed(f"<item><title>x</title>"
                   f"<link>https://nitter.example/santtiagom_/status/111</link>"
                   f"<guid>999999</guid>"
                   f"<pubDate>Mon, 14 Sep 2026 21:31:35 GMT</pubDate></item>")
    assert [t.id for t in parse_feed(payload, H)] == [111]


# ---------- timestamps ----------

def test_far_future_timestamp_is_dropped():
    """E-12: a fabricated future date would sit at the head of the queue forever."""
    future = (datetime.now(timezone.utc) + timedelta(days=3650)).strftime(
        "%a, %d %b %Y %H:%M:%S GMT")
    tweets = parse_feed(feed(item(id="1", date=future) + item(id="777")), H)
    assert [t.id for t in tweets] == [777]


def test_slight_clock_skew_is_tolerated():
    soon = (datetime.now(timezone.utc) + timedelta(hours=1)).strftime(
        "%a, %d %b %Y %H:%M:%S GMT")
    assert len(parse_feed(feed(item(id="1", date=soon)), H)) == 1


@pytest.mark.parametrize("date", ["", "not a date", "Mon, 99 Xxx 9999", "0"])
def test_unparseable_timestamps_drop_the_item(date):
    tweets = parse_feed(feed(item(id="1", date=date) + item(id="777")), H)
    assert [t.id for t in tweets] == [777]


# ---------- hostile text ----------

def test_control_and_bidi_characters_are_stripped():
    """U+202E can visually reverse text, e.g. disguising a link's true target."""
    tweets = parse_feed(feed(item(id="1", title="safe&#x202E;txet lufmrah&#x200B;")), H)
    text = tweets[0].text
    assert "‮" not in text and "​" not in text and "\x00" not in text


def test_markup_in_text_stays_inert_text():
    tweets = parse_feed(feed(item(id="1", title="&lt;script&gt;alert(1)&lt;/script&gt;")), H)
    assert "<script>" in tweets[0].text     # literal text, never interpreted


def test_enormous_text_is_capped():
    tweets = parse_feed(feed(item(id="1", title="A" * 60_000)), H)
    assert len(tweets[0].text) <= 10_000


def test_emoji_and_non_latin_text_survive_intact():
    tweets = parse_feed(feed(item(id="1", title="🎉 español 日本語 العربية")), H)
    assert "🎉" in tweets[0].text and "日本語" in tweets[0].text


def test_retweet_marker_in_user_text_cannot_forge_a_self_retweet():
    """The marker is trusted (A-1), so verify it cannot be spoofed into changing
    the author the operator is shown."""
    tweets = parse_feed(feed(item(id="1", author="realauthor",
                                  title="RT by @santtiagom_: text")), H)
    assert tweets[0].kind is TweetKind.RETWEET
    assert tweets[0].author == "realauthor"          # from the link, not the marker
    assert tweets[0].url == "https://x.com/realauthor/status/1"
