"""MessageSink contract. See contracts/message-sink.md."""
from __future__ import annotations
from typing import Protocol


class MessageSink(Protocol):
    def send(self, message: str, *, preview_url: str | None = None) -> None:
        """Return only on genuine delivery; raise DeliveryFailed otherwise."""
        ...

    def chat_is_private(self) -> bool:
        """Spec 003 D-4: the target is a one-to-one private chat."""
        ...
