"""WhatsApp delivery via CallMeBot.

Two behaviours of this service shape the code: it returns HTML rather than JSON, and
it reports some failures in the body of an HTTP 200. Trusting the status code alone
would mark posts delivered that never arrived (FR-12, E-19).
"""
from __future__ import annotations

import html
import logging
import re
import time

import httpx

from ..models import DeliveryFailed

log = logging.getLogger(__name__)

# Defence in depth: even if the application never calls logging_setup.configure(),
# this module must not cause the key to be logged via httpx's request logging.
logging.getLogger("httpx").setLevel(max(logging.WARNING,
                                        logging.getLogger("httpx").level or 0))

ENDPOINT = "https://api.callmebot.com/whatsapp.php"

# Observed success body (live, 2026-09-15):
#   <p>Message to: +54...<p>Text to send: <OUR MESSAGE><p><b>Message queued.</b> ...
# Note that it echoes our own message back. Scanning the raw body for error words
# therefore misreads a successful send whenever the post itself contains one.
_SUCCESS_BODY = re.compile(r"\bqueued\b", re.I)
_ERROR_BODY = re.compile(r"\b(error|invalid|not\s+registered|must\s+provide|apikey)\b", re.I)


def _judge(body: str, sent_text: str) -> bool | None:
    """True = delivered, False = refused, None = unrecognised.

    The echoed payload is removed first so we judge the service's own words, never
    the post's. Both raw and HTML-escaped forms are stripped, since the echo may be
    escaped.
    """
    residual = body
    for echo in (sent_text, html.escape(sent_text), html.escape(sent_text, quote=False)):
        if echo:
            residual = residual.replace(echo, " ")
    if _SUCCESS_BODY.search(residual):
        return True
    if _ERROR_BODY.search(residual):
        return False
    return None


class CallMeBotSink:
    name = "callmebot"

    def __init__(self, config, client: httpx.Client | None = None,
                 pace_seconds: float = 3.0, max_attempts: int = 3):
        self.config = config
        self._client = client
        self.pace_seconds = pace_seconds
        self.max_attempts = max_attempts
        self._last_send = 0.0

    def __repr__(self) -> str:       # never render the key (FR-13)
        return f"CallMeBotSink(phone={self.config.CALLMEBOT_PHONE!r})"

    def _pace(self) -> None:
        gap = time.monotonic() - self._last_send
        if gap < self.pace_seconds:
            time.sleep(self.pace_seconds - gap)

    def send(self, message: str) -> None:
        client = self._client or httpx.Client(
            timeout=httpx.Timeout(self.config.REQUEST_TIMEOUT_SECONDS),
            follow_redirects=False)
        # Params go through httpx's encoder. Never build this URL by interpolation:
        # post text is attacker-influenced and would otherwise alter the request (E-11).
        params = {
            "phone": self.config.CALLMEBOT_PHONE,
            "text": message,
            "apikey": self.config.CALLMEBOT_APIKEY.get_secret_value(),
        }
        last_error = "no attempt made"
        try:
            for attempt in range(1, self.max_attempts + 1):
                self._pace()
                try:
                    response = client.get(ENDPOINT, params=params)
                    self._last_send = time.monotonic()
                    body = (response.text or "").strip()
                    if response.status_code >= 500:
                        last_error = f"HTTP {response.status_code}"
                    elif response.status_code >= 400:
                        raise DeliveryFailed(f"rejected with HTTP {response.status_code}")
                    else:
                        verdict = _judge(body, message)
                        if verdict is True:
                            return
                        if verdict is False:
                            # A 200 that describes a failure (E-19).
                            raise DeliveryFailed(
                                f"service reported an error: {body[:120]!r}")
                        # FR-12: an unrecognised body is not evidence of delivery.
                        raise DeliveryFailed(
                            f"unrecognised response, not treating as delivered: "
                            f"{body[:120]!r}")
                except httpx.HTTPError as exc:
                    last_error = type(exc).__name__
                if attempt < self.max_attempts:
                    time.sleep(min(2 ** attempt, 10))
        finally:
            if self._client is None:
                client.close()
        # last_error never contains the key: only status codes and exception types.
        raise DeliveryFailed(f"delivery failed after {self.max_attempts} attempts: {last_error}")
