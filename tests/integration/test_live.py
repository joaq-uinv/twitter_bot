"""Live tests. Excluded from the default run (§5); opt in with `pytest -m live`."""
import pytest
from tweet_relay.config import DEFAULT_INSTANCES, Config
from tweet_relay.models import SourceUnavailable
from tweet_relay.sources.nitter_rss import NitterRssSource

pytestmark = pytest.mark.live


def live_config(**kw):
    return Config(X_PROFILE_URL="https://x.com/santtiagom_", **kw)


def test_at_least_one_real_mirror_serves_the_account():
    """The zero-cost design rests entirely on these staying alive (research R-1)."""
    tweets = NitterRssSource(live_config()).fetch("santtiagom_")
    assert tweets, "no mirror returned posts — see quickstart.md to refresh the list"
    assert all(t.url.startswith("https://x.com/") for t in tweets)
    assert [t.published_at for t in tweets] == sorted(t.published_at for t in tweets)


@pytest.mark.parametrize("instance", DEFAULT_INSTANCES)   # never drifts from config
def test_each_pinned_mirror_individually(instance):
    """Reports which pinned mirrors have died, rather than hiding it behind failover."""
    cfg = live_config(NITTER_INSTANCES=instance)
    try:
        tweets = NitterRssSource(cfg).fetch("santtiagom_")
    except SourceUnavailable as exc:
        pytest.skip(f"{instance} is currently unavailable: {exc}")
    assert tweets


def test_real_telegram_delivery():
    """Sends one real message. Runs only with TELEGRAM_LIVE=1 and real credentials, so
    a plain `-m live` run can never message the operator by accident (002 follow-up)."""
    import os
    if os.environ.get("TELEGRAM_LIVE") != "1":
        pytest.skip("set TELEGRAM_LIVE=1 to send a real message")
    from tweet_relay.cli import _bot
    cfg = Config()
    cfg.require_delivery()
    bot = _bot(cfg)
    assert bot.chat_is_private()
    bot.send("🧪 tweet-relay integration test")
