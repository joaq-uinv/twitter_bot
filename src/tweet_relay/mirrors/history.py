"""History of probe results, stored in a directory (spec 002 contract history-store.md).

`history.jsonl` holds one ProbeResult per line; `latest.json` holds the last round's
verdict, the episode, discovery state and open warnings. File I/O only: committing
and force-pushing the `mirror-status` branch is the workflow's job (plan DD-5).

Reading is hostile-tolerant: the branch is ours, but a bad line must not be able to
inject text or crash a round (E-20).
"""
from __future__ import annotations

import json
import logging
import os
import tempfile
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path

from ..config import _HOST_RE as HOST_RE
from .health import EpisodeState
from .models import Freshness, ProbeResult, Reason, Role
from .roster import DiscoveryState

log = logging.getLogger(__name__)

RETENTION = timedelta(days=90)      # FR-18
HISTORY_FILE, LATEST_FILE = "history.jsonl", "latest.json"


@dataclass(frozen=True)
class Latest:
    round_t: datetime | None
    reference: datetime | None
    in_use_healthy: int
    in_use_total: int
    at_risk: bool
    episode: EpisodeState
    discovery: DiscoveryState
    warnings: dict[str, datetime] = field(default_factory=dict)   # open: host -> since


EMPTY_LATEST = Latest(round_t=None, reference=None, in_use_healthy=0, in_use_total=0,
                      at_risk=False, episode=EpisodeState(at_risk_since=None),
                      discovery=DiscoveryState(last_ok=None, accepted=0, rejected=0, candidates=[]))


@dataclass(frozen=True)
class History:
    results: list[ProbeResult]
    latest: Latest
    corrupt: bool = False


# ---------- serialisation ----------

def _ts(d: datetime | None) -> str | None:
    return d.isoformat() if d is not None else None


def _dt(v) -> datetime | None:
    if v is None:
        return None
    d = datetime.fromisoformat(v)
    if d.tzinfo is None:
        raise ValueError("naive timestamp")
    return d


def _host(v) -> str:
    if not isinstance(v, str) or not HOST_RE.match(v):
        raise ValueError("invalid host")
    return v


def result_to_json(r: ProbeResult) -> dict:
    return {"t": _ts(r.t), "host": r.host, "role": r.role.value, "usable": r.usable,
            "freshness": r.freshness.value if r.freshness else None,
            "reason": r.reason.value if r.reason else None,
            "ms": r.ms, "newest": _ts(r.newest)}


def result_from_json(d: dict) -> ProbeResult:
    ms = d["ms"]
    if ms is not None and (not isinstance(ms, int) or isinstance(ms, bool) or ms < 0):
        raise ValueError("invalid ms")
    if not isinstance(d["usable"], bool):
        raise ValueError("invalid usable")
    return ProbeResult(t=_dt(d["t"]), host=_host(d["host"]), role=Role(d["role"]),
                       usable=d["usable"],
                       freshness=Freshness(d["freshness"]) if d["freshness"] else None,
                       reason=Reason(d["reason"]) if d["reason"] else None,
                       ms=ms, newest=_dt(d["newest"]))


def _latest_to_json(x: Latest) -> dict:
    return {"round": {"t": _ts(x.round_t), "reference": _ts(x.reference),
                      "in_use_healthy": x.in_use_healthy, "in_use_total": x.in_use_total,
                      "at_risk": x.at_risk},
            "episode": {"at_risk_since": _ts(x.episode.at_risk_since)},
            "discovery": {"last_ok": _ts(x.discovery.last_ok), "accepted": x.discovery.accepted,
                          "rejected": x.discovery.rejected,
                          "candidates": list(x.discovery.candidates)},
            "warnings": {h: _ts(t) for h, t in x.warnings.items()}}


def _latest_from_json(d: dict) -> Latest:
    rnd, disc = d["round"], d["discovery"]
    for n in (rnd["in_use_healthy"], rnd["in_use_total"], disc["accepted"], disc["rejected"]):
        if not isinstance(n, int) or isinstance(n, bool) or n < 0:
            raise ValueError("invalid count")
    return Latest(round_t=_dt(rnd["t"]), reference=_dt(rnd["reference"]),
                  in_use_healthy=rnd["in_use_healthy"], in_use_total=rnd["in_use_total"],
                  at_risk=bool(rnd["at_risk"]),
                  episode=EpisodeState(at_risk_since=_dt(d["episode"]["at_risk_since"])),
                  discovery=DiscoveryState(last_ok=_dt(disc["last_ok"]),
                                           accepted=disc["accepted"], rejected=disc["rejected"],
                                           candidates=[_host(h) for h in disc["candidates"]]),
                  warnings={_host(h): _dt(t) for h, t in d["warnings"].items()})


# ---------- the store ----------

class DirHistoryStore:
    def __init__(self, directory: Path | str):
        self.dir = Path(directory)

    def load(self) -> History:
        results, bad, lines = [], 0, 0
        path = self.dir / HISTORY_FILE
        if path.exists():
            for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
                if not line.strip():
                    continue
                lines += 1
                try:
                    results.append(result_from_json(json.loads(line)))
                except Exception:              # hostile-tolerant: drop and count
                    bad += 1
        corrupt = lines > 0 and bad * 2 > lines
        if corrupt:
            results = []
        elif bad:
            log.warning("dropped %d invalid history lines", bad)
        results.sort(key=lambda r: r.t)
        return History(results=results, latest=self._load_latest(), corrupt=corrupt)

    def _load_latest(self) -> Latest:
        path = self.dir / LATEST_FILE
        if not path.exists():
            return EMPTY_LATEST
        try:
            return _latest_from_json(json.loads(path.read_text(encoding="utf-8")))
        except Exception:
            log.error("latest.json unreadable; starting from an empty state")
            return EMPTY_LATEST

    def save(self, history: History, now: datetime) -> None:
        """Prune (FR-18), then write each file atomically (E-21)."""
        keep = sorted((r for r in history.results if r.t >= now - RETENTION), key=lambda r: r.t)
        self.dir.mkdir(parents=True, exist_ok=True)
        self._atomic(HISTORY_FILE, "".join(json.dumps(result_to_json(r)) + "\n" for r in keep))
        self._atomic(LATEST_FILE, json.dumps(_latest_to_json(history.latest), indent=2) + "\n")

    def _atomic(self, name: str, text: str) -> None:
        fd, tmp = tempfile.mkstemp(dir=self.dir, prefix=f".{name}.")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(text)
            os.replace(tmp, self.dir / name)
        except BaseException:
            Path(tmp).unlink(missing_ok=True)
            raise
