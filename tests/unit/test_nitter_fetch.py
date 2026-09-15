"""Fetching, failover and resource limits. No real network (§5)."""
import httpx, pytest, respx
from tweet_relay.models import SourceUnavailable
from tweet_relay.sources.nitter_rss import NitterRssSource

H = "santtiagom_"
M1, M2 = "https://m1.example.com", "https://m2.example.com"


def src(config, **kw):
    return NitterRssSource(config, **kw)


@respx.mock
def test_uses_first_healthy_mirror(config, real_feed):
    r1 = respx.get(f"{M1}/{H}/rss").mock(httpx.Response(200, content=real_feed))
    r2 = respx.get(f"{M2}/{H}/rss").mock(httpx.Response(200, content=real_feed))
    assert len(src(config).fetch(H)) == 19
    assert r1.called and not r2.called


@respx.mock
def test_fails_over_to_second_mirror(config, real_feed):
    """FR-9: an individual source failing must not stop the relay."""
    respx.get(f"{M1}/{H}/rss").mock(httpx.Response(500))
    r2 = respx.get(f"{M2}/{H}/rss").mock(httpx.Response(200, content=real_feed))
    assert len(src(config).fetch(H)) == 19
    assert r2.called


@respx.mock
def test_fails_over_on_timeout(config, real_feed):
    """E-18: a mirror that hangs must not hang the relay."""
    respx.get(f"{M1}/{H}/rss").mock(side_effect=httpx.ReadTimeout("hung"))
    respx.get(f"{M2}/{H}/rss").mock(httpx.Response(200, content=real_feed))
    assert len(src(config).fetch(H)) == 19


@respx.mock
def test_raises_only_when_every_mirror_fails(config):
    """FR-10 depends on this being distinguishable from an empty account."""
    respx.get(f"{M1}/{H}/rss").mock(httpx.Response(429))
    respx.get(f"{M2}/{H}/rss").mock(httpx.Response(503))
    with pytest.raises(SourceUnavailable):
        src(config).fetch(H)


@respx.mock
def test_wrong_account_is_treated_as_mirror_failure(config, real_feed):
    """FR-7/E-7: both mirrors answer 200 but serve @santtiagom_'s feed when asked
    for a different account. Content that is not ours is discarded entirely."""
    respx.get(f"{M1}/someone_else/rss").mock(httpx.Response(200, content=real_feed))
    respx.get(f"{M2}/someone_else/rss").mock(httpx.Response(200, content=real_feed))
    with pytest.raises(SourceUnavailable):
        src(config).fetch("someone_else")


@respx.mock
def test_oversized_response_is_refused_before_parsing(config):
    """E-9: memory exhaustion via a huge body."""
    huge = b"<rss><channel><title>@santtiagom_</title>" + b"<!--" + b"x" * 200_000 + b"-->"
    respx.get(f"{M1}/{H}/rss").mock(httpx.Response(200, content=huge))
    respx.get(f"{M2}/{H}/rss").mock(httpx.Response(200, content=huge))
    small = config.model_copy(update={"MAX_FEED_BYTES": 1024})
    with pytest.raises(SourceUnavailable):
        src(small).fetch(H)


@respx.mock
def test_empty_body_is_a_failure_not_an_empty_account(config):
    respx.get(f"{M1}/{H}/rss").mock(httpx.Response(200, content=b""))
    respx.get(f"{M2}/{H}/rss").mock(httpx.Response(200, content=b""))
    with pytest.raises(SourceUnavailable):
        src(config).fetch(H)


@respx.mock
def test_does_not_follow_cross_host_redirects(config, real_feed):
    """§4: a redirect is a mirror telling us to fetch from somewhere else entirely."""
    respx.get(f"{M1}/{H}/rss").mock(
        httpx.Response(302, headers={"location": "https://evil.example.com/x"}))
    evil = respx.get("https://evil.example.com/x").mock(
        httpx.Response(200, content=real_feed))
    respx.get(f"{M2}/{H}/rss").mock(httpx.Response(200, content=real_feed))
    src(config).fetch(H)
    assert not evil.called


@respx.mock
def test_request_carries_an_explicit_timeout(config, real_feed):
    seen = {}

    def capture(request):
        seen["timeout"] = request.extensions.get("timeout")
        return httpx.Response(200, content=real_feed)

    respx.get(f"{M1}/{H}/rss").mock(side_effect=capture)
    src(config).fetch(H)
    assert seen["timeout"] is not None
    assert all(v is not None for v in seen["timeout"].values())
