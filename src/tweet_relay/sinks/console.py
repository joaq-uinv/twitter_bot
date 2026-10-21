"""Dry-run sink: prints exactly what would be sent.

Every line is prefixed with "| " because stdout feeds the run summary (plan A-10):
post text must never be able to pass for one of our own log or result lines.
"""
from __future__ import annotations


class ConsoleSink:
    name = "console"

    def send(self, message: str, *, preview_url: str | None = None) -> None:
        card = [f"card: {preview_url}"] if preview_url else []
        lines = ["-" * 60, *message.splitlines(), *card, "-" * 60]
        print("\n".join(f"| {line}" for line in lines), flush=True)

    def chat_is_private(self) -> bool:
        return True              # nothing is sent, so there is no chat to check
