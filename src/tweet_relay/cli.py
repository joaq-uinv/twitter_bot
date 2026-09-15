"""Entrypoint. Every command is safe to run before the relay is trusted."""
from __future__ import annotations

import argparse
import logging
import sys
from datetime import datetime, timedelta, timezone

from . import logging_setup
from .config import Config
from .models import DeliveryFailed, SourceUnavailable
from .pipeline import Pipeline
from .sinks.callmebot import CallMeBotSink
from .sinks.console import ConsoleSink
from .sources.nitter_rss import NitterRssSource
from .state import load_state

log = logging.getLogger("tweet_relay")


def _load() -> Config:
    try:
        return Config()
    except Exception as exc:
        # AC-5.2: refuse to start, and say what is wrong.
        print(f"Configuration error:\n\n{exc}\n\nSee .env.example.", file=sys.stderr)
        raise SystemExit(2)


def _setup(config: Config) -> None:
    logging_setup.configure(config.LOG_LEVEL,
                            secrets=[config.CALLMEBOT_APIKEY.get_secret_value()])


def cmd_check_source(config: Config) -> int:
    """Read-only: which mirror answered, and what it parsed."""
    source = NitterRssSource(config)
    try:
        tweets = source.fetch(config.handle)
    except SourceUnavailable as exc:
        print(f"✗ No source available for @{config.handle}\n  {exc}", file=sys.stderr)
        print("\nMirrors die regularly. See quickstart.md to refresh NITTER_INSTANCES.",
              file=sys.stderr)
        return 1
    print(f"✓ Retrieved {len(tweets)} posts for @{config.handle}\n")
    for t in tweets[-10:]:
        print(f"  {t.published_at:%Y-%m-%d %H:%M}  {t.kind.value:<8} "
              f"@{t.author:<16} {t.text[:52]!r}")
    if len(tweets) > 10:
        print(f"\n  (showing the 10 most recent of {len(tweets)})")
    return 0


def _require_delivery_or_exit(config: Config) -> None:
    try:
        config.require_delivery()
    except ValueError as exc:
        print(f"Configuration error:\n\n{exc}", file=sys.stderr)
        raise SystemExit(2)


def cmd_test_whatsapp(config: Config) -> int:
    _require_delivery_or_exit(config)
    sink = CallMeBotSink(config, pace_seconds=0)
    try:
        sink.send(f"🧪 tweet-relay test message for @{config.handle}. "
                  "If you can read this, delivery works.")
    except DeliveryFailed as exc:
        print(f"✗ Delivery failed: {exc}", file=sys.stderr)
        print("\nCheck CALLMEBOT_PHONE (E.164, e.g. +34600111222) and CALLMEBOT_APIKEY.\n"
              "To get a key: WhatsApp +34 644 51 95 23 with\n"
              "  I allow callmebot to send me messages", file=sys.stderr)
        return 1
    print("✓ Sent. Check your phone.")
    return 0


def cmd_run(config: Config, once: bool, dry_run: bool) -> int:
    if not dry_run:
        _require_delivery_or_exit(config)
    source = NitterRssSource(config)
    sink = ConsoleSink() if dry_run else CallMeBotSink(config)
    pipeline = Pipeline(config, source, sink)

    if once:
        result = pipeline.run_once()
        print(f"sent={result.sent} withheld={result.withheld} "
              f"bootstrapped={result.bootstrapped} outage={result.outage}")
        return 1 if result.outage else 0

    from .scheduler import run_forever
    run_forever(pipeline, config.poll_interval_seconds)
    return 0


def cmd_healthcheck(config: Config) -> int:
    """Container healthcheck: has a check succeeded recently enough?"""
    state = load_state(config.STATE_PATH, config.handle)
    if state.last_success is None:
        return 0 if not state.bootstrapped else 1
    age = datetime.now(timezone.utc) - state.last_success
    limit = timedelta(seconds=config.poll_interval_seconds * 3)
    if age > limit:
        print(f"last success {age} ago, over {limit}", file=sys.stderr)
        return 1
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="tweet-relay",
                                     description="Relay new X posts to WhatsApp.")
    sub = parser.add_subparsers(dest="command")

    run = sub.add_parser("run", help="run the relay (default)")
    run.add_argument("--once", action="store_true", help="one check, then exit")
    run.add_argument("--dry-run", action="store_true",
                     help="print messages instead of sending them")
    sub.add_parser("check-source", help="show which mirror answers and what it parses")
    sub.add_parser("test-whatsapp", help="send one real test message")
    sub.add_parser("healthcheck", help="exit non-zero if checks have stalled")

    args = parser.parse_args(argv)
    config = _load()
    _setup(config)

    match args.command:
        case "check-source":
            return cmd_check_source(config)
        case "test-whatsapp":
            return cmd_test_whatsapp(config)
        case "healthcheck":
            return cmd_healthcheck(config)
        case _:
            return cmd_run(config, getattr(args, "once", False),
                           getattr(args, "dry_run", False))


if __name__ == "__main__":
    raise SystemExit(main())
