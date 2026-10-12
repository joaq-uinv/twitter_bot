"""fetch_one: one mirror, one answer, one reason (spec 002 FR-3, FR-5; plan DD-1).

The relay and the mirror probe share this function, so "usable" means exactly what
the relay accepts. Fixtures were captured from real mirrors on 2026-10-11.
"""
import pathlib

import httpx
import pytest
import respx

from tweet_relay.mirrors.models import Reason
from tweet_relay.models import SourceUnavailable
from tweet_relay.sources.nitter_rss import MirrorError, fetch_one

FIX = pathlib.Path(__file__).parent.parent / "fixtures" / "mirrors"
BASE = "https://nitter.pp.ua"
URL = f"{BASE}/santtiagom_/rss"
FEED = (FIX / "feed_pp_ua.xml").read_bytes()


def _fetch(config, handle="santtiagom_"):
    with httpx.Client(timeout=5, follow_redirects=False) as client:
        return fetch_one(client, BASE, handle, config)


def _reason(config, **kw):
    with pytest.raises(MirrorError) as exc:
        _fetch(config, **kw)
    assert isinstance(exc.value, SourceUnavailable)      # the relay's except still works
    return exc.value.reason


@respx.mock
def test_valid_feed_returns_posts(config):
    respx.get(URL).mock(httpx.Response(200, content=FEED))
    assert len(_fetch(config)) > 0


@respx.mock
@pytest.mark.parametrize("error,reason", [
    (httpx.ReadTimeout("slow"), Reason.TIMED_OUT),
    (httpx.ConnectTimeout("slow"), Reason.TIMED_OUT),
    (httpx.ConnectError("refused"), Reason.UNREACHABLE),
])
def test_transport_failures(config, error, reason):
    respx.get(URL).mock(side_effect=error)
    assert _reason(config) is reason


@respx.mock
def test_refused_answer(config):
    respx.get(URL).mock(httpx.Response(403, content=(FIX / "forbidden_tiekoetter.html").read_bytes()))
    assert _reason(config) is Reason.REFUSED_ANSWER


@respx.mock
def test_server_error_is_refused_answer(config):
    respx.get(URL).mock(httpx.Response(503))
    assert _reason(config) is Reason.REFUSED_ANSWER


@respx.mock
def test_bot_challenge_redirect_is_sent_elsewhere(config):
    """The real netbub answer: 307 to a challenge URL, never followed."""
    status, location = (FIX / "goaway_netbub.txt").read_text().splitlines()
    route = respx.get(URL).mock(httpx.Response(int(status.split()[1]),
                                               headers={"location": location.split(": ", 1)[1]}))
    assert _reason(config) is Reason.SENT_ELSEWHERE
    assert route.call_count == 1


@respx.mock
def test_declared_oversize_is_too_large(config):
    small = config.model_copy(update={"MAX_FEED_BYTES": 1024})
    respx.get(URL).mock(httpx.Response(200, content=b"x" * 2048))
    assert _reason(small) is Reason.TOO_LARGE


@respx.mock
def test_streamed_oversize_is_too_large(config):
    small = config.model_copy(update={"MAX_FEED_BYTES": 1024})
    respx.get(URL).mock(httpx.Response(200, content=iter([b"x" * 700, b"x" * 700])))
    assert _reason(small) is Reason.TOO_LARGE


@respx.mock
def test_access_queue_page_is_malformed_content(config):
    """The real jaydenha answer: HTTP 200 with an HTML waiting-room page (E-6)."""
    respx.get(URL).mock(httpx.Response(200, content=(FIX / "access_queue_jaydenha.html").read_bytes()))
    assert _reason(config) is Reason.MALFORMED_CONTENT


@respx.mock
def test_empty_body_is_malformed_content(config):
    respx.get(URL).mock(httpx.Response(200, content=b"   "))
    assert _reason(config) is Reason.MALFORMED_CONTENT


@respx.mock
def test_feed_for_another_account_is_wrong_account(config):
    respx.get(f"{BASE}/someoneelse/rss").mock(httpx.Response(200, content=FEED))
    assert _reason(config, handle="someoneelse") is Reason.WRONG_ACCOUNT


@respx.mock
def test_feed_with_no_items_returns_empty(config):
    """Relay contract guarantee 3: an empty feed is a quiet account, not a failure."""
    empty = (b'<?xml version="1.0"?><rss><channel><title>santi / @santtiagom_</title>'
             b"</channel></rss>")
    respx.get(URL).mock(httpx.Response(200, content=empty))
    assert _fetch(config) == []


# --- review #4: a total deadline, not just a per-read timeout ---

@respx.mock
def test_slow_drip_body_is_timed_out(config, monkeypatch):
    """A hostile mirror sending bytes just under the read timeout must not hold the probe."""
    from tweet_relay.sources import nitter_rss
    clock = iter([0.0, 5.0, 10.0, 16.0, 30.0, 60.0])
    monkeypatch.setattr(nitter_rss.time, "monotonic", lambda: next(clock))
    respx.get(URL).mock(httpx.Response(200, content=iter([b"<rss>", b"x" * 10, b"x" * 10, b"x"])))
    assert _reason(config) is Reason.TIMED_OUT


# --- review #3: feed-supplied hostnames never reach the logs ---

@respx.mock
def test_foreign_link_hosts_are_counted_not_logged(config, caplog):
    import logging
    feed = FEED.replace(b"://nitter.pp.ua/", b"://zz-leak.example/")
    respx.get(URL).mock(httpx.Response(200, content=feed))
    with caplog.at_level(logging.DEBUG):
        _fetch(config)
    assert "zz-leak" not in caplog.text
    rebuilt = [r for r in caplog.records if "rebuilt" in r.getMessage()]
    assert len(rebuilt) == 1                    # one line per feed, with a count
