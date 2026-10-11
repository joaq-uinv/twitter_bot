"""The probe checks a host's addresses before connecting (spec 002 FR-11, plan DD-4).

A hostile list can name a host that resolves to the runner's own network. The probe
must refuse it without making any request.
"""
import socket

import httpx
import pytest
import respx

from tweet_relay import config as config_module
from tweet_relay.mirrors.models import Reason
from tweet_relay.mirrors.probe import HttpMirrorProbe


@pytest.mark.parametrize("ip", ["169.254.169.254", "10.0.0.5", "127.0.0.1", "100.64.0.1", "::1"])
@respx.mock
def test_non_global_host_is_refused_without_any_request(monkeypatch, config, ip):
    monkeypatch.setattr(config_module.socket, "getaddrinfo",
                        lambda h, p, *a, **k: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, p))])
    route = respx.get(url__regex=r".*").mock(httpx.Response(200))
    outcome = HttpMirrorProbe(config).probe("evil.example", "santtiagom_")
    assert outcome.usable is False
    assert outcome.reason is Reason.REFUSED_ADDRESS
    assert outcome.ms is None
    assert route.call_count == 0
