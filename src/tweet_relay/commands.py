"""Operator commands read from the bot chat (spec 003 US-3..US-6).

Pure: no I/O. Message text is hostile input (FR-11): only its first characters are
examined, and nothing from it is ever copied into a reply, a log line or state.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from enum import StrEnum


class Command(StrEnum):
    STATUS = "status"
    PAUSE = "pause"
    RESUME = "resume"
    HELP = "help"
    UNKNOWN = "unknown"


# DD-12: case-insensitive, an optional @botname suffix, then end or whitespace. ASCII
# only, so look-alike letters from other scripts never match.
_COMMAND = re.compile(r"/(status|pause|resume|help)(?:@\w+)?(?:\s|$)", re.I | re.A)
_EXAMINED = 64


def parse(text: str) -> Command:
    m = _COMMAND.match(text[:_EXAMINED])
    return Command(m.group(1).lower()) if m else Command.UNKNOWN


# ---------- replies (data-model.md "Replies") ----------
# Fixed templates. The only variable parts are numbers, times we produced and our own
# status page URL; no builder accepts message text (FR-11).

def _when(t: datetime) -> str:
    return f"{t.astimezone(timezone.utc):%Y-%m-%d %H:%M} UTC"


def render_status(*, last_check: tuple[datetime, int] | None, waiting: int | None,
                  paused_since: datetime | None, mirrors: tuple[int, int] | None,
                  page_url: str) -> str:
    last = (f"{_when(last_check[0])}, delivered {last_check[1]}"
            if last_check else "none yet")
    wait = str(waiting) if waiting is not None else "unknown, sources unavailable"
    state = f"paused since {_when(paused_since)}" if paused_since else "running"
    health = (f"{mirrors[0]} of {mirrors[1]} healthy" if mirrors
              else "health check not available")
    return (f"Last check: {last}.\nWaiting: {wait}.\nDeliveries: {state}.\n"
            f"Mirrors: {health}.\n{page_url}")


def render_pause(paused_since: datetime | None) -> str:
    """`paused_since` is the state *before* this command."""
    if paused_since:
        return f"Already paused since {_when(paused_since)}."
    return "⏸ Paused. Send /resume to start again."


def render_resume(paused_since: datetime | None, *, waiting: int | None, cap: int,
                  oldest_listed: datetime | None) -> str:
    """`paused_since` is the state *before* this command (AC-4.4..AC-4.6)."""
    if paused_since is None:
        return "Already running."
    if waiting is None:
        return ("▶️ Resumed. The sources are unavailable right now; waiting posts "
                "arrive when they recover.")
    out = f"▶️ Resumed. {waiting} posts waiting; up to {min(waiting, cap)} arrive now."
    if oldest_listed is not None and paused_since < oldest_listed:
        # E-15: the sources no longer list anything from the start of the pause.
        out += " Posts from early in the pause may no longer be retrievable."
    return out


def render_help() -> str:
    return ("/status - how the relay is doing\n"
            "/pause - stop deliveries until /resume\n"
            "/resume - restart deliveries\n"
            "/help - this list\n\n"
            "Replies arrive at the next check, which can take minutes or hours.")


def render_unknown() -> str:
    return "I don't know that one. Send /help."
