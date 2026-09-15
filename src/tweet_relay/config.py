"""Startup configuration. Invalid config refuses to start (AC-5.2)."""
from __future__ import annotations

import ipaddress
import re
import socket
from urllib.parse import urlparse

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from .models import HANDLE_RE

# Verified working 2026-09-15 (research.md R-1). Volunteer-run; expect churn.
DEFAULT_INSTANCES = [
    "https://nitter.kareem.one",
    "https://nitter.meowing.monster",
    "https://nitter.netbub.com",
    "https://nitter.jaydenha.uk",
]

_PROFILE_HOSTS = {"x.com", "www.x.com", "twitter.com", "www.twitter.com"}
PHONE_RE = re.compile(r"^\+[1-9]\d{7,14}$")


def extract_handle(raw: str) -> str:
    """Accept a profile URL or a bare handle; return the validated handle.

    The returned value is interpolated into a URL path, so HANDLE_RE is a security
    control, not just input hygiene (E-20).
    """
    value = (raw or "").strip()
    if not value:
        raise ValueError("X_PROFILE_URL is empty")

    if "/" in value or value.startswith("http"):
        parsed = urlparse(value if "://" in value else f"https://{value}")
        if parsed.hostname not in _PROFILE_HOSTS:
            raise ValueError(
                f"profile URL host must be x.com or twitter.com, got {parsed.hostname!r}")
        parts = [p for p in parsed.path.split("/") if p]
        if len(parts) != 1:
            raise ValueError(f"expected a profile URL like https://x.com/<handle>, got {raw!r}")
        value = parts[0]

    value = value.lstrip("@")
    if not HANDLE_RE.match(value):
        raise ValueError(f"malformed handle: {value!r}")
    return value


def _validate_instance(url: str) -> str:
    """Reject anything that could point the fetcher at internal infrastructure (E-20)."""
    url = url.strip().rstrip("/")
    parsed = urlparse(url)
    if parsed.scheme != "https":
        raise ValueError(f"instance must use https, got {url!r}")
    if not parsed.hostname:
        raise ValueError(f"instance has no host: {url!r}")

    host = parsed.hostname
    candidates = []
    try:
        candidates.append(ipaddress.ip_address(host))
    except ValueError:
        try:
            infos = socket.getaddrinfo(host, 443, proto=socket.IPPROTO_TCP)
            candidates = [ipaddress.ip_address(i[4][0]) for i in infos]
        except OSError:
            candidates = []  # unresolvable now; the fetcher will fail safely later
    for ip in candidates:
        if (ip.is_private or ip.is_loopback or ip.is_link_local
                or ip.is_reserved or ip.is_multicast or ip.is_unspecified):
            raise ValueError(f"instance resolves to a non-public address: {url!r} -> {ip}")
    return url


class Config(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore",
                                      case_sensitive=False)

    X_PROFILE_URL: str
    CALLMEBOT_PHONE: str
    CALLMEBOT_APIKEY: SecretStr   # SecretStr keeps the key out of reprs (FR-13)

    INCLUDE_RETWEETS: bool = True
    INCLUDE_REPLIES: bool = False
    INCLUDE_QUOTES: bool = True

    POLL_INTERVAL_SECONDS: int = Field(900, ge=60, le=86_400)
    MAX_MESSAGES_PER_RUN: int = Field(10, ge=1, le=50)
    NITTER_INSTANCES: str = ""
    MAX_FEED_BYTES: int = Field(5_242_880, ge=1024)
    REQUEST_TIMEOUT_SECONDS: float = Field(15.0, gt=0, le=120)
    STATE_PATH: str = "/data/seen.json"
    VERIFY_ACROSS_INSTANCES: bool = False
    LOG_LEVEL: str = "INFO"

    @field_validator("X_PROFILE_URL")
    @classmethod
    def _check_profile(cls, v: str) -> str:
        extract_handle(v)
        return v

    @field_validator("CALLMEBOT_PHONE")
    @classmethod
    def _check_phone(cls, v: str) -> str:
        if not PHONE_RE.match((v or "").strip()):
            raise ValueError(f"CALLMEBOT_PHONE must be E.164 (e.g. +34600111222), got {v!r}")
        return v.strip()

    @field_validator("NITTER_INSTANCES")
    @classmethod
    def _check_instances(cls, v: str) -> str:
        for part in [p for p in (v or "").split(",") if p.strip()]:
            _validate_instance(part)
        return v

    @property
    def handle(self) -> str:
        return extract_handle(self.X_PROFILE_URL)

    @property
    def instances(self) -> list[str]:
        given = [p.strip().rstrip("/") for p in self.NITTER_INSTANCES.split(",") if p.strip()]
        return given or list(DEFAULT_INSTANCES)

    @property
    def include_retweets(self) -> bool: return self.INCLUDE_RETWEETS
    @property
    def include_replies(self) -> bool: return self.INCLUDE_REPLIES
    @property
    def include_quotes(self) -> bool: return self.INCLUDE_QUOTES
    @property
    def poll_interval_seconds(self) -> int: return self.POLL_INTERVAL_SECONDS
    @property
    def max_messages_per_run(self) -> int: return self.MAX_MESSAGES_PER_RUN
