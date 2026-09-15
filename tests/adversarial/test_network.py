"""Hostile or failing network conditions."""
import httpx, pytest, respx
from tweet_relay.models import SourceUnavailable
from tweet_relay.sources.nitter_rss import NitterRssSource
from tweet_relay.pipeline import Pipeline
from tweet_relay.state import load_state
from tests.doubles import FakeSource, RecordingSink, tweet

H = "santtiagom_"
M1, M2 = "https://m1.example.com", "https://m2.example.com"


@respx.mock
@pytest.mark.parametrize("status", [400, 401, 403, 404, 418, 429, 500, 502, 503, 504])
def test_every_error_status_is_survived(config, status):
    respx.get(f"{M1}/{H}/rss").mock(httpx.Response(status))
    respx.get(f"{M2}/{H}/rss").mock(httpx.Response(status))
    with pytest.raises(SourceUnavailable):
        NitterRssSource(config).fetch(H)


@respx.mock
@pytest.mark.parametrize("exc", [
    httpx.ConnectError("refused"), httpx.ReadTimeout("slow"),
    httpx.ConnectTimeout("slow"), httpx.RemoteProtocolError("bad"),
    httpx.TooManyRedirects("loop"),
])
def test_transport_failures_are_survived(config, exc):
    respx.get(f"{M1}/{H}/rss").mock(side_effect=exc)
    respx.get(f"{M2}/{H}/rss").mock(side_effect=exc)
    with pytest.raises(SourceUnavailable):
        NitterRssSource(config).fetch(H)


@respx.mock
def test_one_hostile_mirror_does_not_stop_the_relay(config, real_feed):
    """FR-9: the point of having four."""
    respx.get(f"{M1}/{H}/rss").mock(httpx.Response(200, content=b"<html>garbage"))
    respx.get(f"{M2}/{H}/rss").mock(httpx.Response(200, content=real_feed))
    assert len(NitterRssSource(config).fetch(H)) == 19


@respx.mock
def test_redirect_chain_is_not_followed(config, real_feed):
    respx.get(f"{M1}/{H}/rss").mock(
        httpx.Response(302, headers={"location": f"{M1}/loop"}))
    hop = respx.get(f"{M1}/loop").mock(httpx.Response(200, content=real_feed))
    respx.get(f"{M2}/{H}/rss").mock(httpx.Response(200, content=real_feed))
    NitterRssSource(config).fetch(H)
    assert not hop.called


def test_outage_leaves_history_untouched(config):
    """AC-4.2: an outage must not cost us or duplicate anything."""
    sink = RecordingSink()
    good = FakeSource([tweet(i, minutes=i) for i in range(1, 5)])
    Pipeline(config, good, sink).run_once()
    before = load_state(config.STATE_PATH, H).seen_ids

    for _ in range(5):
        Pipeline(config, FakeSource(error="everything is down"), sink).run_once()
    assert load_state(config.STATE_PATH, H).seen_ids == before


def test_repeated_outage_notifies_once_even_across_many_checks(config):
    """AC-4.3: a multi-day outage must not send hundreds of messages."""
    sink = RecordingSink()
    Pipeline(config, FakeSource([tweet(1, minutes=1)]), sink).run_once()
    sink.sent.clear()
    down = FakeSource(error="down")
    for _ in range(50):
        Pipeline(config, down, sink).run_once()
    assert len(sink.sent) == 1


def test_sink_failure_during_outage_notice_does_not_crash(config):
    """Both halves broken at once is exactly when a crash would be worst."""
    class DeadSink:
        def send(self, message):
            from tweet_relay.models import DeliveryFailed
            raise DeliveryFailed("channel down too")

    result = Pipeline(config, FakeSource(error="down"), DeadSink()).run_once()
    assert result.outage is True
