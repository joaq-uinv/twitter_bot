import pytest
from tweet_relay.config import Config, extract_handle

BASE = dict(CALLMEBOT_PHONE="+34600111222", CALLMEBOT_APIKEY="secret123")


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


@pytest.mark.parametrize("bad", ["600111222", "+0600111222", "abc", "+3460011122233444"])
def test_rejects_bad_phone(bad):
    with pytest.raises(ValueError):
        cfg(X_PROFILE_URL="@a", CALLMEBOT_PHONE=bad)


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


def test_apikey_not_in_repr():
    """FR-13: the key must not leak through an object repr into a traceback."""
    c = cfg(X_PROFILE_URL="@a", CALLMEBOT_APIKEY="SUPERSECRET")
    assert "SUPERSECRET" not in repr(c)
    assert "SUPERSECRET" not in str(c)
