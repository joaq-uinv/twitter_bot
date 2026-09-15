"""Retrieves posts from public mirrors that expose an account as a syndication feed.

Constitution §4: every byte here comes from a volunteer-run third party we do not
control. Nothing is trusted — not the XML structure, not the identity of the account
it claims to describe, not the links it contains.
"""
from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from urllib.parse import urlparse

import httpx
from defusedxml import ElementTree as DefusedET

from ..models import HANDLE_RE, SourceUnavailable, Tweet, TweetKind

log = logging.getLogger(__name__)

RT_PREFIX = re.compile(r"^RT by @([A-Za-z0-9_]{1,15}):\s*", re.I)
REPLY_PREFIX = re.compile(r"^R to @([A-Za-z0-9_]{1,15}):\s*", re.I)
STATUS_PATH = re.compile(r"^/([A-Za-z0-9_]{1,15})/status/(\d{1,19})$")
MAX_FUTURE = timedelta(hours=24)


def _classify(title: str, link_author: str, handle: str, description: str) -> TweetKind:
    """Amendment A-1. Order matters; both retweet conditions are required."""
    if REPLY_PREFIX.match(title):
        return TweetKind.REPLY
    # The RT prefix is the mirror's own template, and the only signal that catches a
    # self-retweet. The link-author check is kept as a second condition so a change to
    # the template does not silently reclassify every retweet as an original.
    if RT_PREFIX.match(title) or link_author.lower() != handle.lower():
        return TweetKind.RETWEET
    if "<blockquote>" in description:
        return TweetKind.QUOTE
    return TweetKind.ORIGINAL


def _parse_link(raw: str, expected_host: str | None = None) -> tuple[str, int] | None:
    """Extract (author, id) from a mirror link, or None if it is not a post link.

    DD-5: a link whose shape we do not recognise is discarded rather than rewritten.
    Blind host-rewriting would turn an attacker-chosen path into a plausible x.com
    link delivered to the operator.

    An unexpected link host is logged but NOT rejected. Rejecting it was tried and
    reverted: mirrors legitimately serve canonical links pointing at another host, so
    pinning silently emptied a working feed — turning a healthy relay into a silent
    no-op, which §7 forbids. The host is discarded anyway when the URL is rebuilt from
    validated parts, so pinning bought no security for that risk.
    """
    try:
        parsed = urlparse((raw or "").split("#")[0])
    except ValueError:
        return None
    if expected_host and (parsed.hostname or "").lower() != expected_host.lower():
        log.warning("link host %r differs from mirror %r; URL will be rebuilt",
                    parsed.hostname, expected_host)
    m = STATUS_PATH.match(parsed.path or "")
    if not m:
        return None
    author, sid = m.group(1), m.group(2)
    if not HANDLE_RE.match(author):
        return None
    try:
        return author, int(sid)
    except ValueError:
        return None


def _parse_date(raw: str | None) -> datetime | None:
    if not raw:
        return None
    try:
        dt = parsedate_to_datetime(raw)
    except (TypeError, ValueError):
        return None
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    # E-12: a fabricated future timestamp would jump the delivery queue forever.
    if dt > datetime.now(timezone.utc) + MAX_FUTURE:
        return None
    return dt.astimezone(timezone.utc)


def parse_feed(raw: bytes, handle: str, expected_host: str | None = None) -> list[Tweet]:
    """Parse a feed into validated posts, sorted oldest first.

    Malformed items are dropped, not raised (contract guarantee 1). The whole feed is
    rejected only when it is unparseable or describes the wrong account.
    """
    try:
        root = DefusedET.fromstring(raw)
    except Exception as exc:
        raise SourceUnavailable(f"unparseable feed: {type(exc).__name__}") from None

    channel = root.find("channel")
    if channel is None:
        raise SourceUnavailable("not a syndication feed: no channel element")

    # FR-7/E-7: confirm this describes the account we asked about.
    title = (channel.findtext("title") or "")
    if not re.search(rf"@{re.escape(handle)}\b", title, re.I):
        raise SourceUnavailable(
            f"feed identifies a different account: {title[:80]!r} (wanted @{handle})")

    tweets: list[Tweet] = []
    seen_ids: set[int] = set()
    for item in channel.findall("item"):
        item_title = (item.findtext("title") or "").strip()
        parsed_link = _parse_link(item.findtext("link") or "", expected_host)
        if parsed_link is None:
            log.warning("dropping item with unrecognised link")
            continue
        link_author, link_id = parsed_link

        guid_raw = (item.findtext("guid") or "").strip()
        try:
            post_id = int(guid_raw)
        except ValueError:
            post_id = link_id  # fall back to the link, which we already validated
        if post_id != link_id:
            log.warning("guid/link id disagree (%s vs %s); trusting link", post_id, link_id)
            post_id = link_id
        if post_id in seen_ids:      # E-3
            continue

        published = _parse_date(item.findtext("pubDate"))
        if published is None:
            log.warning("dropping item %s: unusable timestamp", post_id)
            continue

        description = item.findtext("description") or ""
        kind = _classify(item_title, link_author, handle, description)
        text = RT_PREFIX.sub("", REPLY_PREFIX.sub("", item_title)) or item_title

        try:
            tweets.append(Tweet(id=post_id, author=link_author, text=text,
                                published_at=published, kind=kind))
        except ValueError as exc:
            log.warning("dropping invalid item %s: %s", post_id, exc)
            continue
        seen_ids.add(post_id)

    # FR-3: the real feed is not date-ordered, so sorting here is load-bearing.
    tweets.sort(key=lambda t: (t.published_at, t.id))
    return tweets


class NitterRssSource:
    """Tries each configured mirror in order; the first usable answer wins.

    Raises SourceUnavailable only when every mirror fails, so callers can tell a
    total outage (notify the operator) from a quiet account (stay silent).
    """

    name = "nitter-rss"

    def __init__(self, config, client: httpx.Client | None = None):
        self.config = config
        self._client = client

    def _get(self, client: httpx.Client, url: str) -> bytes:
        limit = self.config.MAX_FEED_BYTES
        # Streamed so an oversized body is abandoned mid-download rather than
        # buffered in full and then rejected (E-9).
        with client.stream("GET", url) as response:
            response.raise_for_status()
            declared = response.headers.get("content-length")
            if declared and declared.isdigit() and int(declared) > limit:
                raise SourceUnavailable(f"response declares {declared} bytes, over cap")
            chunks, total = [], 0
            for chunk in response.iter_bytes():
                total += len(chunk)
                if total > limit:
                    raise SourceUnavailable(f"response exceeded {limit} bytes")
                chunks.append(chunk)
        return b"".join(chunks)

    def fetch(self, handle: str) -> list[Tweet]:
        if not HANDLE_RE.match(handle or ""):
            raise SourceUnavailable(f"refusing to fetch malformed handle {handle!r}")

        client = self._client or httpx.Client(
            timeout=httpx.Timeout(self.config.REQUEST_TIMEOUT_SECONDS),
            # follow_redirects=False: a mirror redirecting us elsewhere is a mirror we
            # should stop trusting, not follow (§4).
            follow_redirects=False,
            headers={"User-Agent": "tweet-relay/0.1 (+personal notification relay)"},
        )
        failures: list[str] = []
        try:
            for base in self.config.instances:
                url = f"{base.rstrip('/')}/{handle}/rss"
                try:
                    body = self._get(client, url)
                    if not body.strip():
                        raise SourceUnavailable("empty body")
                    tweets = parse_feed(body, handle,
                                        expected_host=urlparse(base).hostname)
                    log.info("fetched %d posts from %s", len(tweets), base)
                    return tweets
                except SourceUnavailable as exc:
                    failures.append(f"{base}: {exc}")
                    log.warning("mirror unusable %s: %s", base, exc)
                except httpx.HTTPError as exc:
                    failures.append(f"{base}: {type(exc).__name__}")
                    log.warning("mirror failed %s: %s", base, type(exc).__name__)
        finally:
            if self._client is None:
                client.close()

        raise SourceUnavailable("all mirrors failed: " + "; ".join(failures))
