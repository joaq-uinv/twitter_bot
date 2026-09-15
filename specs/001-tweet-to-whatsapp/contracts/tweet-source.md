# Contract: `TweetSource`

```python
class TweetSource(Protocol):
    name: str
    def fetch(self, handle: str) -> list[Tweet]: ...
```

## Guarantees an implementation MUST provide

1. Returns **validated** `Tweet` objects only. Anything failing `data-model.md`'s
   invariants is dropped and logged at WARNING — never returned, never raised (FR-8).
2. Raises `SourceUnavailable` when it cannot produce a result at all. This is the only
   expected exception; anything else is a bug.
3. Returns `[]` only for a genuinely empty account — never to mask a failure. An empty
   list means "no posts", which callers treat as success (§7: silence must mean healthy).
4. Enforces a bounded wait. Never blocks indefinitely (E-18).
5. Enforces a byte cap before parsing (E-9).
6. Verifies returned content belongs to `handle`; raises `SourceUnavailable` if not
   (FR-7, E-7) — a mirror serving the wrong account is a broken mirror.
7. Performs no writes. Sources are pure readers; only the pipeline touches state.

**Ordering is explicitly NOT guaranteed.** Callers must sort. This is contractual, not
incidental — the real feed is unordered (F-2), and a source that happened to return
sorted output would let an ordering bug hide.

## Implementations

| Name | Status |
|---|---|
| `NitterRssSource` | Primary. Iterates mirrors in order; first success wins; `SourceUnavailable` only if **all** fail |
| `SyndicationSource` | **Gated.** Returned 429 on every probe. Ship only if it demonstrably returns data; otherwise delete (DD-9) |
| `FixtureSource` | Test double reading `tests/fixtures/` |
