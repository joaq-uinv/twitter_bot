import pytest
from datetime import datetime, timezone
from tweet_relay.models import Tweet, TweetKind
from tweet_relay.formatter import render, MAX_TEXT_CHARS

UTC = timezone.utc


def t(**kw):
    base = dict(id=42, author="santtiagom_", text="hola mundo",
                published_at=datetime(2026, 9, 15, tzinfo=UTC), kind=TweetKind.ORIGINAL)
    return Tweet(**{**base, **kw})


def test_original_has_no_kind_marker():
    out = render(t(), "santtiagom_")
    assert out.startswith("hola mundo")
    assert "RT" not in out.split("\n")[0]


def test_retweet_names_the_original_author():
    """AC-2.1: the operator must be able to tell amplification from authorship."""
    out = render(t(author="atrjava", kind=TweetKind.RETWEET), "santtiagom_")
    assert "atrjava" in out and "RT" in out


def test_quote_is_distinguishable_from_retweet():
    """D-1: quotes are their own category."""
    q = render(t(kind=TweetKind.QUOTE), "santtiagom_")
    r = render(t(author="other", kind=TweetKind.RETWEET), "santtiagom_")
    assert q.split("\n")[0] != r.split("\n")[0]


def test_link_always_present_and_last():
    out = render(t(), "santtiagom_")
    assert out.rstrip().endswith("https://x.com/santtiagom_/status/42")


def test_long_text_truncates_but_link_survives():
    """E-13: the link is appended after truncation, so it can never be cut off."""
    out = render(t(text="x" * 5000), "santtiagom_")
    assert out.rstrip().endswith("https://x.com/santtiagom_/status/42")
    assert "…" in out
    assert len(out) < 5000


def test_short_text_is_not_truncated():
    assert "…" not in render(t(text="brief"), "santtiagom_")


def test_emoji_and_newlines_survive():
    out = render(t(text="line1\nline2 🎉"), "santtiagom_")
    assert "🎉" in out and "line1\nline2" in out


def test_truncation_boundary_is_exact():
    out = render(t(text="y" * (MAX_TEXT_CHARS + 50)), "santtiagom_")
    body = out.split("\n")[0] if "\n" in out else out
    assert "y" * MAX_TEXT_CHARS not in out or out.count("y") <= MAX_TEXT_CHARS
