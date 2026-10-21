# Contract: `MirrorDirectory`

```python
class MirrorDirectory(Protocol):
    def list(self) -> DirectoryRead: ...

@dataclass(frozen=True)
class DirectoryRead:
    hosts: list[Host]        # validated, de-duplicated, in list order
    accepted: int
    rejected: int
```

## Guarantees an implementation MUST provide

1. **Treats the list as hostile** (spec FR-11). Enforces a 1 MiB size cap, the
   relay's timeout, no redirects, and a strict parse.
2. **Drops entries one at a time** (FR-12). A bad entry increments `rejected`.
   Only an unreadable *document* is a failure.
3. Raises `DirectoryUnavailable` when the document cannot be read or parsed. The
   caller then keeps the last good set (FR-14). Nothing else is raised.
4. Returns hosts only. It never returns any other field from the list (FR-16).
5. Does **not** apply the cap or the in-use exclusion. The roster builder does
   that (FR-13, plan DD-11), so it holds for every directory implementation.

## `StatusD420Directory`, the production implementation (research R-1)

- `GET https://status.d420.de/api/v1/instances`. Requires `{"hosts": [...]}`.
- An entry is accepted only if `url` passes `validate_mirror_url()` **and**
  `domain` equals `url`'s host. Every other field is ignored.
- More than 1000 entries means the whole document is rejected as hostile.

| Name | Status |
|---|---|
| `StatusD420Directory` | Production |
| `StaticDirectory` | Test double |
