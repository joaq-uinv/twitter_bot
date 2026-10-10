# Contract: `WarningTracker`

```python
class WarningTracker(Protocol):
    def open_warnings(self) -> dict[Host, datetime]: ...            # host -> opened at
    def open(self, host: Host, since: datetime, reason: Reason) -> None: ...
    def update(self, host: Host, reason: Reason) -> None: ...       # AC-2.3
    def close(self, host: Host) -> None: ...                        # AC-2.4
```

The caller computes the desired set with the soft-warning rule (data-model.md) and
reconciles: it opens what is missing, updates what persists and closes what has
recovered.

## Guarantees an implementation MUST provide

1. **At most one open warning per host** (FR-10). `open` on a host that already
   has one is a no-op, so a rerun after a partial failure is idempotent.
2. Warning text is built **only** from `Host`, `Reason`, times, counts and the
   status-page URL (FR-16). No body or title takes text from a response.
3. A tracker failure (network, auth, rate limit) raises `TrackerUnavailable`. The
   round still records and publishes, logs at ERROR, and fails as "check broken",
   so the operator learns that warnings are not being tracked (§7).
4. Credentials come from the environment only and never appear in exception text
   (§6, the A-7 scrub pattern).

## `GitHubIssueTracker`, the production implementation (plan DD-8)

- REST API with `GITHUB_TOKEN` (`issues: write`).
- Identifies issues by label `mirror-health` **and** the exact title
  `Mirror unhealthy for 24h: <host>`.
- `update` adds a comment (`Still unhealthy: <reason> at <time>`), at most one per
  round. `close` adds a closing comment, then closes the issue.

| Name | Status |
|---|---|
| `GitHubIssueTracker` | Production |
| `FakeTracker` | Test double that records calls |
