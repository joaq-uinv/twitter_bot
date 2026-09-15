"""Renders a validated post as WhatsApp message text.

The rendered string is passed to the sink as opaque data and encoded there; nothing
in here can affect the structure of the outbound request (FR-13, E-11).
"""
from __future__ import annotations

from .models import Tweet, TweetKind

MAX_TEXT_CHARS = 900

_MARKERS = {
    TweetKind.RETWEET: "🔁 RT @{author}",
    TweetKind.QUOTE: "💬 Quote by @{monitored}",
    TweetKind.REPLY: "↩️ Reply by @{monitored}",
}


def render(tweet: Tweet, monitored_handle: str) -> str:
    body = tweet.text
    if len(body) > MAX_TEXT_CHARS:
        # Truncate the body only. The link is appended afterwards so it always
        # survives, which is the point of E-13.
        body = body[:MAX_TEXT_CHARS].rstrip() + "…"

    marker = _MARKERS.get(tweet.kind)
    header = marker.format(author=tweet.author, monitored=monitored_handle) if marker else None

    parts = [p for p in (header, body, tweet.url) if p]
    return "\n\n".join(parts)


def render_bootstrap(handle: str, count: int) -> str:
    return (f"✅ Relay is live for @{handle}.\n\n"
            f"{count} existing posts marked as already seen — you will only get new ones.")


def render_outage(handle: str, detail: str) -> str:
    return (f"⚠️ Relay cannot reach any source for @{handle}.\n\n"
            f"{detail[:300]}\n\nYou will not get posts until this recovers.")


def render_withheld(count: int) -> str:
    return f"…and {count} more not sent yet — they will arrive on the next checks."
