import pytest
from datetime import datetime, timezone
from tweet_relay.models import Tweet, TweetKind, SourceUnavailable, DeliveryFailed

UTC = timezone.utc


def make(**kw):
    base = dict(id=123, author="santtiagom_", text="hello",
                published_at=datetime(2026, 9, 15, tzinfo=UTC), kind=TweetKind.ORIGINAL)
    return Tweet(**{**base, **kw})


def test_url_is_constructed_not_supplied():
    """DD-5: the URL is built from validated parts, never copied from the feed."""
    assert make().url == "https://x.com/santtiagom_/status/123"


def test_url_uses_original_author_for_retweet():
    t = make(author="atrjava", id=999, kind=TweetKind.RETWEET)
    assert t.url == "https://x.com/atrjava/status/999"


@pytest.mark.parametrize("bad", [0, -1, 2**63])
def test_rejects_out_of_range_ids(bad):
    with pytest.raises(ValueError):
        make(id=bad)


@pytest.mark.parametrize("bad", ["", "a" * 16, "has space", "has-dash", "../../admin"])
def test_rejects_malformed_authors(bad):
    with pytest.raises(ValueError):
        make(author=bad)


def test_rejects_naive_datetime():
    with pytest.raises(ValueError):
        make(published_at=datetime(2026, 9, 15))


def test_text_strips_control_and_bidi_but_keeps_newlines_and_emoji():
    t = make(text="a\x00b‮c‍d\ne 🎉")
    assert "\x00" not in t.text and "‮" not in t.text
    assert "\n" in t.text and "🎉" in t.text


@pytest.mark.parametrize("raw", ["", "   ", "\x00‮", "\u200b\u202e"])
def test_text_may_be_empty_after_normalisation(raw):
    """003 US-7, FR-19: a post with no text of its own is a valid post."""
    assert make(text=raw).text == ""


def test_empty_text_does_not_relax_other_invariants():
    """003 AC-7.3: only "no text" changed."""
    for bad in (dict(id=0), dict(author="has space"), dict(published_at=datetime(2026, 9, 15))):
        with pytest.raises(ValueError):
            make(text="", **bad)


def test_exceptions_exist():
    assert issubclass(SourceUnavailable, Exception)
    assert issubclass(DeliveryFailed, Exception)


def test_preview_url_is_built_from_author_and_id_only():
    """003 FR-2, plan DD-4: the card's go-between address comes from validated parts,
    so nothing a feed says can point the preview anywhere else."""
    assert make().preview_url == "https://fxtwitter.com/santtiagom_/status/123"
    assert make(author="atrjava", id=999, kind=TweetKind.RETWEET).preview_url == \
        "https://fxtwitter.com/atrjava/status/999"
