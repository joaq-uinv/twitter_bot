"""StatusD420Directory: the community list is hostile input (spec 002 FR-11, FR-12,
FR-16, E-11; contract mirror-directory.md). DNS is monkeypatched (§5)."""
import json
import pathlib
import socket

import httpx
import pytest
import respx

from tweet_relay import config as config_module
from tweet_relay.mirrors.directory import DirectoryUnavailable, StatusD420Directory

FIX = pathlib.Path(__file__).parent.parent / "fixtures" / "mirrors" / "d420_instances.json"
URL = StatusD420Directory.URL
REAL = json.loads(FIX.read_text())


@pytest.fixture(autouse=True)
def dns(monkeypatch):
    """Everything public, except hosts named *.internal-test."""
    def fake(host, port, *a, **kw):
        ip = "10.0.0.5" if host.endswith(".internal-test") else "93.184.216.34"
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, port))]
    monkeypatch.setattr(config_module.socket, "getaddrinfo", fake)


def _read(config, payload=None, *, raw=None, status=200, headers=None):
    body = raw if raw is not None else json.dumps(payload).encode()
    respx.get(URL).mock(httpx.Response(status, content=body, headers=headers))
    return StatusD420Directory(config).list()


def entry(domain, url=None):
    return {"domain": domain, "url": url or f"https://{domain}", "healthy": True,
            "rss": True, "country": "<script>alert(1)</script>", "version": "x"}


@respx.mock
def test_real_list_yields_its_hosts(config):
    read = _read(config, REAL)
    assert read.hosts == [e["domain"] for e in REAL["hosts"]]
    assert (read.accepted, read.rejected) == (len(REAL["hosts"]), 0)


@respx.mock
def test_only_hosts_are_returned(config):
    """FR-16: no other field from the list survives."""
    read = _read(config, {"hosts": [entry("nitter.pp.ua")]})
    assert read.hosts == ["nitter.pp.ua"]
    assert all(isinstance(h, str) and "<" not in h for h in read.hosts)


@respx.mock
@pytest.mark.parametrize("bad", [
    entry("nitter.pp.ua", url="http://nitter.pp.ua"),            # not https
    entry("nitter.pp.ua", url="https://other.example"),          # domain/url disagree
    entry("nitter.pp.ua", url="https://nitter.pp.ua:8443"),      # port
    entry("cgnat.internal-test"),                                # non-global address
    {"domain": "nitter.pp.ua"},                                  # url missing
    {"url": 42, "domain": "nitter.pp.ua"},                       # wrong type
    "https://nitter.pp.ua",                                      # not an object
])
def test_bad_entries_are_dropped_one_at_a_time(config, bad):
    """FR-12: one bad entry never rejects the rest."""
    read = _read(config, {"hosts": [entry("good.example"), bad, entry("also-good.example")]})
    assert read.hosts == ["good.example", "also-good.example"]
    assert read.rejected == 1


@respx.mock
def test_duplicates_are_removed(config):
    read = _read(config, {"hosts": [entry("a.example"), entry("A.example"), entry("a.example")]})
    assert read.hosts == ["a.example"]


@respx.mock
@pytest.mark.parametrize("raw", [
    b"not json at all",
    b"[]",                                    # wrong top-level shape
    b'{"instances": []}',                    # missing hosts
    b'{"hosts": "nope"}',
])
def test_unreadable_document_is_unavailable(config, raw):
    with pytest.raises(DirectoryUnavailable):
        _read(config, raw=raw)


@respx.mock
def test_oversized_document_is_unavailable(config):
    with pytest.raises(DirectoryUnavailable):
        _read(config, raw=b" " * (StatusD420Directory.MAX_BYTES + 1))


@respx.mock
def test_absurdly_long_list_is_rejected_whole(config):
    with pytest.raises(DirectoryUnavailable):
        _read(config, {"hosts": [entry(f"h{i}.example") for i in range(1001)]})


@respx.mock
@pytest.mark.parametrize("status,headers", [(302, {"location": "https://evil.example"}), (503, None)])
def test_non_success_answers_are_unavailable(config, status, headers):
    with pytest.raises(DirectoryUnavailable):
        _read(config, raw=b"", status=status, headers=headers)


@respx.mock
def test_network_failure_is_unavailable(config):
    respx.get(URL).mock(side_effect=httpx.ConnectError("down"))
    with pytest.raises(DirectoryUnavailable):
        StatusD420Directory(config).list()
