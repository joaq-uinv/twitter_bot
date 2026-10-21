"""Probes one mirror, read-only (spec 002 contract mirror-probe.md).

Fetching and parsing go through `fetch_one`, the function the relay uses, so a mirror
the probe calls usable is exactly one the relay would accept (FR-3, plan DD-1).
"""
from __future__ import annotations

import logging
import time
from datetime import datetime, timedelta, timezone

import httpx

from ..config import non_global_address
from ..sources.nitter_rss import USER_AGENT, MirrorError, fetch_one
from .models import ProbeOutcome, Reason

log = logging.getLogger(__name__)

# A post dated further ahead than this is clock skew at best and a lie at worst; it
# must not make a mirror look fresher than it is (E-2, plan DD-10).
FUTURE_TOLERANCE = timedelta(minutes=5)


class HttpMirrorProbe:
    def __init__(self, config, client: httpx.Client | None = None, *,
                 resolve=non_global_address, clock=time.monotonic,
                 now=lambda: datetime.now(timezone.utc)):
        self.config = config
        self._client = client
        self._resolve = resolve
        self._clock = clock
        self._now = now

    def _http(self) -> httpx.Client:
        if self._client is None:
            self._client = httpx.Client(
                timeout=httpx.Timeout(self.config.REQUEST_TIMEOUT_SECONDS),
                follow_redirects=False,                      # sent_elsewhere, never followed
                headers={"User-Agent": USER_AGENT})
        return self._client

    def close(self) -> None:
        if self._client is not None:
            self._client.close()

    def probe(self, host: str, handle: str) -> ProbeOutcome:
        # FR-11, DD-4: checked at probe time, before any connection. Rebinding between
        # this check and the connect is an accepted risk (plan Risks): nothing from a
        # response is ever published.
        if self._resolve(host) is not None:
            return ProbeOutcome(usable=False, reason=Reason.REFUSED_ADDRESS, ms=None, newest=None)

        start = self._clock()
        try:
            tweets = fetch_one(self._http(), f"https://{host}", handle, self.config)
        except MirrorError as exc:
            # The message stays local: only the reason is ever published (FR-16).
            log.debug("probe %s: %s (%s)", host, exc.reason, exc)
            ms = None if exc.reason is Reason.UNREACHABLE else self._elapsed_ms(start)
            return ProbeOutcome(usable=False, reason=exc.reason, ms=ms, newest=None)
        ms = self._elapsed_ms(start)

        cutoff = self._now() + FUTURE_TOLERANCE
        times = [t.published_at for t in tweets if t.published_at <= cutoff]
        if not times:
            return ProbeOutcome(usable=False, reason=Reason.NO_POSTS, ms=ms, newest=None)
        return ProbeOutcome(usable=True, reason=None, ms=ms, newest=max(times))

    def _elapsed_ms(self, start: float) -> int:
        return max(0, round((self._clock() - start) * 1000))
