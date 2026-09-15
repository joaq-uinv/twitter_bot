"""Live tests. Excluded from the default run (§5); opt in with `pytest -m live`."""
import pytest
from tweet_relay.config import Config
from tweet_relay.models import SourceUnavailable
from tweet_relay.sources.nitter_rss import NitterRssSource

pytestmark = pytest.mark.live


def live_config(**kw):
    return Config(X_PROFILE_URL="https://x.com/santtiagom_",
                  CALLMEBOT_PHONE="+34600111222", CALLMEBOT_APIKEY="unused", **kw)


def test_at_least_one_real_mirror_serves_the_account():
    """The zero-cost design rests entirely on these staying alive (research R-1)."""
    tweets = NitterRssSource(live_config()).fetch("santtiagom_")
    assert tweets, "no mirror returned posts — see quickstart.md to refresh the list"
    assert all(t.url.startswith("https://x.com/") for t in tweets)
    assert [t.published_at for t in tweets] == sorted(t.published_at for t in tweets)


@pytest.mark.parametrize("instance", [
    "https://nitter.kareem.one",
    "https://nitter.meowing.monster",
    "https://nitter.netbub.com",
    "https://nitter.jaydenha.uk",
])
def test_each_pinned_mirror_individually(instance):
    """Reports which pinned mirrors have died, rather than hiding it behind failover."""
    cfg = live_config(NITTER_INSTANCES=instance)
    try:
        tweets = NitterRssSource(cfg).fetch("santtiagom_")
    except SourceUnavailable as exc:
        pytest.skip(f"{instance} is currently unavailable: {exc}")
    assert tweets


def test_real_whatsapp_delivery():
    """Requires real credentials in the environment; skipped otherwise."""
    cfg = Config()
    try:
        cfg.require_delivery()
    except ValueError:
        pytest.skip("delivery credentials not configured")
    from tweet_relay.sinks.callmebot import CallMeBotSink
    CallMeBotSink(cfg, pace_seconds=0).send("🧪 tweet-relay integration test")
