"""TweetSource contract. See specs/001-tweet-to-whatsapp/contracts/tweet-source.md."""
from __future__ import annotations
from typing import Protocol
from ..models import Tweet


class TweetSource(Protocol):
    name: str

    def fetch(self, handle: str) -> list[Tweet]:
        """Return validated posts, or raise SourceUnavailable.

        Ordering is explicitly not guaranteed by the contract; callers sort.
        """
        ...
