"""Post text reaching the outbound request. The key travels in that request (FR-13)."""
import httpx, logging, pytest, respx
from urllib.parse import parse_qs, urlparse
from tweet_relay.sinks.callmebot import CallMeBotSink

API = "https://api.callmebot.com/whatsapp.php"
SECRET = "test-key-do-not-log"

PAYLOADS = [
    "&apikey=ATTACKER",
    "&phone=%2B19999999999",
    "?apikey=x&text=y",
    "#fragment&apikey=z",
    "a\nb\rc",
    "\x00null",
    "%26apikey%3Dencoded",
    "' OR 1=1 --",
    "<script>alert(1)</script>",
    "🎉" * 50,
    "../../etc/passwd",
    "text&" + "a=b&" * 50,
]


@respx.mock
@pytest.mark.parametrize("payload", PAYLOADS)
def test_text_cannot_add_or_override_parameters(config, payload):
    """E-11: whatever the post says, the request must carry exactly three params."""
    route = respx.get(API).mock(httpx.Response(200, text="Message queued"))
    CallMeBotSink(config, pace_seconds=0).send(payload)

    q = parse_qs(urlparse(str(route.calls[0].request.url)).query, keep_blank_values=True)
    assert set(q) == {"phone", "text", "apikey"}
    assert len(q["apikey"]) == 1 and q["apikey"] == [SECRET]
    assert len(q["phone"]) == 1 and q["phone"] == ["+34600111222"]
    assert len(q["text"]) == 1


@respx.mock
@pytest.mark.parametrize("payload", PAYLOADS)
def test_payloads_never_leak_the_key_into_logs(config, caplog, payload):
    from tweet_relay.logging_setup import configure
    configure("DEBUG", secrets=[SECRET])
    respx.get(API).mock(httpx.Response(200, text="Message queued"))
    with caplog.at_level(logging.DEBUG):
        CallMeBotSink(config, pace_seconds=0).send(payload)
    assert SECRET not in caplog.text


@respx.mock
def test_full_pipeline_message_cannot_forge_parameters(config):
    """The realistic path: hostile post text -> formatter -> sink."""
    from tweet_relay.formatter import render
    from tweet_relay.models import Tweet, TweetKind
    from datetime import datetime, timezone

    route = respx.get(API).mock(httpx.Response(200, text="Message queued"))
    t = Tweet(id=1, author="santtiagom_",
              text="check this &apikey=STOLEN&phone=+1999 out",
              published_at=datetime(2026, 9, 15, tzinfo=timezone.utc),
              kind=TweetKind.ORIGINAL)
    CallMeBotSink(config, pace_seconds=0).send(render(t, "santtiagom_"))

    q = parse_qs(urlparse(str(route.calls[0].request.url)).query)
    assert q["apikey"] == [SECRET] and q["phone"] == ["+34600111222"]
    assert "STOLEN" in q["text"][0]        # present as literal text, harmless
