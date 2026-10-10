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
from urllib.parse import quote

import httpx

from ..models import DeliveryFailed, MessageRejected

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
_TAG = re.compile(r"<[^>]*>")
# E-21/D-4: only these refusals can be about one particular message, and only when the
# service's words do not point at the account or at rate limiting. 401/404/429 and
# anything mentioning keys, limits or a paused account are channel problems.
_MESSAGE_REFUSAL_CODES = frozenset({400, 403, 413, 414, 422})
_CHANNEL_WORDING = re.compile(
    r"\b(?:too\s+many|rate[\s-]*limit\w*|rate|limit\w*|quota|blocked|paused|"
    r"api\s*key|invalid|not\s+registered|unauthori[sz]ed)\b", re.I)
_REASON_CHARS = 300


def _strip_echo(body: str, sent_text: str) -> str:
    """The body minus our own echoed payload, raw or HTML-escaped."""
    for echo in (sent_text, html.escape(sent_text), html.escape(sent_text, quote=False)):
        if echo:
            body = body.replace(echo, " ")
    return body


def _judge(body: str, sent_text: str) -> bool | None:
    """True = delivered, False = refused, None = unrecognised.

    The echoed payload is removed first so we judge the service's own words, never
    the post's.
    """
    residual = _strip_echo(body, sent_text)
    if _SUCCESS_BODY.search(residual):
        return True
    if _ERROR_BODY.search(residual):
        return False
    return None


def _reason(body: str, sent_text: str, secrets: list[str]) -> str:
    """The service's own words, fit for an exception message and a log line (§7).

    Found live on 2026-10-09: a paused account failed every send for three weeks
    while the log showed only the first 120 characters of the body, which are always
    our echoed text. The cause sat just past the cut.

    The body is third-party input on its way into logs, so every form of the key is
    removed before truncation (a cut could otherwise leave part of it) and again
    after unescaping (which could reassemble an escaped form) - FR-13.

    The phone number goes too: the body opens with "Message to: <phone>", and run logs
    leave GitHub's masked log viewer for the run summary and the uptime monitor (A-9).
    """
    forms = sorted({f for s in secrets if s
                    for f in (s, s.lstrip("+"), quote(s, safe=""), html.escape(s)) if f},
                   key=len, reverse=True)

    def scrub(text: str) -> str:
        for form in forms:
            text = text.replace(form, "***")
        return text

    # Scrubbed before the echo is stripped as well: removing an echo that happens to be
    # a prefix of a secret would otherwise leave a remainder no scrub form matches.
    text = scrub(_strip_echo(scrub(body), sent_text))
    text = scrub(html.unescape(_TAG.sub(" ", text)))
    return " ".join(text.split())[:_REASON_CHARS]


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
                        reason = _reason(body, message, [params["apikey"], params["phone"]])
                        detail = f"rejected with HTTP {response.status_code}: {reason!r}"
                        if (response.status_code in _MESSAGE_REFUSAL_CODES
                                and not _CHANNEL_WORDING.search(reason)):
                            # A refusal of this particular message (E-21): the 403 seen
                            # live on 2026-10-10 blocked one post while others went through.
                            raise MessageRejected(detail)
                        # Account, key or rate-limit trouble: a retry only adds traffic.
                        raise DeliveryFailed(detail)
                    else:
                        verdict = _judge(body, message)
                        if verdict is True:
                            return
                        reason = _reason(body, message, [params["apikey"], params["phone"]])
                        if verdict is False:
                            # A 200 that describes a failure (E-19).
                            raise DeliveryFailed(f"service reported an error: {reason!r}")
                        # FR-12: an unrecognised body is not evidence of delivery.
                        raise DeliveryFailed(
                            f"unrecognised response, not treating as delivered: {reason!r}")
                except httpx.HTTPError as exc:
                    last_error = type(exc).__name__
                if attempt < self.max_attempts:
                    time.sleep(min(2 ** attempt, 10))
        finally:
            if self._client is None:
                client.close()
        # last_error never contains the key: only status codes and exception types.
        raise DeliveryFailed(f"delivery failed after {self.max_attempts} attempts: {last_error}")
