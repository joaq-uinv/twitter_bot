"""Dry-run sink: prints exactly what would be sent."""
from __future__ import annotations


class ConsoleSink:
    name = "console"

    def send(self, message: str) -> None:
        print("-" * 60)
        print(message)
        print("-" * 60, flush=True)
