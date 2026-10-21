"""Post text reaching the outbound request, which carries the bot token (FR-16, E-11).

The text is one JSON string field, never interpolated into the URL, and sent without
any formatting mode, so nothing a post says can add a field, change the chat, change
the endpoint, or turn on markup.
"""
import json
import logging
from datetime import datetime, timezone

import httpx
import pytest
import respx

from tweet_relay.sinks.telegram import TelegramBot

TOKEN = "123456789:TEST-token-do-not-log-AAAAAAAAAAAAAAAAAA"
CHAT = "111222333"
SEND = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
OK = httpx.Response(200, json={"ok": True, "result": {"message_id": 1}})

PAYLOADS = [
    '", "chat_id": "666", "parse_mode": "HTML',
    '{"chat_id": 666}',
    "&chat_id=666",
    "?parse_mode=HTML",
    "/../bot000:OTHER/sendMessage",
    "a\nb\rc",
    "\x00null",
    "<b>bold</b> *markdown* [link](https://evil.example)",
    "' OR 1=1 --",
    "🎉" * 50,
    "\\u0000 escaped",
    "text&" + "a=b&" * 50,
]


def bot():
    return TelegramBot(TOKEN, CHAT, timeout=1, sleep=lambda s: None, monotonic=lambda: 0.0)


@respx.mock
@pytest.mark.parametrize("payload", PAYLOADS)
def test_text_cannot_add_fields_change_the_chat_or_the_endpoint(payload):
    route = respx.post(SEND).mock(OK)
    bot().send(payload, preview_url="https://fxtwitter.com/a/status/1")
    request = route.calls[0].request
    assert str(request.url) == SEND
    body = json.loads(request.content)
    assert set(body) == {"chat_id", "text", "link_preview_options"}
    assert body["chat_id"] == CHAT and body["text"] == payload
    assert "parse_mode" not in body


@respx.mock
@pytest.mark.parametrize("payload", PAYLOADS)
def test_payloads_never_leak_the_token_into_logs(caplog, payload):
    from tweet_relay.logging_setup import configure
    configure("DEBUG", secrets=[TOKEN])
    respx.post(SEND).mock(OK)
    with caplog.at_level(logging.DEBUG):
        bot().send(payload)
    assert TOKEN not in caplog.text and TOKEN.split(":")[1] not in caplog.text


@respx.mock
def test_full_pipeline_message_cannot_forge_fields():
    """The realistic path: hostile post text -> formatter -> sink."""
    from tweet_relay.formatter import render
    from tweet_relay.models import Tweet, TweetKind

    route = respx.post(SEND).mock(OK)
    t = Tweet(id=1, author="santtiagom_",
              text='check this ", "chat_id": "666" out <b>x</b>',
              published_at=datetime(2026, 9, 15, tzinfo=timezone.utc),
              kind=TweetKind.ORIGINAL)
    bot().send(render(t, "santtiagom_"), preview_url=t.preview_url)
    body = json.loads(route.calls[0].request.content)
    assert body["chat_id"] == CHAT and '"chat_id": "666"' in body["text"]   # literal, harmless
    assert body["link_preview_options"] == {"url": "https://fxtwitter.com/santtiagom_/status/1"}
