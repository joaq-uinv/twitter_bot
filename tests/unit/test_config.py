import pytest
from tweet_relay.config import Config, extract_handle

TOKEN = "123456789:TEST-token-do-not-log-AAAAAAAAAAAAAAAAAA"
BASE = dict(TELEGRAM_BOT_TOKEN=TOKEN, TELEGRAM_CHAT_ID="111222333")


def cfg(**kw):
    return Config(**{**BASE, **kw})


@pytest.mark.parametrize("raw,expected", [
    ("https://x.com/santtiagom_", "santtiagom_"),
    ("https://twitter.com/santtiagom_", "santtiagom_"),
    ("http://x.com/santtiagom_/", "santtiagom_"),
    ("https://www.x.com/santtiagom_?s=20", "santtiagom_"),
    ("@santtiagom_", "santtiagom_"),
    ("santtiagom_", "santtiagom_"),
])
def test_extracts_handle_from_accepted_forms(raw, expected):
    assert extract_handle(raw) == expected


@pytest.mark.parametrize("bad", [
    "https://evil.com/santtiagom_",          # wrong host
    "https://x.com/../../admin",             # path traversal
    "https://x.com/",                        # no handle
    "https://x.com/a b",                     # space
    "@" + "a" * 16,                          # too long
    "", "   ", "@",
    "https://x.com/santtiagom_/status/1",    # not a profile URL
])
def test_rejects_malformed_profile_identifiers(bad):
    """AC-5.2 + E-20: the handle is interpolated into a URL path, so this regex is
    also the path-injection control."""
    with pytest.raises(ValueError):
        extract_handle(bad)


def test_config_exposes_handle():
    assert cfg(X_PROFILE_URL="https://x.com/santtiagom_").handle == "santtiagom_"


def test_defaults_match_spec():
    c = cfg(X_PROFILE_URL="@a")
    assert c.include_retweets is True
    assert c.include_replies is False
    assert c.include_quotes is True          # D-1
    assert c.poll_interval_seconds == 900
    assert c.max_messages_per_run == 10
    assert len(c.instances) == 4             # the four verified mirrors


@pytest.mark.parametrize("bad", ["123", "abc:def", "123456789:short", "123456789:" + "a" * 30 + " x",
                                 "x123456789:" + "a" * 35, "123456789:" + "a" * 20 + "\n" + "a" * 15])
def test_rejects_a_malformed_bot_token_without_echoing_it(bad):
    """003 data-model: shape only; the error never contains the value (FR-16)."""
    with pytest.raises(ValueError) as err:
        cfg(X_PROFILE_URL="@a", TELEGRAM_BOT_TOKEN=bad)
    assert bad.strip() not in str(err.value) or len(bad.strip()) < 4


@pytest.mark.parametrize("bad", ["abc", "12 34", "1.5", "+1", "1" * 21])
def test_rejects_a_malformed_chat_id_without_echoing_it(bad):
    with pytest.raises(ValueError) as err:
        cfg(X_PROFILE_URL="@a", TELEGRAM_CHAT_ID=bad)
    assert bad not in str(err.value) or len(bad) < 4


def test_surrounding_whitespace_from_a_paste_is_tolerated():
    c = cfg(X_PROFILE_URL="@a", TELEGRAM_BOT_TOKEN=f" {TOKEN}\n", TELEGRAM_CHAT_ID=" 42\n")
    assert c.TELEGRAM_BOT_TOKEN.get_secret_value() == TOKEN and c.chat_id == 42


def test_chat_id_is_exposed_as_an_int():
    assert cfg(X_PROFILE_URL="@a", TELEGRAM_CHAT_ID="-100123").chat_id == -100123


def test_old_channel_settings_are_ignored():
    """003 AC-1.4: a .env that still has them must not stop the relay."""
    c = Config(X_PROFILE_URL="@a", CALLMEBOT_PHONE="+34600111222", CALLMEBOT_APIKEY="k",
               **BASE)
    c.require_delivery()
    assert not hasattr(c, "CALLMEBOT_APIKEY")


def test_status_page_must_be_https():
    with pytest.raises(ValueError):
        cfg(X_PROFILE_URL="@a", STATUS_PAGE_URL="http://example.com/")
    assert cfg(X_PROFILE_URL="@a").STATUS_PAGE_URL == "https://joaq-uinv.github.io/twitter_bot/"


@pytest.mark.parametrize("bad", [
    "http://169.254.169.254/",   # cloud metadata
    "file:///etc/passwd",
    "http://localhost:22",
    "http://127.0.0.1",
    "https://10.0.0.1",
    "https://192.168.1.1",
    "http://nitter.kareem.one",  # plain http
    "not-a-url",
])
def test_rejects_ssrf_instance_addresses(bad):
    """E-20: operator-supplied source addresses must not reach internal infrastructure."""
    with pytest.raises(ValueError):
        cfg(X_PROFILE_URL="@a", NITTER_INSTANCES=bad)


def test_accepts_valid_instance_list():
    c = cfg(X_PROFILE_URL="@a",
            NITTER_INSTANCES="https://a.example.com, https://b.example.com/")
    assert c.instances == ["https://a.example.com", "https://b.example.com"]


def test_secrets_not_in_repr():
    """FR-16: neither the token nor the chat id leaks through a repr into a traceback."""
    c = cfg(X_PROFILE_URL="@a", TELEGRAM_CHAT_ID="987654321")
    for shown in (repr(c), str(c)):
        assert TOKEN not in shown and TOKEN.split(":")[1] not in shown
        assert "987654321" not in shown


def test_delivery_credentials_may_be_blank_for_diagnostics():
    """check-source must work before delivery is configured."""
    c = Config(X_PROFILE_URL="@a")
    assert c.handle == "a"


def test_require_delivery_names_what_is_missing():
    with pytest.raises(ValueError, match="TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID"):
        Config(X_PROFILE_URL="@a").require_delivery()
    with pytest.raises(ValueError, match="TELEGRAM_CHAT_ID"):
        Config(X_PROFILE_URL="@a", TELEGRAM_BOT_TOKEN=TOKEN).require_delivery()
    cfg(X_PROFILE_URL="@a").require_delivery()   # must not raise


def test_suite_does_not_read_the_operators_dotenv():
    """Regression: a real .env once leaked credentials into tests that assert their
    absence, so the suite failed purely because the machine was configured."""
    assert Config.model_config.get("env_file") is None


def test_default_mirrors_are_the_ones_verified_on_2026_10_21():
    """001 plan A-14: pp.ua and thepixora answer 403; jaydenha and mie.foundation
    parse 19 posts through the relay's own check-source."""
    assert Config(X_PROFILE_URL="@a").instances == [
        "https://nitter.kareem.one",
        "https://nitter.mie.foundation",
        "https://nitter.jaydenha.uk",
        "https://nitter.meowing.monster",
    ]
