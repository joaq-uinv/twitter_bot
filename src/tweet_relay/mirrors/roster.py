"""Which mirrors a round probes, and in what role (spec 002 FR-13..15, plan DD-11).

Pure: it reads the configured mirrors, history and the latest list, and never changes
the relay's configuration. Discovery only ever suggests (FR-15, AC-5.4).
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from urllib.parse import urlparse

from .directory import DirectoryRead
from .models import ProbeResult, Role

CANDIDATE_CAP = 25          # FR-13: former and discovered together


@dataclass(frozen=True)
class DiscoveryState:
    last_ok: datetime | None
    accepted: int
    rejected: int
    candidates: list[str]   # the last good discovered set, kept on failure (FR-14)


def build_roster(in_use_urls: list[str], history: list[ProbeResult],
                 found: DirectoryRead | None, prev: DiscoveryState,
                 now: datetime) -> tuple[list[tuple[str, Role]], DiscoveryState]:
    """In-use first, then former (D-2, newest first), then discovered, capped at 25.

    `found=None` means the list was unavailable: the last good candidates are reused
    and `last_ok` is left as it was, so the page can show discovery as stale (E-13).
    """
    in_use = _unique(urlparse(u).hostname for u in in_use_urls)

    last_in_use: dict[str, datetime] = {}
    for r in history:
        if r.role is Role.IN_USE and r.host not in in_use:
            last_in_use[r.host] = max(r.t, last_in_use.get(r.host, r.t))
    former = sorted(last_in_use, key=lambda h: last_in_use[h], reverse=True)

    if found is None:
        discovery = prev
    else:
        discovery = DiscoveryState(last_ok=now, accepted=found.accepted,
                                   rejected=found.rejected, candidates=list(found.hosts))

    entries = [(h, Role.IN_USE) for h in in_use]
    taken = set(in_use)
    extra: list[tuple[str, Role]] = []
    for host, role in [(h, Role.FORMER) for h in former] + \
                      [(h, Role.CANDIDATE) for h in discovery.candidates]:
        if host not in taken and len(extra) < CANDIDATE_CAP:
            extra.append((host, role))
            taken.add(host)
    return entries + extra, discovery


def _unique(items) -> list[str]:
    out: list[str] = []
    for item in items:
        if item and item not in out:
            out.append(item)
    return out
