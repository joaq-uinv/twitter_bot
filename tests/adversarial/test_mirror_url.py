"""validate_mirror_url: the one strict gate for every mirror address (spec 002 FR-11,
plan DD-3). It covers configured mirrors and every entry a hostile list may name.

DNS is monkeypatched: no network in these tests (§5).
"""
import socket

import pytest

from tweet_relay import config as config_module
from tweet_relay.config import DEFAULT_INSTANCES, validate_mirror_url


def _resolves_to(monkeypatch, *ips):
    def fake(host, port, *a, **kw):
        return [(socket.AF_INET6 if ":" in ip else socket.AF_INET, socket.SOCK_STREAM, 6, "",
                 (ip, port)) for ip in ips]
    monkeypatch.setattr(config_module.socket, "getaddrinfo", fake)


@pytest.fixture
def public_dns(monkeypatch):
    _resolves_to(monkeypatch, "93.184.216.34")


@pytest.mark.parametrize("url", [
    "http://nitter.pp.ua",                    # not https
    "https://user:pw@nitter.pp.ua",           # userinfo
    "https://nitter.pp.ua@evil.example",      # userinfo trick
    "https://nitter.pp.ua:8443",              # port
    "https://nitter.pp.ua:443",               # even the default port, written out
    "https://nitter.pp.ua/admin",             # path
    "https://nitter.pp.ua/?x=1",              # query
    "https://nitter.pp.ua/#frag",             # fragment
    "https://93.184.216.34",                  # IPv4 literal
    "https://[2606:2800:220:1::248]",         # IPv6 literal
    "https://nitter_pp.ua",                   # underscore
    "https://-nitter.pp.ua",                  # label starts with hyphen
    "https://" + "a" * 64 + ".example",       # label over 63
    "https://" + ("a" * 60 + ".") * 5 + "example",   # name over 253
    "https://localhost",                      # single label
    "https://",                               # empty host
    "https:nitter.pp.ua",
])
def test_malformed_addresses_are_refused(public_dns, url):
    with pytest.raises(ValueError):
        validate_mirror_url(url)


@pytest.mark.parametrize("ip", [
    "100.64.0.1",          # CGNAT: is_private is False in Python 3.12 (research R-3)
    "169.254.169.254",     # cloud metadata, link-local
    "10.0.0.5", "192.168.1.1", "172.16.0.1", "127.0.0.1", "0.0.0.0",
    "192.0.2.10",          # documentation range
    "::1", "fd00::1", "fe80::1",
])
def test_hosts_resolving_to_non_global_addresses_are_refused(monkeypatch, ip):
    _resolves_to(monkeypatch, ip)
    with pytest.raises(ValueError):
        validate_mirror_url("https://nitter.pp.ua")


def test_any_non_global_address_among_several_is_refused(monkeypatch):
    _resolves_to(monkeypatch, "93.184.216.34", "10.0.0.5")
    with pytest.raises(ValueError):
        validate_mirror_url("https://nitter.pp.ua")


@pytest.mark.parametrize("url", DEFAULT_INSTANCES)
def test_default_instances_are_accepted(public_dns, url):
    assert validate_mirror_url(url) == url


def test_result_is_canonical(public_dns):
    assert validate_mirror_url("https://Nitter.PP.ua/") == "https://nitter.pp.ua"


def test_punycode_host_is_accepted(public_dns):
    assert validate_mirror_url("https://xn--nttr-6qa.example") == "https://xn--nttr-6qa.example"


def test_unresolvable_host_is_accepted_and_fails_later(monkeypatch):
    """Existing 001 behaviour: the fetcher fails safely on a name that does not resolve."""
    def nx(*a, **kw):
        raise socket.gaierror("NXDOMAIN")
    monkeypatch.setattr(config_module.socket, "getaddrinfo", nx)
    assert validate_mirror_url("https://a.example.com") == "https://a.example.com"
