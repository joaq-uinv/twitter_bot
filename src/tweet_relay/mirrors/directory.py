"""Discovers candidate mirrors from a community list (spec 002 contract
mirror-directory.md, research R-1).

The list and every host it names are hostile (FR-11). Only the `url` of each entry is
used, it must pass the same strict validator as configured mirrors, and nothing else
from the document ever leaves this module (FR-16).
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from urllib.parse import urlparse

import httpx

from ..config import validate_mirror_url
from ..sources.nitter_rss import USER_AGENT

log = logging.getLogger(__name__)


class DirectoryUnavailable(Exception):
    """The list document could not be read. The caller keeps the last good set (FR-14)."""


@dataclass(frozen=True)
class DirectoryRead:
    hosts: list[str]          # validated, de-duplicated, in list order
    accepted: int
    rejected: int


class StatusD420Directory:
    URL = "https://status.d420.de/api/v1/instances"
    MAX_BYTES = 1024 * 1024
    MAX_ENTRIES = 1000        # more than this is not a list of volunteer mirrors

    def __init__(self, config, client: httpx.Client | None = None):
        self.config = config
        self._client = client

    def list(self) -> DirectoryRead:
        doc = self._fetch()
        try:
            entries = json.loads(doc)["hosts"]
        except (ValueError, TypeError, KeyError):
            raise DirectoryUnavailable("not a mirror list") from None
        if not isinstance(entries, list):
            raise DirectoryUnavailable("not a mirror list")
        if len(entries) > self.MAX_ENTRIES:
            raise DirectoryUnavailable(f"implausibly long list ({len(entries)} entries)")

        hosts: list[str] = []
        rejected = 0
        for e in entries:
            host = self._accept(e)
            if host is None:
                rejected += 1
            elif host not in hosts:
                hosts.append(host)
        return DirectoryRead(hosts=hosts, accepted=len(hosts), rejected=rejected)

    @staticmethod
    def _accept(entry) -> str | None:
        """FR-12: judged one entry at a time; None means dropped."""
        if not isinstance(entry, dict):
            return None
        url, domain = entry.get("url"), entry.get("domain")
        if not isinstance(url, str) or not isinstance(domain, str):
            return None
        try:
            host = urlparse(validate_mirror_url(url, resolve=False)).hostname
        except ValueError:
            return None
        return host if domain.strip().lower() == host else None

    def _fetch(self) -> bytes:
        client = self._client or httpx.Client(
            timeout=httpx.Timeout(self.config.REQUEST_TIMEOUT_SECONDS),
            follow_redirects=False, headers={"User-Agent": USER_AGENT})
        try:
            with client.stream("GET", self.URL) as response:
                if response.status_code != 200:
                    raise DirectoryUnavailable(f"HTTP {response.status_code}")
                chunks, total = [], 0
                for chunk in response.iter_bytes():
                    total += len(chunk)
                    if total > self.MAX_BYTES:
                        raise DirectoryUnavailable("list document too large")
                    chunks.append(chunk)
            return b"".join(chunks)
        except httpx.HTTPError as exc:
            raise DirectoryUnavailable(type(exc).__name__) from None
        finally:
            if self._client is None:
                client.close()
