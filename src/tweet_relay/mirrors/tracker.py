"""Soft warnings live outside the page (spec 002 FR-10; contract warning-tracker.md)."""
from __future__ import annotations

from datetime import datetime
from typing import Protocol

from .models import Reason


class TrackerUnavailable(Exception):
    """The tracker could not be read or written. The round still records and publishes,
    then reports 'check broken' so the operator learns warnings are not tracked (§7)."""


class WarningTracker(Protocol):
    def open_warnings(self) -> dict[str, datetime]: ...
    def open(self, host: str, since: datetime, reason: Reason) -> None: ...
    def update(self, host: str, reason: Reason) -> None: ...
    def close(self, host: str) -> None: ...


class NullTracker:
    """For local runs without tracker credentials: tracks nothing, and says so."""

    def open_warnings(self) -> dict[str, datetime]:
        return {}

    def open(self, host, since, reason) -> None: ...
    def update(self, host, reason) -> None: ...
    def close(self, host) -> None: ...
