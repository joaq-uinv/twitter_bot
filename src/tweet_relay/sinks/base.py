"""MessageSink contract. See contracts/message-sink.md."""
from __future__ import annotations
from typing import Protocol


class MessageSink(Protocol):
    def send(self, message: str) -> None:
        """Return only on genuine delivery; raise DeliveryFailed otherwise."""
        ...
