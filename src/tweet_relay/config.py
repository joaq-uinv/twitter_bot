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
# Re-verified 2026-10-10 (specs/002-mirror-health/research.md R-2): netbub now answers
# with a bot challenge and jaydenha with an HTML access queue, so both were replaced.
# Ordered fastest first; meowing.monster answered in 12 s against a 15 s timeout.
DEFAULT_INSTANCES = [
    "https://nitter.kareem.one",
    "https://nitter.pp.ua",
    "https://shitter.thepixora.com",
    "https://nitter.meowing.monster",
]

_PROFILE_HOSTS = {"x.com", "www.x.com", "twitter.com", "www.twitter.com"}
# Spec 003 data-model.md. Shape only: whether the token works is the first send's job.
BOT_TOKEN_RE = re.compile(r"^\d{5,12}:[A-Za-z0-9_-]{30,64}$")
CHAT_ID_RE = re.compile(r"^-?\d{1,20}$")


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


HOST_RE = re.compile(
    r"^(?=.{1,253}$)[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?"
    r"(?:\.[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?)+$")


def non_global_address(host: str):
    """The first resolved address of `host` that is not globally routable, or None.

    `not is_global` rather than `is_private`: in Python 3.12 carrier-grade NAT space
    (100.64.0.0/10) is neither private nor global (spec 002 research R-3). A name that
    does not resolve returns None; whoever connects later fails safely.
    """
    try:
        infos = socket.getaddrinfo(host, 443, proto=socket.IPPROTO_TCP)
    except OSError:
        return None
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if not ip.is_global:
            return ip
    return None


def validate_mirror_url(url: str, *, resolve: bool = True) -> str:
    """The single strict gate for mirror addresses (001 E-20, spec 002 FR-11, DD-3).

    Accepts only `https://<host>`, optionally with a trailing slash: no userinfo,
    port, path, query, fragment or IP literal, and a strictly limited hostname
    charset. Every resolved address must be global. Returns `https://<host>`,
    lower-cased.

    `resolve=False` checks shape only. Discovery uses it (spec 002 review #5): a hostile
    list of up to 1000 names behind slow DNS must not stall the round, and the address
    check runs anyway at probe time for the few hosts actually probed (DD-4).
    """
    raw = (url or "").strip()
    parsed = urlparse(raw)
    if parsed.scheme != "https":
        raise ValueError(f"mirror must use https, got {raw!r}")
    netloc = parsed.netloc
    if not netloc or "@" in netloc or ":" in netloc:
        raise ValueError(f"mirror must be a bare host (no credentials or port): {raw!r}")
    if parsed.path not in ("", "/") or parsed.params or parsed.query or parsed.fragment:
        raise ValueError(f"mirror must be a bare host (no path or query): {raw!r}")
    host = netloc.lower()
    try:
        ipaddress.ip_address(host)
    except ValueError:
        pass
    else:
        raise ValueError(f"mirror must be named, not an IP literal: {raw!r}")
    if not HOST_RE.match(host):
        raise ValueError(f"mirror host has invalid characters or length: {raw!r}")
    ip = non_global_address(host) if resolve else None
    if ip is not None:
        raise ValueError(f"mirror resolves to a non-public address: {raw!r} -> {ip}")
    return f"https://{host}"


def _validate_instance(url: str) -> str:
    """Reject anything that could point the fetcher at internal infrastructure (E-20).

    Tightened by spec 002 DD-3: delegates to the one strict validator.
    """
    return validate_mirror_url(url)


class Config(BaseSettings):
    # hide_input_in_errors: a rejected value must not be echoed by the validation
    # error, because the rejected value may be a secret (spec 003 FR-16).
    model_config = SettingsConfigDict(env_file=".env", extra="ignore",
                                      case_sensitive=False, hide_input_in_errors=True)

    X_PROFILE_URL: str
    # Blank is allowed so `check-source` can diagnose retrieval before delivery is
    # set up. Commands that actually deliver assert these via require_delivery().
    # Both are secrets (spec 003 FR-16); SecretStr keeps them out of reprs.
    TELEGRAM_BOT_TOKEN: SecretStr = SecretStr("")
    TELEGRAM_CHAT_ID: SecretStr = SecretStr("")
    STATUS_PAGE_URL: str = "https://joaq-uinv.github.io/twitter_bot/"
    MIRROR_LATEST_PATH: str = "/data/mirror-latest.json"

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

    @field_validator("TELEGRAM_BOT_TOKEN")
    @classmethod
    def _check_token(cls, v: SecretStr) -> SecretStr:
        raw = v.get_secret_value().strip()
        if raw and not BOT_TOKEN_RE.match(raw):
            # Never echo the value: it is a secret even when malformed.
            raise ValueError("TELEGRAM_BOT_TOKEN does not look like a bot token "
                             "(digits, a colon, then 30-64 letters, digits, - or _)")
        return SecretStr(raw)

    @field_validator("TELEGRAM_CHAT_ID")
    @classmethod
    def _check_chat(cls, v: SecretStr) -> SecretStr:
        raw = v.get_secret_value().strip()
        if raw and not CHAT_ID_RE.match(raw):
            raise ValueError("TELEGRAM_CHAT_ID must be a whole number "
                             "(see quickstart: find-chat-id)")
        return SecretStr(raw)

    @field_validator("STATUS_PAGE_URL")
    @classmethod
    def _check_page(cls, v: str) -> str:
        if urlparse(v).scheme != "https" or not urlparse(v).hostname:
            raise ValueError(f"STATUS_PAGE_URL must be an https URL, got {v!r}")
        return v

    @field_validator("NITTER_INSTANCES")
    @classmethod
    def _check_instances(cls, v: str) -> str:
        for part in [p for p in (v or "").split(",") if p.strip()]:
            _validate_instance(part)
        return v

    def require_delivery(self) -> None:
        """Raise unless delivery is fully configured. Called by commands that send."""
        missing = [name for name in ("TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID")
                   if not getattr(self, name).get_secret_value()]
        if missing:
            raise ValueError(
                f"{' and '.join(missing)} must be set to deliver messages.\n"
                "See specs/003-bot-chat-delivery/quickstart.md steps 1-2.")

    @property
    def chat_id(self) -> int | None:
        raw = self.TELEGRAM_CHAT_ID.get_secret_value()
        return int(raw) if raw else None

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
