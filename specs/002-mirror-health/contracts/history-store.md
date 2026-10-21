# Contract: `HistoryStore`

```python
class HistoryStore(Protocol):
    def load(self) -> History: ...                 # results + latest
    def save(self, history: History) -> None: ...  # atomic
```

## Guarantees an implementation MUST provide

1. **`load` never raises** for bad content. It drops invalid lines. If more than
   half the lines are invalid, it returns an empty history with `corrupt=True`, and
   the caller logs at ERROR (E-20). A missing directory is an empty history.
2. **`save` is atomic.** Each file is written to a temporary file then renamed, so
   a killed round never leaves a half-written file (E-21).
3. Prunes results older than 90 days on save (FR-18).
4. It is file I/O only. Git operations (checkout, commit, force-push to
   `mirror-status`) belong to the workflow (plan DD-5).

| Name | Status |
|---|---|
| `DirHistoryStore` | Production. `history.jsonl` and `latest.json` in a directory |
| `MemoryHistoryStore` | Test double |
