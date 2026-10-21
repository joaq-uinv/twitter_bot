"""The bot chat: delivery and the operator's commands (spec 003, plan DD-1, DD-2).

Telegram Bot API over plain HTTPS. The token travels in the request path, and httpx
puts the URL into its exception messages, so no exception text from httpx is ever
passed on: errors carry only an exception type, a status code and the API's own
description, scrubbed (plan DD-8, the lesson of 001 A-3).
"""
from __future__ import annotations

import logging
import re
import time

import httpx

from ..commands import MAX_TEXT, InboxBatch, IncomingMessage
from ..models import DeliveryFailed, InboxUnavailable, MessageRejected

log = logging.getLogger(__name__)

# Request URLs carry the token; httpx logs them at INFO (001 A-3).
logging.getLogger("httpx").setLevel(max(logging.WARNING,
                                        logging.getLogger("httpx").level or 0))

API_ROOT = "https://api.telegram.org"
MAX_FLOOD_WAIT = 30            # seconds; longer waits fail the send (contract 5)
_DESCRIPTION_CHARS = 200
MAX_UPDATES_BYTES = 1 << 20    # contract command-inbox 4
# A 400 that mentions any of these is about the chat or the bot, not this message, so
# the minimal-form retry would only add traffic (contract 7).
_CHANNEL_WORDING = re.compile(
    r"\b(?:chat|bot|token|user|unauthori[sz]ed|forbidden|webhook|not\s+found|"
    r"rate|limit|too\s+many)\b", re.I)


class TelegramBot:
    name = "telegram"

    def __init__(self, token: str, chat_id: str, *, timeout: float,
                 client: httpx.Client | None = None, pace_seconds: float = 1.0,
                 max_attempts: int = 3, sleep=time.sleep, monotonic=time.monotonic):
        self._token = token
        self._chat_id = chat_id
        self._timeout = timeout
        self._client = client
        self.pace_seconds = pace_seconds
        self.max_attempts = max_attempts
        self._sleep = sleep
        self._monotonic = monotonic
        self._last_send: float | None = None

    def __repr__(self) -> str:        # never render the token or the chat (FR-16)
        return "TelegramBot()"

    def _url(self, method: str) -> str:
        return f"{API_ROOT}/bot{self._token}/{method}"

    def _scrub(self, text: str) -> str:
        """The API's own words, fit for an exception and a log line (FR-16, §7)."""
        for secret in sorted({self._token, self._token.split(":")[-1], self._chat_id},
                             key=len, reverse=True):
            if secret and len(secret) >= 4:
                text = text.replace(secret, "***")
        return " ".join(text.split())[:_DESCRIPTION_CHARS]

    def _pace(self) -> None:
        if self._last_send is not None:
            gap = self._monotonic() - self._last_send
            if gap < self.pace_seconds:
                self._sleep(self.pace_seconds - gap)

    def send(self, message: str, *, preview_url: str | None = None) -> None:
        # No parse_mode: the text is literal, so nothing in a post can change the
        # message's structure (001 E-11).
        payload: dict = {"chat_id": self._chat_id, "text": message}
        if preview_url:
            payload["link_preview_options"] = {"url": preview_url}
        self._pace()
        try:
            body = self._call("sendMessage", payload)
        finally:
            self._last_send = self._monotonic()
        result = body.get("result")
        mid = result.get("message_id") if isinstance(result, dict) else None
        if not isinstance(mid, int) or isinstance(mid, bool):
            # FR-5: an answer that does not confirm the message is not a delivery.
            raise DeliveryFailed("unrecognised response, not treating as delivered")

    def chat_is_private(self) -> bool:
        """Spec D-4, plan DD-7: the configured chat is a one-to-one private chat.

        Whether it is the operator's own is confirmed once at setup; this only stops
        posts and status going to a group or channel by mistake.
        """
        result = self._call("getChat", {"chat_id": self._chat_id}).get("result")
        kind = result.get("type") if isinstance(result, dict) else None
        if not isinstance(kind, str):
            raise DeliveryFailed("getChat: unrecognised response")
        return kind == "private"

    def read(self, offset: int) -> InboxBatch:
        """Messages sent to the bot from `offset` on (contract command-inbox).

        Reading confirms nothing: only a later read with a higher offset does, and the
        pipeline decides that offset (plan DD-5). Who sent a message is not judged here.
        """
        try:
            body = self._call("getUpdates", {"offset": offset, "limit": 100, "timeout": 0,
                                             "allowed_updates": ["message"]},
                              max_bytes=MAX_UPDATES_BYTES)
        except DeliveryFailed as exc:          # its text is already scrubbed
            raise InboxUnavailable(str(exc)) from None
        updates = body.get("result")
        if not isinstance(updates, list):
            raise InboxUnavailable("getUpdates: unrecognised response")
        messages, next_offset, skipped = [], offset, 0
        for update in updates:
            uid = update.get("update_id") if isinstance(update, dict) else None
            if _is_int(uid) and uid > 0:
                next_offset = max(next_offset, uid + 1)
            message = _incoming(update)
            if message is None:
                skipped += 1
            else:
                messages.append(message)
        if skipped:
            log.debug("skipped %d updates that are not usable messages", skipped)
        messages.sort(key=lambda m: m.update_id)
        return InboxBatch(messages=messages, next_offset=next_offset)

    def _call(self, method: str, payload: dict, *, max_bytes: int | None = None) -> dict:
        """One API call with retries. Returns the body of an `ok` answer.

        Retried: timeouts, connection errors, 5xx, one short flood-control wait.
        Not retried: every other refusal, which only a person can fix.
        """
        client = self._client or httpx.Client(timeout=httpx.Timeout(self._timeout),
                                              follow_redirects=False)
        last_error = "no attempt made"
        flood_waited = False
        try:
            for attempt in range(1, self.max_attempts + 1):
                try:
                    response = client.post(self._url(method), json=payload)
                except httpx.HTTPError as exc:
                    # Type only: httpx's message contains the URL, and so the token.
                    last_error = type(exc).__name__
                else:
                    if response.status_code >= 500:
                        last_error = f"HTTP {response.status_code}"
                    else:
                        if max_bytes is not None and len(response.content) > max_bytes:
                            raise DeliveryFailed(f"{method}: answer over {max_bytes} bytes")
                        try:
                            body = response.json()
                        except ValueError:
                            raise DeliveryFailed(f"{method}: HTTP {response.status_code} "
                                                 "with a non-JSON body") from None
                        if not isinstance(body, dict):
                            raise DeliveryFailed(f"{method}: unrecognised response")
                        if body.get("ok") is True:
                            return body
                        wait = self._flood_wait(body)
                        if wait is not None and not flood_waited and attempt < self.max_attempts:
                            flood_waited = True
                            self._sleep(wait)
                            continue
                        raise self._refusal(method, body)
                if attempt < self.max_attempts:
                    self._sleep(min(2 ** attempt, 10))
        finally:
            if self._client is None:
                client.close()
        raise DeliveryFailed(f"{method} failed after {self.max_attempts} attempts: {last_error}")

    @staticmethod
    def _flood_wait(body: dict) -> int | None:
        """Seconds to wait for a short flood-control refusal, else None (contract 5)."""
        params = body.get("parameters")
        wait = params.get("retry_after") if isinstance(params, dict) else None
        if (body.get("error_code") == 429 and isinstance(wait, int)
                and not isinstance(wait, bool) and 0 < wait <= MAX_FLOOD_WAIT):
            return wait
        return None

    def _refusal(self, method: str, body: dict) -> DeliveryFailed:
        code = body.get("error_code")
        description = body.get("description")
        reason = self._scrub(description) if isinstance(description, str) else ""
        if code == 401:
            return DeliveryFailed(f"{method}: the bot token was rejected (HTTP 401)")
        detail = f"{method}: refused with {code}: {reason!r}"
        if code == 400 and reason and not _CHANNEL_WORDING.search(reason):
            # This message, not the chat or the bot (001 E-21; contract 7).
            return MessageRejected(detail)
        return DeliveryFailed(detail)


def _is_int(v) -> bool:
    return isinstance(v, int) and not isinstance(v, bool)


def _incoming(update) -> IncomingMessage | None:
    """A validated message, or None for anything that does not fit (hostile input)."""
    if not isinstance(update, dict):
        return None
    uid, message = update.get("update_id"), update.get("message")
    if not (_is_int(uid) and uid > 0 and isinstance(message, dict)):
        return None
    chat = message.get("chat")
    if not isinstance(chat, dict):
        return None
    chat_id, chat_type = chat.get("id"), chat.get("type")
    text = message.get("text", "")
    if not (_is_int(chat_id) and isinstance(chat_type, str) and isinstance(text, str)):
        return None
    return IncomingMessage(update_id=uid, chat_id=chat_id, chat_type=chat_type,
                           text=text[:MAX_TEXT])
