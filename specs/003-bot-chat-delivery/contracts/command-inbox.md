# Contract: `CommandInbox` (new in 003)

```python
class CommandInbox(Protocol):
    def read(self, offset: int) -> InboxBatch: ...   # raises InboxUnavailable

@dataclass(frozen=True)
class InboxBatch:
    messages: list[IncomingMessage]   # valid ones, oldest first
    next_offset: int                  # highest update_id seen (valid or not) + 1, else offset
    more: bool = False                # a full page came back: more may be waiting (P-3)
```

## Guarantees an implementation MUST provide

1. Returns the messages sent to the bot with `update_id >= offset`, oldest first, at
   most 100 per call (plan DD-3). Reading **does not** confirm anything: the same
   call with the same offset returns the same messages. Confirmation happens only
   because the pipeline stores a higher offset (plan DD-5).
2. Returns only updates of kind "new message". Edits, reactions and membership
   changes are never requested.
3. Every returned item is a validated `IncomingMessage` (data-model.md). Updates that
   do not fit are dropped inside the adapter and reported only as a count at DEBUG,
   never their content. `next_offset` covers malformed updates too, so a malformed update
   cannot block the queue forever.
4. Caps the response body (1 MiB) and the total wait (the relay's request timeout)
   before parsing. Non-JSON, `ok: false`, or a missing `result` list raise
   `InboxUnavailable`.
5. Never logs or raises with message text, sender identity, the token, or a URL
   (spec FR-7, FR-16).
6. Does **not** filter by sender. Deciding who the operator is belongs to the
   pipeline, against configuration, so the rule is tested in one place.

## Pipeline obligations (caller side)

- An `InboxUnavailable` sets `failed=1` (the run fails, §7) but does not stop post
  delivery: a broken command path must not also stop the relay's main job.
- Commands are handled before posts are delivered, after the fetch (plan Architecture).
- Each handled command advances and saves the offset before its reply (plan DD-5).
- When a page is fully consumed and `more` is set, read the next page, at most 10 reads
  per check, so a flood of strangers cannot starve the operator (plan P-3, AC-6.2).

## Implementations

| Name | Notes |
|---|---|
| `TelegramBot` | Production. `getUpdates(offset, limit=100, timeout=0, allowed_updates=["message"])` |
| `NullInbox` | Dry runs without a token, and `check-source`. Returns nothing |
| `ScriptedInbox` | Test double. Returns a fixed list; can raise `InboxUnavailable` |
