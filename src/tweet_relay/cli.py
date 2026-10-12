"""Entrypoint. Every command is safe to run before the relay is trusted."""
from __future__ import annotations

import argparse
import logging
import os
import shutil
import sys
import tempfile
import time
from datetime import datetime, timedelta, timezone

from . import logging_setup
from .config import Config
from .mirrors.directory import StatusD420Directory
from .mirrors.history import DirHistoryStore
from .mirrors.probe import HttpMirrorProbe
from .mirrors.round import run_round
from .mirrors.tracker import GitHubIssueTracker, NullTracker
from .models import DeliveryFailed, SourceUnavailable
from .pipeline import Pipeline
from .sinks.callmebot import CallMeBotSink
from .sinks.console import ConsoleSink
from .sources.nitter_rss import NitterRssSource
from .state import StateUnwritable, load_state

log = logging.getLogger("tweet_relay")


# A misconfiguration is permanent: restarting cannot fix a missing credential. Under
# `restart: unless-stopped` an immediate exit becomes a tight restart loop that floods
# the logs, so pause first to keep the real error readable. Zero in tests.
CONFIG_ERROR_PAUSE = float(os.environ.get("CONFIG_ERROR_PAUSE_SECONDS", "15"))


def _config_error(message: str) -> "SystemExit":
    print(f"Configuration error:\n\n{message}\n\nSee .env.example.", file=sys.stderr)
    if CONFIG_ERROR_PAUSE > 0:
        print(f"Pausing {CONFIG_ERROR_PAUSE:.0f}s before exit so this does not "
              "restart-loop. Fix .env, then the relay starts normally.",
              file=sys.stderr, flush=True)
        time.sleep(CONFIG_ERROR_PAUSE)
    return SystemExit(2)


def _load() -> Config:
    try:
        return Config()
    except Exception as exc:
        # AC-5.2: refuse to start, and say what is wrong.
        raise _config_error(str(exc))


def _setup(config: Config) -> None:
    logging_setup.configure(config.LOG_LEVEL,
                            secrets=[config.CALLMEBOT_APIKEY.get_secret_value(),
                                     os.environ.get("GITHUB_TOKEN", "")])


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
        raise _config_error(str(exc))


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
        return _run(config, once, dry_run)
    # A dry run works on a throwaway copy of the delivery history (plan A-10). The
    # pipeline marks rendered posts as seen; against the real history, the documented
    # "sends nothing" check would make every pending post undeliverable.
    with tempfile.TemporaryDirectory(prefix="tweet-relay-dry-run-") as scratch:
        copy = os.path.join(scratch, "seen.json")
        if os.path.exists(config.STATE_PATH):
            shutil.copyfile(config.STATE_PATH, copy)
        return _run(config.model_copy(update={"STATE_PATH": copy}), once, dry_run)


def _run(config: Config, once: bool, dry_run: bool) -> int:
    source = NitterRssSource(config)
    sink = ConsoleSink() if dry_run else CallMeBotSink(config)
    pipeline = Pipeline(config, source, sink)

    if once:
        try:
            result = pipeline.run_once()
        except StateUnwritable as exc:
            print(f"Cannot start:\n\n{exc}", file=sys.stderr)
            return 2
        print(f"sent={result.sent} withheld={result.withheld} failed={result.failed} "
              f"bootstrapped={result.bootstrapped} outage={result.outage} dry_run={dry_run}")
        # Non-zero on a delivery failure too: a scheduler's failure notice is the one
        # alarm that does not travel through the delivery channel (plan A-8, §7).
        return 1 if result.outage or result.failed else 0

    from .scheduler import run_forever
    run_forever(pipeline, config.poll_interval_seconds)
    return 0


def _warning_tracker():
    """Where soft warnings go (spec 002 FR-10, DD-8): GitHub issues in Actions, where
    GITHUB_TOKEN and GITHUB_REPOSITORY exist; nowhere in local runs, and it says so."""
    token, repo = os.environ.get("GITHUB_TOKEN"), os.environ.get("GITHUB_REPOSITORY")
    if token and repo:
        return GitHubIssueTracker(token=token, repo=repo)
    log.info("no warning tracker configured; soft warnings are not tracked in this run")
    return NullTracker()


def cmd_probe_mirrors(config: Config, data: str, site_out: str) -> int:
    """One mirror-health round (spec 002). Exit 0 ok, 3 at risk, 1 check broken (DD-6).

    Read-only with respect to delivery: needs no CallMeBot credentials (FR-19).
    """
    import json
    from pathlib import Path

    probe = HttpMirrorProbe(config)
    try:
        out = run_round(config=config, probe=probe, directory=StatusD420Directory(config),
                        store=DirHistoryStore(data), tracker=_warning_tracker(),
                        now=datetime.now(timezone.utc).replace(microsecond=0))
    except Exception:
        log.exception("mirror probe round failed")
        print("cause=check_broken")
        return 1
    finally:
        probe.close()

    site = Path(site_out)
    site.mkdir(parents=True, exist_ok=True)
    (site / "status.json").write_text(json.dumps(out.status, indent=2) + "\n", encoding="utf-8")
    # P-1: the page ships in the package; one directory holds page + data for Pages.
    for asset in ("index.html", "app.js", "style.css"):
        shutil.copyfile(Path(__file__).parent / "site" / asset, site / asset)

    v = out.verdict
    print(f"{v.in_use_healthy} of {v.in_use_total} in-use mirrors healthy")
    for r in out.round.results:
        if r.role.value == "in_use":
            print(f"in_use {r.host}: {'healthy' if r.healthy else r.reason.value}")
    if out.tracker_error:
        print("warning tracker unavailable: soft warnings were not updated")
    # At risk outranks a tracker problem: it is the urgent signal (AC-1.7).
    if v.at_risk:
        print("cause=at_risk")
        return 3
    if out.tracker_error:
        print("cause=check_broken")
        return 1
    print("cause=ok")
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
    pm = sub.add_parser("probe-mirrors", help="probe every mirror and publish status (spec 002)")
    pm.add_argument("--data", required=True, help="directory holding history.jsonl/latest.json")
    pm.add_argument("--site-out", required=True, help="directory to write status.json into")
    summ = sub.add_parser("summarize", help="render a run's log (stdin) as a job summary")
    summ.add_argument("--exit-code", type=int, required=True)
    summ.add_argument("--handle", required=True)
    summ.add_argument("--run-url")

    args = parser.parse_args(argv)
    if args.command == "summarize":
        # Before _load(): it must also explain runs that died on bad config.
        from .report import render_summary
        print(render_summary(sys.stdin.read(), args.exit_code, args.run_url, args.handle))
        return 0
    config = _load()
    _setup(config)

    match args.command:
        case "check-source":
            return cmd_check_source(config)
        case "test-whatsapp":
            return cmd_test_whatsapp(config)
        case "healthcheck":
            return cmd_healthcheck(config)
        case "probe-mirrors":
            return cmd_probe_mirrors(config, args.data, args.site_out)
        case _:
            return cmd_run(config, getattr(args, "once", False),
                           getattr(args, "dry_run", False))


if __name__ == "__main__":
    raise SystemExit(main())
