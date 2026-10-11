"""Value types for mirror health (spec 002 data-model.md).

Everything here may be published, so nothing here can hold free text: a result is a
validated host, members of closed sets, times and numbers (FR-5, FR-16). The
invariants are checked on construction, so an inconsistent result cannot exist.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum


class Reason(StrEnum):
    TIMED_OUT = "timed_out"
    UNREACHABLE = "unreachable"
    REFUSED_ANSWER = "refused_answer"
    SENT_ELSEWHERE = "sent_elsewhere"
    TOO_LARGE = "too_large"
    MALFORMED_CONTENT = "malformed_content"
    WRONG_ACCOUNT = "wrong_account"
    NO_POSTS = "no_posts"
    STALE = "stale"
    REFUSED_ADDRESS = "refused_address"


class Role(StrEnum):
    IN_USE = "in_use"
    FORMER = "former"          # in use earlier, not in the current config (D-2)
    CANDIDATE = "candidate"    # discovered


class Freshness(StrEnum):
    FRESH = "fresh"
    STALE = "stale"
    UNKNOWN = "unknown"        # no usable in-use result to compare against (FR-4)


@dataclass(frozen=True)
class ProbeOutcome:
    """One probe, before freshness is known (that needs the whole round)."""
    usable: bool
    reason: Reason | None
    ms: int | None
    newest: datetime | None

    def __post_init__(self) -> None:
        if (self.reason is None) != self.usable:
            raise ValueError("an outcome has a reason exactly when it is unusable")
        if (self.newest is None) == self.usable:
            raise ValueError("an outcome has a newest post exactly when it is usable")


@dataclass(frozen=True)
class ProbeResult:
    """One line of history.jsonl."""
    t: datetime
    host: str
    role: Role
    usable: bool
    freshness: Freshness | None
    reason: Reason | None
    ms: int | None
    newest: datetime | None

    def __post_init__(self) -> None:
        if (self.freshness is None) == self.usable:
            raise ValueError("freshness is set exactly when the result is usable")
        stale = self.usable and self.freshness is Freshness.STALE
        if (self.reason is Reason.STALE) != stale:
            raise ValueError("reason is 'stale' exactly when usable and stale")
        if (self.reason is None) != self.healthy:
            raise ValueError("a result has a reason exactly when it is unhealthy")

    @property
    def healthy(self) -> bool:
        # D-4: unknown freshness counts as healthy.
        return self.usable and self.freshness in (Freshness.FRESH, Freshness.UNKNOWN)
