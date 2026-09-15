"""Domain types. A Tweet that exists is a Tweet that is safe to deliver.

Constitution §4: validation happens at construction, so the rest of the codebase
never has to ask whether a field came from an untrusted mirror.
"""
from __future__ import annotations

import re
import unicodedata
from datetime import datetime, timezone
from enum import Enum

HANDLE_RE = re.compile(r"^[A-Za-z0-9_]{1,15}$")
MAX_ID = 2**63 - 1
MAX_TEXT = 10_000

# Bidi overrides and isolates: renderable text that can visually reorder a message,
# e.g. making a malicious link appear to point somewhere else.
_BIDI = {0x202A, 0x202B, 0x202C, 0x202D, 0x202E, 0x2066, 0x2067, 0x2068, 0x2069}


class SourceUnavailable(Exception):
    """A source could not produce a result. The only exception a source may raise."""


class DeliveryFailed(Exception):
    """A message was not delivered. Never raised when delivery actually succeeded."""


class TweetKind(str, Enum):
    ORIGINAL = "original"
    RETWEET = "retweet"
    QUOTE = "quote"
    REPLY = "reply"


def clean_text(raw: str) -> str:
    """Strip control and bidi characters, keeping newlines, tabs and emoji."""
    out = []
    for ch in unicodedata.normalize("NFC", raw):
        cp = ord(ch)
        if ch in "\n\t":
            out.append(ch)
        elif cp in _BIDI:
            continue
        elif unicodedata.category(ch) in ("Cc", "Cf", "Cs", "Co", "Cn"):
            continue  # Cf covers zero-width joiners/spaces
        else:
            out.append(ch)
    return "".join(out).strip()


class Tweet:
    """A validated post. Construction enforces every invariant in data-model.md."""

    __slots__ = ("id", "author", "text", "published_at", "kind")

    def __init__(self, *, id: int, author: str, text: str,
                 published_at: datetime, kind: TweetKind):
        if not isinstance(id, int) or isinstance(id, bool):
            raise ValueError(f"id must be an int, got {type(id).__name__}")
        if not (0 < id <= MAX_ID):
            raise ValueError(f"id out of range: {id}")
        if not HANDLE_RE.match(author or ""):
            raise ValueError(f"malformed author: {author!r}")

        cleaned = clean_text(text or "")
        if not cleaned:
            raise ValueError("text is empty after normalisation")
        if len(cleaned) > MAX_TEXT:
            cleaned = cleaned[:MAX_TEXT]

        if not isinstance(published_at, datetime) or published_at.tzinfo is None:
            raise ValueError("published_at must be timezone-aware")

        self.id = id
        self.author = author
        self.text = cleaned
        self.published_at = published_at.astimezone(timezone.utc)
        self.kind = TweetKind(kind)

    @property
    def url(self) -> str:
        """Built from validated parts. Never copied from feed input (DD-5)."""
        return f"https://x.com/{self.author}/status/{self.id}"

    def __repr__(self) -> str:
        return f"Tweet(id={self.id}, author={self.author!r}, kind={self.kind.value})"

    def __eq__(self, other) -> bool:
        return isinstance(other, Tweet) and other.id == self.id

    def __hash__(self) -> int:
        return hash(self.id)
