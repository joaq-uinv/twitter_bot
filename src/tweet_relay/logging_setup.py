"""Logging configured so a secret cannot reach a log record (FR-13).

This exists because of a real leak found in 001 (plan A-3): httpx logs every request
URL at INFO, and the first delivery service required its API key as a query
parameter, so the key appeared in ordinary application logs. The bot token is in the
URL path now (spec 003 research R-3), so the same holds. Silencing httpx alone would be brittle
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

    def _arg(self, value):
        # Numbers stay numbers (for %d); anything else is rendered and scrubbed, because
        # an exception object passed as %s renders its message (spec 003 review P-3).
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return value
        return self._scrub(value if isinstance(value, str) else str(value))

    def filter(self, record: logging.LogRecord) -> bool:
        if self.needles:
            if isinstance(record.msg, str):
                record.msg = self._scrub(record.msg)
            if record.args:
                if isinstance(record.args, dict):
                    record.args = {k: self._arg(v) for k, v in record.args.items()}
                else:
                    record.args = tuple(self._arg(a) for a in record.args)
            if record.exc_info and not record.exc_text:
                # Formatters reuse exc_text when it is set, so the traceback is
                # rendered here once, already scrubbed.
                record.exc_text = self._scrub(
                    logging.Formatter().formatException(record.exc_info))
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
