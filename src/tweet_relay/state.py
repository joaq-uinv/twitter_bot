"""Delivery history.

DD-1: history is a *set* of delivered post ids, tested by membership. It is
deliberately not a high-water mark. A retweet carries the original post's id, which
can be years old, so "is this id greater than the newest I have seen" answers the
wrong question and would silently suppress most retweets (research F-3).
"""
from __future__ import annotations

import fcntl
import json
import logging
import os
import tempfile
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

log = logging.getLogger(__name__)

MAX_SEEN = 300   # DD-2


class StateUnwritable(Exception):
    """The state directory cannot be written. Almost always a mount ownership issue."""


class RelayState:
    __slots__ = ("handle", "seen_ids", "bootstrapped", "outage_notified", "last_success")

    def __init__(self, handle: str, seen_ids: list[int] | None = None,
                 bootstrapped: bool = False, outage_notified: bool = False,
                 last_success: datetime | None = None):
        self.handle = handle
        self.seen_ids = list(seen_ids or [])
        self.bootstrapped = bootstrapped
        self.outage_notified = outage_notified
        self.last_success = last_success

    def is_new(self, post_id: int) -> bool:
        return post_id not in set(self.seen_ids)

    def mark_seen(self, post_id: int) -> None:
        if post_id in self.seen_ids:
            return
        self.seen_ids.insert(0, post_id)
        del self.seen_ids[MAX_SEEN:]

    def to_dict(self) -> dict:
        return {
            "handle": self.handle,
            "seen_ids": self.seen_ids,
            "bootstrapped": self.bootstrapped,
            "outage_notified": self.outage_notified,
            "last_success": self.last_success.isoformat() if self.last_success else None,
        }


def _fresh(handle: str) -> RelayState:
    return RelayState(handle=handle)


def load_state(path: str | Path, handle: str) -> RelayState:
    """Read history. Any problem yields a fresh un-bootstrapped state (E-16).

    Re-bootstrapping is the safe failure direction: it suppresses history rather than
    replaying it, so corruption can never cause a flood of duplicate messages.
    """
    path = Path(path)
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return _fresh(handle)
    except (json.JSONDecodeError, OSError, UnicodeDecodeError) as exc:
        log.error("state unreadable (%s); re-bootstrapping", exc)
        return _fresh(handle)

    if not isinstance(raw, dict):
        log.error("state is not an object; re-bootstrapping")
        return _fresh(handle)

    if raw.get("handle") != handle:
        log.info("monitored account changed (%r -> %r); re-bootstrapping",
                 raw.get("handle"), handle)
        return _fresh(handle)

    ids = raw.get("seen_ids")
    if not isinstance(ids, list):
        log.error("state seen_ids malformed; re-bootstrapping")
        return _fresh(handle)
    clean = [i for i in ids if isinstance(i, int) and not isinstance(i, bool) and i > 0]
    if len(clean) != len(ids):
        log.warning("dropped %d malformed ids from state", len(ids) - len(clean))

    last = raw.get("last_success")
    try:
        parsed_last = datetime.fromisoformat(last) if last else None
    except (TypeError, ValueError):
        parsed_last = None

    return RelayState(
        handle=handle,
        seen_ids=clean[:MAX_SEEN],
        bootstrapped=bool(raw.get("bootstrapped", False)),
        outage_notified=bool(raw.get("outage_notified", False)),
        last_success=parsed_last,
    )


def save_state(path: str | Path, state: RelayState, _fail_after_write: bool = False) -> None:
    """Write atomically: full write to a sibling temp file, then rename (E-6).

    A crash before the rename leaves the previous file untouched; there is no window
    in which a reader can observe a partial file.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".seen-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(state.to_dict(), fh, indent=2)
            fh.flush()
            os.fsync(fh.fileno())
        if _fail_after_write:               # test hook for the crash window
            raise RuntimeError("simulated crash before rename")
        os.replace(tmp, path)
        tmp = None
    finally:
        if tmp and os.path.exists(tmp):
            os.unlink(tmp)


@contextmanager
def state_lock(path: str | Path):
    """Exclusive lock across read-modify-write, so concurrent runs on one volume
    cannot lose updates (E-17)."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    lock_path = path.with_suffix(path.suffix + ".lock")
    try:
        fh = open(lock_path, "w")
    except PermissionError as exc:
        raise StateUnwritable(
            f"cannot write state at {path.parent} ({exc.strerror}).\n"
            "The container user must own the mounted state directory. Set HOST_UID "
            "and HOST_GID in .env to your own ids (`id -u`, `id -g`), or run:\n"
            f"  sudo chown -R $(id -u):$(id -g) ./state"
        ) from None
    with fh:
        fcntl.flock(fh, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(fh, fcntl.LOCK_UN)


def with_lock_update(path: str | Path, handle: str, post_id: int) -> None:
    """Atomic read-modify-write of a single id. Used by tests and the pipeline."""
    with state_lock(path):
        state = load_state(path, handle)
        state.mark_seen(post_id)
        save_state(path, state)
