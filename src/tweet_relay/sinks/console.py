"""Dry-run sink: prints exactly what would be sent.

Every line is prefixed with "| " because stdout feeds the run summary (plan A-10):
post text must never be able to pass for one of our own log or result lines.
"""
from __future__ import annotations


class ConsoleSink:
    name = "console"

    def send(self, message: str) -> None:
        lines = ["-" * 60, *message.splitlines(), "-" * 60]
        print("\n".join(f"| {line}" for line in lines), flush=True)
