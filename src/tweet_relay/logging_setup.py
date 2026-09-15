"""Logging configured so a secret cannot reach a log record (FR-13).

This exists because of a real leak found by tests/unit/test_callmebot.py: httpx logs
every request URL at INFO, and CallMeBot requires the API key as a query parameter, so
the key appeared in ordinary application logs. Silencing httpx alone would be brittle
— any future library could do the same — so redaction is applied at the root handler
as a backstop as well.
"""
from __future__ import annotations

import logging
from urllib.parse import quote


class SecretRedactingFilter(logging.Filter):
    """Replaces known secrets anywhere in a formatted record."""

    def __init__(self, secrets: list[str]):
        super().__init__()
        self.needles: list[str] = []
        for s in secrets:
            if s and len(s) >= 4:
                self.needles.append(s)
                encoded = quote(s, safe="")
                if encoded != s:
                    self.needles.append(encoded)

    def _scrub(self, value: str) -> str:
        for needle in self.needles:
            if needle in value:
                value = value.replace(needle, "***REDACTED***")
        return value

    def filter(self, record: logging.LogRecord) -> bool:
        if self.needles:
            if isinstance(record.msg, str):
                record.msg = self._scrub(record.msg)
            if record.args:
                if isinstance(record.args, dict):
                    record.args = {k: self._scrub(v) if isinstance(v, str) else v
                                   for k, v in record.args.items()}
                else:
                    record.args = tuple(self._scrub(a) if isinstance(a, str) else a
                                        for a in record.args)
        return True


def configure(level: str = "INFO", secrets: list[str] | None = None) -> None:
    root = logging.getLogger()
    root.setLevel(getattr(logging, (level or "INFO").upper(), logging.INFO))
    if not root.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter(
            "%(asctime)s %(levelname)-7s %(name)s: %(message)s"))
        root.addHandler(handler)

    redactor = SecretRedactingFilter(secrets or [])
    for handler in root.handlers:
        handler.addFilter(redactor)

    # httpx logs full request URLs at INFO, and the key travels in the query string.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
