"""Builds status.json for the page (spec 002 data-model.md, plan DD-9).

All the arithmetic lives here, in tested Python. The page's JavaScript only renders
what this produces. Every value is a validated host, a closed-set label, a time or a
number (FR-16).
"""
from __future__ import annotations

from datetime import datetime, timedelta

from .history import Latest
from .models import ProbeResult, Role

TREND_LENGTH = 40
UPTIME_WINDOWS = {"uptime_7d": timedelta(days=7), "uptime_30d": timedelta(days=30)}


def _ts(d: datetime | None) -> str | None:
    return d.isoformat() if d is not None else None


def _uptime(results: list[ProbeResult], since: datetime) -> float | None:
    window = [r for r in results if r.t >= since]
    if not window:
        return None
    return sum(r.healthy for r in window) / len(window)      # D-4 via ProbeResult.healthy


def build_status(history: list[ProbeResult], latest: Latest, now: datetime) -> dict:
    by_host: dict[str, list[ProbeResult]] = {}
    for r in sorted(history, key=lambda r: r.t):
        by_host.setdefault(r.host, []).append(r)
    rounds = sorted({r.t for r in history})[-TREND_LENGTH:]
    current = [r for r in history if r.t == latest.round_t] if latest.round_t else []

    mirrors = []
    for r in current:
        mine = by_host[r.host]
        healthy_at = {x.t: x.healthy for x in mine}
        entry = {
            "host": r.host,
            "role": r.role.value,
            "healthy": r.healthy,
            "reason": r.reason.value if r.reason else None,
            "ms": r.ms,
            "newest_age_s": int((r.t - r.newest).total_seconds()) if r.newest else None,
            "trend": [healthy_at.get(t) for t in rounds],     # None = not probed (AC-4.2)
        }
        for key, span in UPTIME_WINDOWS.items():
            entry[key] = _uptime(mine, now - span)
        mirrors.append(entry)

    in_use = [m for m in mirrors if m["role"] == Role.IN_USE.value]
    others = sorted((m for m in mirrors if m["role"] != Role.IN_USE.value),
                    key=lambda m: (not m["healthy"],
                                   -(m["uptime_30d"] if m["uptime_30d"] is not None else -1),
                                   m["host"]))            # AC-5.2

    return {
        "generated_at": _ts(now),
        "round": {"t": _ts(latest.round_t), "reference": _ts(latest.reference),
                  "in_use_healthy": latest.in_use_healthy, "in_use_total": latest.in_use_total,
                  "at_risk": latest.at_risk,
                  "at_risk_since": _ts(latest.episode.at_risk_since)},
        "discovery": {"last_ok": _ts(latest.discovery.last_ok),
                      "accepted": latest.discovery.accepted,
                      "rejected": latest.discovery.rejected},
        "mirrors": in_use + others,
        "warnings": [{"host": h, "since": _ts(t)} for h, t in sorted(latest.warnings.items())],
    }
