"""HttpMirrorProbe maps one mirror's answer to a ProbeOutcome (spec 002 contract
mirror-probe.md; FR-3, FR-6, E-2, AC-1.7)."""
import pathlib
from datetime import timedelta

import httpx
import pytest
import respx

from tweet_relay.mirrors.models import Reason
from tweet_relay.mirrors.probe import HttpMirrorProbe
from tweet_relay.sources.nitter_rss import parse_feed

FIX = pathlib.Path(__file__).parent.parent / "fixtures" / "mirrors"
FEED = (FIX / "feed_pp_ua.xml").read_bytes()
HOST = "nitter.pp.ua"
URL = f"https://{HOST}/santtiagom_/rss"
NEWEST = max(t.published_at for t in parse_feed(FEED, "santtiagom_", HOST))


def _probe(config, now=NEWEST + timedelta(hours=1), clock=None):
    ticks = iter(clock or [0.0, 0.25])
    return HttpMirrorProbe(config, resolve=lambda host: None, now=lambda: now,
                           clock=lambda: next(ticks))


@respx.mock
def test_usable_feed(config):
    respx.get(URL).mock(httpx.Response(200, content=FEED))
    outcome = _probe(config).probe(HOST, "santtiagom_")
    assert outcome.usable and outcome.reason is None
    assert outcome.ms == 250
    assert outcome.newest == NEWEST


@respx.mock
def test_future_dated_posts_do_not_count_as_newest(config):
    """E-2: a post more than 5 minutes in the future cannot make a mirror look fresher."""
    respx.get(URL).mock(httpx.Response(200, content=FEED))
    now = NEWEST - timedelta(hours=2)
    outcome = _probe(config, now=now).probe(HOST, "santtiagom_")
    assert outcome.newest <= now + timedelta(minutes=5)


@respx.mock
@pytest.mark.parametrize("response,reason", [
    (httpx.Response(403), Reason.REFUSED_ANSWER),
    (httpx.Response(307, headers={"location": "/x"}), Reason.SENT_ELSEWHERE),
    (httpx.Response(200, content=(FIX / "access_queue_jaydenha.html").read_bytes()),
     Reason.MALFORMED_CONTENT),
])
def test_answers_map_to_reasons(config, response, reason):
    respx.get(URL).mock(response)
    outcome = _probe(config).probe(HOST, "santtiagom_")
    assert (outcome.usable, outcome.reason, outcome.newest) == (False, reason, None)
    assert outcome.ms == 250


@respx.mock
def test_timeout_maps_to_timed_out(config):
    respx.get(URL).mock(side_effect=httpx.ReadTimeout("slow"))
    assert _probe(config).probe(HOST, "santtiagom_").reason is Reason.TIMED_OUT


@respx.mock
def test_unreachable_has_no_timing(config):
    respx.get(URL).mock(side_effect=httpx.ConnectError("refused"))
    outcome = _probe(config).probe(HOST, "santtiagom_")
    assert outcome.reason is Reason.UNREACHABLE and outcome.ms is None


@respx.mock
def test_empty_feed_is_no_posts(config):
    empty = b'<?xml version="1.0"?><rss><channel><title>@santtiagom_</title></channel></rss>'
    respx.get(URL).mock(httpx.Response(200, content=empty))
    assert _probe(config).probe(HOST, "santtiagom_").reason is Reason.NO_POSTS


@respx.mock
def test_unexpected_errors_propagate(config):
    """Contract 2: anything a mirror cannot cause is a bug, i.e. 'check broken'."""
    respx.get(URL).mock(side_effect=RuntimeError("bug"))
    with pytest.raises(RuntimeError):
        _probe(config).probe(HOST, "santtiagom_")
