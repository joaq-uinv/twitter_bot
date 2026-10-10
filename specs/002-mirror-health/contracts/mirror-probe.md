# Contract: `MirrorProbe`

```python
class MirrorProbe(Protocol):
    def probe(self, host: Host, handle: str) -> ProbeOutcome: ...

@dataclass(frozen=True)
class ProbeOutcome:          # before freshness, which needs the whole round
    usable: bool
    reason: Reason | None    # None iff usable
    ms: int | None
    newest: datetime | None  # newest non-future post; None iff not usable
```

## Guarantees an implementation MUST provide

1. **Same rules as the relay.** Fetching and parsing go through `fetch_one()`, the
   function `NitterRssSource` uses (plan DD-1). "Usable" means exactly "the relay
   would accept it" (FR-3).
2. **Never raises** for anything a mirror can do. Every failure maps to exactly one
   `Reason`. An unexpected exception is a bug, and it fails the round as "check
   broken" (AC-1.7).
3. **Checks the address before connecting.** If any resolved address is not
   global, it returns `refused_address` and makes no connection (FR-11, DD-4).
4. **Never follows redirects** (`sent_elsewhere`) and enforces the relay's timeout
   and byte cap.
5. **Returns no third-party text.** The outcome type has no string fields.
   Exception messages are logged locally at DEBUG and never returned (FR-16).
6. Read-only. It sends no messages and does not touch delivery history (FR-2).

## Implementations

| Name | Status |
|---|---|
| `HttpMirrorProbe` | Production. httpx plus `fetch_one` |
| `FixtureMirrorProbe` | Test double. It maps hosts to fixtures captured on 2026-10-10 (research R-2) |
