"""Operator-supplied addresses must not become a request to internal infrastructure."""
import pytest
from tweet_relay.config import Config, extract_handle

BASE = dict(X_PROFILE_URL="@santtiagom_", CALLMEBOT_PHONE="+34600111222",
            CALLMEBOT_APIKEY="k")


@pytest.mark.parametrize("target", [
    "http://169.254.169.254/latest/meta-data/",      # AWS/GCP metadata
    "https://169.254.169.254",
    "http://metadata.google.internal/",
    "file:///etc/passwd",
    "gopher://127.0.0.1:6379/_FLUSHALL",
    "http://localhost:22",
    "https://127.0.0.1",
    "https://0.0.0.0",
    "https://10.0.0.5",
    "https://192.168.1.1",
    "https://172.16.0.1",
    "https://[::1]",
    "http://nitter.kareem.one",                       # plain http
    "ftp://nitter.kareem.one",
    "not-a-url",
    "//evil.example.com",
])
def test_dangerous_instance_addresses_are_refused(target):
    with pytest.raises(ValueError):
        Config(**BASE, NITTER_INSTANCES=target)


def test_one_bad_entry_rejects_the_whole_list():
    """Fail closed: a list containing a dangerous entry is not silently filtered."""
    with pytest.raises(ValueError):
        Config(**BASE, NITTER_INSTANCES="https://nitter.example.com,http://127.0.0.1")


@pytest.mark.parametrize("target", [
    "https://x.com/../../admin",
    "https://x.com/%2e%2e/admin",
    "https://evil.example.com/santtiagom_",
    "@../../etc/passwd",
    "santtiagom_/../../admin",
    "@santtiagom_%00",
    "@a b",
])
def test_profile_identifier_cannot_escape_the_path(target):
    """E-20: the handle is interpolated into a mirror URL path."""
    with pytest.raises(ValueError):
        extract_handle(target)


def test_handle_charset_is_strictly_limited():
    for ch in "/\\?#&=%. :@\t\n":
        with pytest.raises(ValueError):
            extract_handle(f"@sant{ch}iago")
