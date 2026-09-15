"""Delivery adapter. FR-12 (never claim a false success) and FR-13 (never leak the key)."""
import httpx, logging, pytest, respx
from urllib.parse import parse_qs, urlparse
from tweet_relay.models import DeliveryFailed
from tweet_relay.sinks.callmebot import CallMeBotSink

API = "https://api.callmebot.com/whatsapp.php"


def sink(config, **kw):
    return CallMeBotSink(config, pace_seconds=0, **kw)


@respx.mock
def test_sends_with_encoded_parameters(config):
    route = respx.get(API).mock(httpx.Response(200, text="Message queued"))
    sink(config).send("hello world")
    q = parse_qs(urlparse(str(route.calls[0].request.url)).query)
    assert q["text"] == ["hello world"]
    assert q["phone"] == ["+34600111222"]


@respx.mock
def test_text_cannot_inject_extra_parameters(config):
    """E-11: a post whose text contains query syntax must stay a single value."""
    route = respx.get(API).mock(httpx.Response(200, text="Message queued"))
    hostile = "pwned&apikey=STOLEN&phone=+9999999999#frag"
    sink(config).send(hostile)
    q = parse_qs(urlparse(str(route.calls[0].request.url)).query)
    assert q["text"] == [hostile], "text must survive as exactly one opaque value"
    assert q["apikey"] == ["test-key-do-not-log"]
    assert q["phone"] == ["+34600111222"]
    assert len(q["apikey"]) == 1 and len(q["phone"]) == 1


@respx.mock
def test_newlines_survive_as_one_parameter(config):
    route = respx.get(API).mock(httpx.Response(200, text="Message queued"))
    sink(config).send("line1\nline2\n\nline3")
    q = parse_qs(urlparse(str(route.calls[0].request.url)).query)
    assert q["text"] == ["line1\nline2\n\nline3"]


@respx.mock
@pytest.mark.parametrize("body", [
    "ERROR: APIKey is invalid",
    "You must provide a valid APIKey",
    "error: phone not registered",
])
def test_http_200_with_error_body_is_a_failure(config, body):
    """E-19/R-3: CallMeBot reports some failures inside a 200 response. Treating
    those as success would mark posts delivered that never arrived."""
    respx.get(API).mock(httpx.Response(200, text=body))
    with pytest.raises(DeliveryFailed):
        sink(config).send("hi")


@respx.mock
def test_retries_server_errors_then_gives_up(config):
    route = respx.get(API).mock(httpx.Response(503))
    with pytest.raises(DeliveryFailed):
        sink(config, max_attempts=3).send("hi")
    assert route.call_count == 3


@respx.mock
def test_recovers_when_a_retry_succeeds(config):
    respx.get(API).mock(side_effect=[httpx.Response(503),
                                     httpx.Response(200, text="Message queued")])
    sink(config, max_attempts=3).send("hi")   # must not raise


@respx.mock
def test_timeout_is_retried_then_raises(config):
    respx.get(API).mock(side_effect=httpx.ReadTimeout("slow"))
    with pytest.raises(DeliveryFailed):
        sink(config, max_attempts=2).send("hi")


@respx.mock
def test_apikey_never_reaches_logs_or_exceptions(config, caplog):
    """FR-13, asserted rather than assumed."""
    secret = "test-key-do-not-log"
    respx.get(API).mock(httpx.Response(500, text=f"failed with {secret}"))
    with caplog.at_level(logging.DEBUG):
        with pytest.raises(DeliveryFailed) as exc:
            sink(config, max_attempts=1).send("hi")
    assert secret not in str(exc.value)
    assert secret not in caplog.text
    assert secret not in repr(sink(config))


@respx.mock
def test_console_sink_never_fails(config, capsys):
    from tweet_relay.sinks.console import ConsoleSink
    ConsoleSink().send("dry run message")
    assert "dry run message" in capsys.readouterr().out


def test_httpx_request_logging_cannot_leak_the_key(config, caplog):
    """Regression: httpx logs full request URLs at INFO, and the key is a query
    parameter. Found by the FR-13 assertion above, fixed in logging_setup."""
    import logging as _l
    from tweet_relay.logging_setup import configure
    secret = config.CALLMEBOT_APIKEY.get_secret_value()
    configure("DEBUG", secrets=[secret])
    logger = _l.getLogger("httpx")
    with caplog.at_level(_l.DEBUG):
        logger.warning("HTTP Request: GET %s", f"https://api.callmebot.com/x?apikey={secret}")
        _l.getLogger("tweet_relay.x").error("boom apikey=%s", secret)
    assert secret not in caplog.text


def test_redaction_covers_url_encoded_form():
    from tweet_relay.logging_setup import SecretRedactingFilter
    f = SecretRedactingFilter(["a b/c+d"])
    rec = logging.LogRecord("n", logging.INFO, "p", 1, "url=a%20b%2Fc%2Bd", None, None)
    f.filter(rec)
    assert "a%20b%2Fc%2Bd" not in rec.getMessage()
