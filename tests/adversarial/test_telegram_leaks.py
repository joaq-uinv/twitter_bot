"""The bot token and the operator's chat id must never escape (spec 003 FR-16, §6).

The token sits in the request path (research R-3), and httpx names the URL in its
exception messages, so every error path is forced here with marker values and checked
in the exception text, its repr, the formatted traceback and the logs at every level.
The root redaction filter is not configured: the adapter must not depend on it.
"""
import json
import logging
import pathlib
import traceback
from urllib.parse import quote

import httpx
import pytest
import respx

from tweet_relay.models import DeliveryFailed
from tweet_relay.sinks.telegram import TelegramBot

FIX = pathlib.Path(__file__).parent.parent / "fixtures" / "telegram"
TOKEN = "987654321:LEAKMARKER-token-AAAAAAAAAAAAAAAAAAAAAA"
CHAT = "424242424242"
API = f"https://api.telegram.org/bot{TOKEN}"
FORMS = [TOKEN, quote(TOKEN, safe=""), TOKEN.split(":")[1], CHAT]


def fixture(name):
    body = json.loads((FIX / name).read_text())
    return httpx.Response(body.get("error_code", 200), json=body)


def echoing(status, extra=""):
    return httpx.Response(status, json={"ok": False, "error_code": status,
                                        "description": f"Bad Request: {TOKEN} {CHAT} {extra}"})


ERRORS = [
    *[pytest.param(fixture(n), id=n) for n in
      ("unauthorized_401.json", "not_found_404.json", "blocked_403.json",
       "chat_not_found_400.json", "too_long_400.json", "flood_429.json")],
    pytest.param(httpx.ConnectError(f"cannot connect to {API}/sendMessage"), id="connect"),
    pytest.param(httpx.ReadTimeout(f"timed out reading {API}/sendMessage"), id="timeout"),
    pytest.param(httpx.Response(400, text="x" * 1_000_000 + TOKEN), id="huge-non-json"),
    pytest.param(echoing(400), id="400-echo"),
    pytest.param(echoing(403), id="403-echo"),
    pytest.param(echoing(400, "x" * 190), id="400-echo-truncated"),
    pytest.param(httpx.Response(200, json={"ok": True, "result": {"echo": TOKEN}}),
                 id="2xx-echo"),
]


def leaked(text: str) -> list[str]:
    return [f for f in FORMS if f in text]


def bot():
    return TelegramBot(TOKEN, CHAT, timeout=1, max_attempts=2, sleep=lambda s: None,
                       monotonic=lambda: 0.0)


@respx.mock
@pytest.mark.parametrize("answer", ERRORS)
def test_no_send_failure_reveals_the_token_or_chat(answer, caplog):
    respx.post(f"{API}/sendMessage").mock(side_effect=[answer, answer])
    with caplog.at_level(logging.DEBUG):
        with pytest.raises(DeliveryFailed) as err:
            bot().send("hello")
    shown = "\n".join([str(err.value), repr(err.value),
                       "".join(traceback.format_exception(err.value)), caplog.text])
    assert leaked(shown) == []


@respx.mock
@pytest.mark.parametrize("answer", ERRORS)
def test_no_chat_check_failure_reveals_the_token_or_chat(answer, caplog):
    respx.post(f"{API}/getChat").mock(side_effect=[answer, answer])
    with caplog.at_level(logging.DEBUG):
        try:
            bot().chat_is_private()
        except DeliveryFailed as exc:
            shown = "\n".join([str(exc), repr(exc), "".join(traceback.format_exception(exc))])
        else:
            shown = ""
    assert leaked(shown + caplog.text) == []


def test_the_adapter_renders_without_secrets():
    assert leaked(repr(bot()) + str(bot())) == []


# ---------- T022/T034: nothing a stranger writes reaches a log or report (AC-6.1) ----------

def test_a_strangers_message_never_reaches_logs_or_the_summary(config, caplog):
    from tests.doubles import OPERATOR, FakeSource, RecordingSink, ScriptedInbox, batch, msg, tweet
    from tweet_relay.pipeline import Pipeline
    from tweet_relay.report import render_summary
    from tweet_relay.state import RelayState, save_state

    marker = "STRANGERMARK"
    fake_line = "2026-10-21 12:00:00,000 INFO    tweet_relay.pipeline: delivered tweet_id=1"
    stranger = 555666777
    save_state(config.STATE_PATH, RelayState(handle="santtiagom_", seen_ids=[1],
                                             bootstrapped=True, announced=True))
    inbox = ScriptedInbox(batch(
        msg(1, f"/pause {marker}", chat_id=stranger),
        msg(2, f"{fake_line}\n{TOKEN}", chat_id=stranger),
        msg(3, f"/status {marker}"),                     # the operator: handled, not echoed
    ))
    sink = RecordingSink()
    with caplog.at_level(logging.DEBUG):
        result = Pipeline(config, FakeSource([tweet(1), tweet(2, minutes=2)]), sink,
                          inbox=inbox, operator_chat_id=OPERATOR).run_once()
    line = (f"sent={result.sent} withheld={result.withheld} failed={result.failed} "
            f"bootstrapped={result.bootstrapped} outage={result.outage} dry_run=False")
    log_text = caplog.text
    summary = render_summary(log_text + "\n" + line + "\n", 0, None, "santtiagom_")
    for shown in (log_text, summary, "\n".join(sink.sent)):
        assert marker not in shown and str(stranger) not in shown
        assert TOKEN not in shown and "tweet_id=1" not in shown
    assert result.sent == 1 and not result.paused
