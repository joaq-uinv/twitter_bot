# Contract: `MessageSink`

```python
class MessageSink(Protocol):
    def send(self, message: str) -> None: ...   # raises DeliveryFailed
```

## Guarantees an implementation MUST provide

1. Returns normally **only** when the message was genuinely delivered. Raises
   `DeliveryFailed` otherwise. The pipeline marks a post seen based solely on this —
   a false success means permanent silent loss (FR-12).
2. **HTTP 200 is not sufficient evidence of delivery.** CallMeBot reports some errors
   in the body of a 200 response, so the body must be inspected (R-3, E-19).
3. Never includes credentials in an exception message, log line, or traceback (FR-13).
   Asserted by test, not convention.
4. Treats message text as **opaque data**. Text is passed through the transport's own
   encoder; string interpolation into a URL or body is forbidden (E-11).
5. Applies its own inter-message pacing to respect channel rate limits.
6. Retries transient failures with backoff; raises `DeliveryFailed` once exhausted.
   Retries must not duplicate an already-delivered message.

## Implementations

| Name | Notes |
|---|---|
| `CallMeBotSink` | Production. 3s pacing, backoff on 5xx/timeout, body-content success check |
| `ConsoleSink` | `--dry-run`. Prints the exact rendered message; never fails |
| `RecordingSink` | Test double. Can be told to fail on the *n*-th send, for E-5 partial-failure tests |
