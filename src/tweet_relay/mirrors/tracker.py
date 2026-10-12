"""Soft warnings live outside the page (spec 002 FR-10; contract warning-tracker.md)."""
from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from typing import Protocol

import httpx

from ..config import HOST_RE
from .models import Reason


class TrackerUnavailable(Exception):
    """The tracker could not be read or written. The round still records and publishes,
    then reports 'check broken' so the operator learns warnings are not tracked (§7)."""


class WarningTracker(Protocol):
    def open_warnings(self) -> dict[str, datetime]: ...
    def open(self, host: str, since: datetime, reason: Reason) -> None: ...
    def update(self, host: str, reason: Reason) -> None: ...
    def close(self, host: str) -> None: ...


class NullTracker:
    """For local runs without tracker credentials: tracks nothing, and says so."""

    def open_warnings(self) -> dict[str, datetime]:
        return {}

    def open(self, host, since, reason) -> None: ...
    def update(self, host, reason) -> None: ...
    def close(self, host) -> None: ...


# ---------- GitHub issues (plan DD-8) ----------


log = logging.getLogger(__name__)

LABEL = "mirror-health"
_TITLE_PREFIX = "Mirror unhealthy for 24h: "
_REPO_RE = re.compile(r"^[A-Za-z0-9-]{1,39}/[A-Za-z0-9._-]{1,100}$")


def title_for(host: str) -> str:
    """Fixed text plus a validated host: the only way a title is ever built (FR-16)."""
    return _TITLE_PREFIX + host


class GitHubIssueTracker:
    """One issue per in-use mirror unhealthy for 24 h, matched by label + exact title.

    Every text it writes is built from a validated host, a closed-set reason, times and
    the status page URL. The token travels only in the Authorization header and never
    appears in an exception, a log line or repr (§6).
    """

    def __init__(self, token: str, repo: str, client: httpx.Client | None = None,
                 now=lambda: datetime.now(timezone.utc)):
        if not _REPO_RE.match(repo or ""):
            raise ValueError("GITHUB_REPOSITORY must look like owner/name")
        self._token = token
        self.repo = repo
        owner, name = repo.split("/")
        self.page_url = f"https://{owner.lower()}.github.io/{name}/"
        self._client = client
        self._now = now

    def __repr__(self) -> str:
        return f"GitHubIssueTracker(repo={self.repo!r})"

    # -- protocol --

    def open_warnings(self) -> dict[str, datetime]:
        return {host: since for host, (_, since) in self._open_issues().items()}

    def open(self, host: str, since: datetime, reason: Reason) -> None:
        if host in self._open_issues():
            return                                            # contract 1: idempotent
        body = (f"`{host}` has been unhealthy in every probe since {since.isoformat()} "
                f"(latest reason: `{reason.value}`).\n\n"
                f"Status page: {self.page_url}\n\n"
                "This closes automatically on the mirror's first healthy probe.")
        self._call("POST", "/issues", {"title": title_for(host), "body": body, "labels": [LABEL]})

    def update(self, host: str, reason: Reason) -> None:
        number = self._number(host)
        if number is not None:
            self._call("POST", f"/issues/{number}/comments",
                       {"body": f"Still unhealthy: `{reason.value}` at {self._now().isoformat()}."})

    def close(self, host: str) -> None:
        number = self._number(host)
        if number is None:
            return
        self._call("POST", f"/issues/{number}/comments",
                   {"body": f"Healthy again, or no longer in use, at {self._now().isoformat()}."})
        self._call("PATCH", f"/issues/{number}", {"state": "closed"})

    # -- internals --

    def _number(self, host: str) -> int | None:
        found = self._open_issues().get(host)
        return found[0] if found else None

    def _open_issues(self) -> dict[str, tuple[int, datetime]]:
        issues = self._call("GET", "/issues", params={"state": "open", "labels": LABEL,
                                                      "per_page": "100"})
        out = {}
        for i in issues if isinstance(issues, list) else []:
            if not isinstance(i, dict) or "pull_request" in i:
                continue
            title = i.get("title")
            if not isinstance(title, str) or not title.startswith(_TITLE_PREFIX):
                continue
            host = title[len(_TITLE_PREFIX):]
            if not HOST_RE.match(host):
                continue
            try:
                since = datetime.fromisoformat(str(i["created_at"]).replace("Z", "+00:00"))
                if since.tzinfo is None:
                    continue
                out[host] = (int(i["number"]), since)
            except (KeyError, TypeError, ValueError):
                continue
        return out

    def _call(self, method: str, path: str, payload: dict | None = None, params=None):
        client = self._client or httpx.Client(timeout=httpx.Timeout(15.0))
        try:
            response = client.request(
                method, f"https://api.github.com/repos/{self.repo}{path}", json=payload,
                params=params, headers={"Authorization": f"Bearer {self._token}",
                                        "Accept": "application/vnd.github+json",
                                        "X-GitHub-Api-Version": "2022-11-28"})
        except httpx.HTTPError as exc:
            raise TrackerUnavailable(f"GitHub API unreachable: {type(exc).__name__}") from None
        finally:
            if self._client is None:
                client.close()
        if response.status_code >= 300:
            # Status only: the body could echo anything, including credentials.
            raise TrackerUnavailable(f"GitHub API answered {response.status_code}")
        if not response.content:
            return None
        try:
            return response.json()
        except ValueError:
            raise TrackerUnavailable("GitHub API answered with something that is not JSON") from None
