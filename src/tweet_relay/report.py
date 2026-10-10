"""A run's log rendered as a GitHub job summary (plan A-9).

The summary is built from the log, not from in-process state, so that it also covers
runs that crashed or never started: those are exactly the runs that most need a
visible verdict (§7).

The log quotes third-party bytes (mirror warnings, the delivery service's reason) and
GitHub renders the summary as HTML. All log text is HTML-escaped and placed only
inside <pre> blocks, where markdown is not parsed (§4).
"""
from __future__ import annotations

import html
import re

# Every pattern is anchored to a whole line in our own format (plan A-10). Third-party
# text reaches the log inside WARNING lines and, in dry runs, in rendered posts on
# stdout (prefixed "| " by ConsoleSink), and must never be able to forge a mirror,
# a delivered post, or the result line.
_LOG = r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2},\d{3} "
_RESULT = re.compile(r"^sent=(\d+) withheld=(\d+) failed=(\d+) "
                     r"bootstrapped=(True|False) outage=(True|False)"
                     r"(?: dry_run=(True|False))?$", re.M)
_MIRROR = re.compile(_LOG + r"INFO\s+tweet_relay\.sources\.nitter_rss: "
                     r"fetched (\d+) posts from (https://[\w.-]+)$", re.M)
_DELIVERED = re.compile(_LOG + r"INFO\s+tweet_relay\.pipeline: "
                        r"delivered tweet_id=(\d+)$", re.M)
_PROBLEM = re.compile(_LOG + r"(?:WARNING|ERROR|CRITICAL)\s.*$"
                      r"|^Traceback \(most recent call last\):$", re.M)

_MAX_LOG_CHARS = 60_000      # GitHub caps a step summary at 1 MiB


def _pre(text: str) -> str:
    # A blank line before <pre> makes it its own HTML block, which ends only at </pre>;
    # the escaped text cannot contain a literal </pre>.
    return f"\n<pre>\n{html.escape(text)}\n</pre>\n"


def render_summary(log: str, exit_code: int, run_url: str | None, handle: str) -> str:
    results = list(_RESULT.finditer(log))
    result = results[-1] if results else None      # ours is printed last
    dry_run = False
    mirror = _MIRROR.search(log)
    delivered = _DELIVERED.findall(log)
    problems = [m.group(0) for m in _PROBLEM.finditer(log)]

    if result is None:
        headline = f"## ❌ tweet-relay: check did not complete (exit {exit_code})"
    else:
        sent, withheld, failed, bootstrapped, outage, dry = result.groups()
        dry_run = dry == "True"
        ok = exit_code == 0 and failed == "0" and outage == "False"
        icon, verdict = ("✅", "ok") if ok else ("❌", "failed")
        if outage == "True":
            verdict = "no mirror reachable"
        if dry_run:
            # Nothing was sent: never phrase a dry run as a delivery (001 FR-12).
            headline = (f"## {icon} tweet-relay: dry run, {verdict}, would send {sent}, "
                        f"withheld {withheld}")
        else:
            headline = (f"## {icon} tweet-relay: {verdict}, sent {sent}, "
                        f"withheld {withheld}, failed {failed}")
        if bootstrapped == "True":
            headline += ", first run (bootstrapped)"

    lines = [headline, ""]
    if run_url:
        lines.append(f"Run: {run_url}")
    lines.append(f"Mirror: {mirror.group(2)} ({mirror.group(1)} posts)" if mirror
                 else "Mirror: none answered")

    if delivered:
        lines += ["", "### Rendered (dry run)" if dry_run else "### Delivered", ""]
        lines += [f"- https://x.com/{handle}/status/{i}" for i in delivered]

    if problems:
        lines += ["", "### Problems", _pre("\n".join(problems))]

    tail = log[-_MAX_LOG_CHARS:]
    if len(log) > _MAX_LOG_CHARS:
        tail = f"[... {len(log) - _MAX_LOG_CHARS} earlier characters omitted ...]\n" + tail
    lines += ["", "<details><summary>Full log</summary>", _pre(tail), "</details>", ""]
    return "\n".join(lines)
