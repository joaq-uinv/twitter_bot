"""The backstop redaction filter (logging_setup). The sources must not leak in the
first place (spec 003 DD-8); this catches what slips through (review P-3, m-4)."""
import logging

from tweet_relay.logging_setup import SecretRedactingFilter

SECRET = "TOPSECRET-value-1234"


def formatted(record):
    SecretRedactingFilter([SECRET]).filter(record)
    return logging.Formatter("%(message)s").format(record)


def record(msg, args=(), exc_info=None):
    return logging.LogRecord("t", logging.ERROR, __file__, 1, msg, args, exc_info)


def test_string_arguments_are_scrubbed():
    assert SECRET not in formatted(record("x %s", (SECRET,)))


def test_non_string_arguments_are_scrubbed():
    """An exception object passed as %s renders its message, which may hold a secret."""
    assert SECRET not in formatted(record("failed: %s", (ValueError(f"url /bot{SECRET}/x"),)))


def test_tracebacks_are_scrubbed():
    try:
        raise RuntimeError(f"GET /bot{SECRET}/sendMessage")
    except RuntimeError:
        import sys
        out = formatted(record("boom", exc_info=sys.exc_info()))
    assert SECRET not in out and "RuntimeError" in out
