"""Bot chat adapter (spec 003; contracts message-sink.md and command-inbox.md).

Fixtures in tests/fixtures/telegram: 401/404 bodies observed 2026-10-21, the rest
built from the documented shapes (research R-3).
"""
import json
import pathlib

import httpx
import pytest
import respx

from tweet_relay.models import DeliveryFailed, InboxUnavailable, MessageRejected
from tweet_relay.sinks.telegram import TelegramBot

FIX = pathlib.Path(__file__).parent.parent / "fixtures" / "telegram"
TOKEN = "123456789:TEST-token-do-not-log-AAAAAAAAAAAAAAAAAA"
CHAT = "111222333"
API = f"https://api.telegram.org/bot{TOKEN}"


def fx(name: str) -> dict:
    return json.loads((FIX / name).read_text())


def reply(name: str, status: int | None = None) -> httpx.Response:
    body = fx(name)
    return httpx.Response(status or body.get("error_code", 200), json=body)


class FakeClock:
    def __init__(self):
        self.now, self.slept = 0.0, []

    def monotonic(self):
        return self.now

    def sleep(self, s):
        self.slept.append(s)
        self.now += s


def bot(clock=None, **kw):
    clock = clock or FakeClock()
    return TelegramBot(TOKEN, CHAT, timeout=5, sleep=clock.sleep,
                       monotonic=clock.monotonic, **kw)


# ---------- T012: sending ----------

@respx.mock
def test_send_posts_plain_text_with_the_card_url():
    """FR-2, 001 E-11: JSON body, no parse_mode, card from the go-between (DD-4)."""
    route = respx.post(f"{API}/sendMessage").mock(reply("send_ok.json"))
    bot().send("hola <b>*x*</b>", preview_url="https://fxtwitter.com/a/status/1")
    body = json.loads(route.calls[0].request.content)
    assert body == {"chat_id": CHAT, "text": "hola <b>*x*</b>",
                    "link_preview_options": {"url": "https://fxtwitter.com/a/status/1"}}


@respx.mock
def test_send_without_a_card():
    route = respx.post(f"{API}/sendMessage").mock(reply("send_ok.json"))
    bot().send("notice")
    assert "link_preview_options" not in json.loads(route.calls[0].request.content)


@pytest.mark.parametrize("response", [
    httpx.Response(200, json={"ok": True, "result": {}}),                 # no message_id
    httpx.Response(200, json={"ok": True, "result": {"message_id": "42"}}),
    httpx.Response(200, json={"ok": True, "result": {"message_id": True}}),
    httpx.Response(200, json={"ok": False}),
    httpx.Response(200, text="<html>hello</html>"),
    httpx.Response(200, text=""),
])
@respx.mock
def test_only_a_confirmed_message_counts_as_delivered(response):
    """FR-5, contract 1: anything but ok + integer message_id is a failure."""
    respx.post(f"{API}/sendMessage").mock(response)
    with pytest.raises(DeliveryFailed):
        bot(max_attempts=1).send("x")


# ---------- T014: error classification (contract message-sink 5-7) ----------

@pytest.mark.parametrize("name", ["unauthorized_401.json", "not_found_404.json",
                                  "blocked_403.json", "chat_not_found_400.json"])
@respx.mock
def test_chat_and_bot_problems_are_channel_failures(name):
    """E-12, E-13: never MessageRejected, so no minimal-form retry adds traffic."""
    route = respx.post(f"{API}/sendMessage").mock(reply(name))
    with pytest.raises(DeliveryFailed) as err:
        bot().send("x")
    assert not isinstance(err.value, MessageRejected)
    assert route.call_count == 1, "a refusal is not retried"


@respx.mock
def test_a_rejected_token_says_so():
    """E-13: the operator can tell what to fix, without the token being shown."""
    respx.post(f"{API}/sendMessage").mock(reply("unauthorized_401.json"))
    with pytest.raises(DeliveryFailed, match="token was rejected"):
        bot().send("x")


@respx.mock
def test_a_blocked_bot_says_so():
    respx.post(f"{API}/sendMessage").mock(reply("blocked_403.json"))
    with pytest.raises(DeliveryFailed, match="blocked"):
        bot().send("x")


@respx.mock
def test_a_refused_message_is_message_rejected():
    """001 E-21 / D-4: only this message was refused, so the minimal form may help."""
    respx.post(f"{API}/sendMessage").mock(reply("too_long_400.json"))
    with pytest.raises(MessageRejected):
        bot().send("x")


@respx.mock
def test_flood_control_waits_once_when_short():
    clock = FakeClock()
    route = respx.post(f"{API}/sendMessage").mock(
        side_effect=[reply("flood_429.json"), reply("send_ok.json")])
    bot(clock).send("x")
    assert route.call_count == 2 and 2 in clock.slept


@respx.mock
def test_flood_control_gives_up_when_long():
    body = fx("flood_429.json")
    body["parameters"]["retry_after"] = 120
    clock = FakeClock()
    route = respx.post(f"{API}/sendMessage").mock(httpx.Response(429, json=body))
    with pytest.raises(DeliveryFailed):
        bot(clock).send("x")
    assert route.call_count == 1 and 120 not in clock.slept


@respx.mock
def test_server_errors_and_timeouts_are_retried_then_fail():
    clock = FakeClock()
    route = respx.post(f"{API}/sendMessage").mock(
        side_effect=[httpx.Response(502), httpx.ReadTimeout("t"), httpx.Response(500)])
    with pytest.raises(DeliveryFailed):
        bot(clock, max_attempts=3).send("x")
    assert route.call_count == 3 and len(clock.slept) >= 2


@respx.mock
def test_a_transient_error_then_success_delivers():
    route = respx.post(f"{API}/sendMessage").mock(
        side_effect=[httpx.ConnectError("c"), reply("send_ok.json")])
    bot().send("x")
    assert route.call_count == 2


@respx.mock
def test_sends_are_paced_one_second_apart():
    """Contract 5: about one message per second per chat (research R-2)."""
    clock = FakeClock()
    respx.post(f"{API}/sendMessage").mock(reply("send_ok.json"))
    b = bot(clock)
    b.send("a")
    b.send("b")
    assert clock.now >= 1.0


# ---------- T016: the configured chat is a private one-to-one chat (D-4) ----------

@respx.mock
def test_private_chat_is_recognised():
    route = respx.post(f"{API}/getChat").mock(reply("get_chat_private.json"))
    assert bot().chat_is_private() is True
    assert json.loads(route.calls[0].request.content) == {"chat_id": CHAT}


@respx.mock
def test_group_or_channel_is_not_private():
    """E-14: posts and status must never go to a group or channel."""
    respx.post(f"{API}/getChat").mock(reply("get_chat_group.json"))
    assert bot().chat_is_private() is False


@pytest.mark.parametrize("response", [
    reply("chat_not_found_400.json"),
    httpx.Response(200, json={"ok": True, "result": {"type": 5}}),
    httpx.Response(200, json={"ok": True, "result": "private"}),
])
@respx.mock
def test_a_chat_check_that_cannot_be_answered_fails(response):
    respx.post(f"{API}/getChat").mock(response)
    with pytest.raises(DeliveryFailed):
        bot(max_attempts=1).chat_is_private()


# ---------- T020: reading the operator's messages (contract command-inbox) ----------

@respx.mock
def test_read_asks_only_for_new_messages_without_waiting():
    route = respx.post(f"{API}/getUpdates").mock(
        httpx.Response(200, json={"ok": True, "result": []}))
    batch = bot().read(1000)
    assert json.loads(route.calls[0].request.content) == {
        "offset": 1000, "limit": 100, "timeout": 0, "allowed_updates": ["message"]}
    assert batch.messages == [] and batch.next_offset == 1000


@respx.mock
def test_read_returns_valid_messages_and_moves_past_everything_seen():
    respx.post(f"{API}/getUpdates").mock(reply("updates_mixed.json"))
    batch = bot().read(1000)
    got = [(m.update_id, m.chat_id, m.chat_type, m.text) for m in batch.messages]
    assert got == [
        (1001, 111222333, "private", "/status"),
        (1002, 999888777, "private", "/pause"),       # the adapter does not filter (6)
        (1003, 111222333, "private", ""),             # sticker: no text
        (1005, 111222333, "private", "/Pause now"),
        (1006, 111222333, "group", "/resume"),
    ]
    # 1004 is an edit and the next has no update_id: skipped, never block the queue.
    assert batch.next_offset == 1007


@respx.mock
def test_long_text_is_cut_before_it_leaves_the_adapter():
    body = {"ok": True, "result": [{"update_id": 5, "message": {
        "message_id": 1, "chat": {"id": 1, "type": "private"}, "text": "/help" + "x" * 10_000}}]}
    respx.post(f"{API}/getUpdates").mock(httpx.Response(200, json=body))
    assert len(bot().read(0).messages[0].text) == 4096


@pytest.mark.parametrize("update", [
    {"update_id": True, "message": {"chat": {"id": 1, "type": "private"}, "text": "x"}},
    {"update_id": 7, "message": {"chat": {"id": "1", "type": "private"}, "text": "x"}},
    {"update_id": 7, "message": {"chat": {"id": True, "type": "private"}, "text": "x"}},
    {"update_id": 7, "message": {"chat": {"id": 1, "type": 3}, "text": "x"}},
    {"update_id": 7, "message": {"chat": {"id": 1, "type": "private"}, "text": ["x"]}},
    {"update_id": 7, "message": "nope"},
    {"update_id": -3, "message": {"chat": {"id": 1, "type": "private"}, "text": "x"}},
    "not an object",
])
@respx.mock
def test_malformed_updates_are_skipped(update):
    respx.post(f"{API}/getUpdates").mock(
        httpx.Response(200, json={"ok": True, "result": [update]}))
    assert bot().read(0).messages == []


@pytest.mark.parametrize("response", [
    httpx.Response(200, text="<html>"),
    httpx.Response(200, json={"ok": True, "result": {"not": "a list"}}),
    httpx.Response(200, json={"ok": True}),
    httpx.Response(409, json={"ok": False, "error_code": 409,
                              "description": "Conflict: can't use getUpdates method while webhook is active"}),
    httpx.Response(200, content=b'{"ok": true, "result": [' + b" " * (1 << 20) + b"]}"),
])
@respx.mock
def test_an_unusable_answer_is_inbox_unavailable(response):
    respx.post(f"{API}/getUpdates").mock(response)
    with pytest.raises(InboxUnavailable):
        bot(max_attempts=1).read(0)
