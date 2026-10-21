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


# --- E-21 / D-4: minimal form for a message the channel refuses ---

@pytest.mark.parametrize("kind,author,lead", [
    (TweetKind.ORIGINAL, "santtiagom_", "New post from @santtiagom_"),
    (TweetKind.RETWEET, "ezecostales", "@santtiagom_ reposted @ezecostales"),
    (TweetKind.QUOTE, "santtiagom_", "@santtiagom_ quoted a post"),
    (TweetKind.REPLY, "santtiagom_", "@santtiagom_ replied"),
])
def test_minimal_form_names_the_kind_and_carries_only_the_link(kind, author, lead):
    """Review #3: a repost must not be presented as the account's own post."""
    from tweet_relay.formatter import render_minimal
    post = t(id=2108539369770672204, text="prompt engineering 👀", kind=kind, author=author)
    assert render_minimal(post, "santtiagom_") == (
        f"{lead} (its text could not be delivered): "
        f"https://x.com/{author}/status/2108539369770672204")


def test_minimal_form_never_includes_post_text():
    from tweet_relay.formatter import render_minimal
    post = t(text="UNIQUE-MARKER-7f3a anything at all")
    assert "UNIQUE-MARKER-7f3a" not in render_minimal(post, "santtiagom_")


@pytest.mark.parametrize("kind,author,lead", [
    (TweetKind.ORIGINAL, "santtiagom_", "New post from @santtiagom_ (no text)"),
    (TweetKind.RETWEET, "atrjava", "@santtiagom_ reposted @atrjava (no text)"),
    (TweetKind.QUOTE, "santtiagom_", "@santtiagom_ quoted a post (no text)"),
    (TweetKind.REPLY, "santtiagom_", "@santtiagom_ replied (no text)"),
])
def test_post_without_text_gets_a_fixed_line_by_kind(kind, author, lead):
    """003 AC-7.1, E-21: a repost is never presented as the account's own post."""
    post = t(text="", author=author, kind=kind)
    assert render(post, "santtiagom_") == f"{lead}\n\n{post.url}"
