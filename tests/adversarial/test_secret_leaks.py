"""The key must not escape through anything the service sends back (FR-13, §6).

test_injection.py covers what *we* send. This covers the other direction: a 2xx body
is quoted into the failure reason so the operator can see why delivery failed (§7),
which makes the response body a path from the network into exception text and logs.
The service is third-party; if it ever echoes the key, that must stop at the sink.

These assertions do not call logging_setup.configure(): the root redaction filter is
a backstop, and the sink must not depend on it.
"""
import html, httpx, logging, pathlib, pytest, respx
from urllib.parse import quote
from pydantic import SecretStr
from tweet_relay.models import DeliveryFailed
from tweet_relay.sinks.callmebot import CallMeBotSink

API = "https://api.callmebot.com/whatsapp.php"
# Characters that change under URL-encoding and HTML-escaping, so every form differs.
KEY = "k3y/with+special=&<chars>"
FORMS = [KEY, quote(KEY, safe=""), html.escape(KEY)]
PAUSED = (pathlib.Path(__file__).parent.parent / "fixtures" / "callmebot_paused.html").read_text()


@pytest.fixture
def keyed(config):
    return config.model_copy(update={"CALLMEBOT_APIKEY": SecretStr(KEY)})


def leaked(text: str) -> list[str]:
    return [f for f in FORMS if f in text]


BODIES = [
    pytest.param(200, f"ERROR: APIKey {form} is invalid", id=f"error-{i}")
    for i, form in enumerate(FORMS)
] + [
    pytest.param(200, f"<p>unknown request for key {form}</p>", id=f"unrecognised-{i}")
    for i, form in enumerate(FORMS)
] + [
    pytest.param(208, PAUSED.replace("{text}", "hi") + f"<p>apikey={form}</p>", id=f"paused-{i}")
    for i, form in enumerate(FORMS)
]


@respx.mock
@pytest.mark.parametrize("status,body", BODIES)
def test_key_echoed_by_the_service_never_reaches_the_exception(keyed, status, body):
    respx.get(API).mock(httpx.Response(status, text=body))
    with pytest.raises(DeliveryFailed) as exc:
        CallMeBotSink(keyed, pace_seconds=0, max_attempts=1).send("hi")
    assert leaked(str(exc.value)) == []
    assert leaked(repr(exc.value)) == []


@respx.mock
@pytest.mark.parametrize("status,body", BODIES)
def test_key_echoed_by_the_service_never_reaches_the_logs(keyed, caplog, status, body):
    """The pipeline logs the exception on every failed send, at ERROR."""
    respx.get(API).mock(httpx.Response(status, text=body))
    with caplog.at_level(logging.DEBUG):
        try:
            CallMeBotSink(keyed, pace_seconds=0, max_attempts=1).send("hi")
        except DeliveryFailed as exc:
            logging.getLogger("tweet_relay.pipeline").error("delivery failed: %s", exc)
    assert leaked(caplog.text) == []


@respx.mock
def test_key_cannot_be_half_revealed_by_truncation(keyed):
    """A reason cut to length after the key was found would leak its prefix."""
    padding = "x" * 190
    respx.get(API).mock(httpx.Response(200, text=f"ERROR {padding} {KEY} {padding}"))
    with pytest.raises(DeliveryFailed) as exc:
        CallMeBotSink(keyed, pace_seconds=0, max_attempts=1).send("hi")
    assert KEY[:6] not in str(exc.value)


@respx.mock
def test_transport_error_naming_the_url_does_not_leak_the_key(keyed):
    """httpx errors can carry the request, whose URL holds the key as a parameter."""
    respx.get(API).mock(side_effect=httpx.ConnectError(f"cannot reach {API}?apikey={quote(KEY)}"))
    with pytest.raises(DeliveryFailed) as exc:
        CallMeBotSink(keyed, pace_seconds=0, max_attempts=1).send("hi")
    assert leaked(str(exc.value)) == []


def test_config_renders_without_the_key(keyed):
    for rendering in (repr(keyed), str(keyed), keyed.model_dump_json()):
        assert leaked(rendering) == []


# --- the phone number (plan A-9) ---
#
# The service's reply begins "Message to: <phone>". Locally that is harmless; but run
# logs are now copied into the run summary and to the uptime monitor, and GitHub only
# masks secrets in its own log viewer, not in files a step writes. The repo is public.

PHONE = "+34600111222"
PHONE_FORMS = [PHONE, PHONE.lstrip("+"), quote(PHONE, safe="")]


@respx.mock
@pytest.mark.parametrize("status,body", [
    (200, f"<p>Message to: {PHONE}<p>Text to send: hi<p>ERROR: something"),
    (200, f"<p>Message to: {PHONE.lstrip('+')}<p>Text to send: hi<p>no idea"),
    (208, PAUSED.replace("{text}", "hi")),
])
def test_phone_number_never_reaches_the_failure_reason(config, status, body):
    respx.get(API).mock(httpx.Response(status, text=body))
    with pytest.raises(DeliveryFailed) as exc:
        CallMeBotSink(config, pace_seconds=0, max_attempts=1).send("hi")
    assert [f for f in PHONE_FORMS if f in str(exc.value)] == []
