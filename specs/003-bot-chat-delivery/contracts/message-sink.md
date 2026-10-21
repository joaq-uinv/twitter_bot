# Contract: `MessageSink` (amended by 003)

Supersedes `specs/001-tweet-to-whatsapp/contracts/message-sink.md` for the
signature and the implementation table. Guarantees 1, 3, 4, 6 and 7 carry over
unchanged in meaning.

```python
class MessageSink(Protocol):
    def send(self, message: str, *, preview_url: str | None = None) -> None: ...
    # raises DeliveryFailed or MessageRejected
```

## Guarantees an implementation MUST provide

1. Returns normally **only** when the message was genuinely delivered. For
   `TelegramSink` that means `{"ok": true, "result": {"message_id": <int>}}`; any
   other shape, including `ok: true` without an integer `message_id`, raises
   `DeliveryFailed` (spec FR-5).
2. Never includes credentials, the chat identity, or a request URL in an exception
   message, log line, or traceback (spec FR-16, plan DD-8). Asserted by test.
3. Treats message text as **opaque data**: sent as a JSON field with no
   `parse_mode`, so no character in a post can change the message's structure
   (001 E-11).
4. `preview_url`, when given, is used only to build the link preview (plan DD-4); a
   preview that cannot be built is never a delivery failure (spec E-16).
5. Paces sends to at most one per second per chat. On 429 waits `retry_after` once if
   it is ≤ 30 s, otherwise raises `DeliveryFailed`.
6. Retries timeouts and 5xx with backoff; raises `DeliveryFailed` once exhausted. A
   retry after a timeout can duplicate a message that did arrive; that is accepted,
   as in 001, because the alternative is losing it.
7. Raises `MessageRejected` **only** for a 400 whose description does not concern the
   chat, the bot or the token (e.g. "message is too long", "text must be non-empty").
   401, 403, 404, 429, 5xx, "chat not found" and anything unrecognised are plain
   `DeliveryFailed`.
8. Exposes `chat_is_private() -> bool`, used once per run before the first send
   (spec D-4, plan DD-7). A failure to answer raises `DeliveryFailed`.

## Implementations

| Name | Notes |
|---|---|
| `TelegramBot` | Production (`sinks/telegram.py`). Also implements `CommandInbox` |
| `ConsoleSink` | `--dry-run`. Prints the message, then `| card: <preview_url>`; `chat_is_private()` returns `True`; never fails |
| `RecordingSink` | Test double. Records `(message, preview_url)`. Can fail on the *n*-th send |
| ~~`CallMeBotSink`~~ | Deleted (spec FR-3) |
