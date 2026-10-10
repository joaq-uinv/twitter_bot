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

_RESULT = re.compile(r"^sent=(\d+) withheld=(\d+) failed=(\d+) "
                     r"bootstrapped=(True|False) outage=(True|False)$", re.M)
_MIRROR = re.compile(r"fetched (\d+) posts from (https://[\w.-]+)")
_DELIVERED = re.compile(r"delivered tweet_id=(\d+)")
_PROBLEM = re.compile(r"^.*\b(WARNING|ERROR|CRITICAL)\b.*$|^Traceback.*$", re.M)

_MAX_LOG_CHARS = 60_000      # GitHub caps a step summary at 1 MiB


def _pre(text: str) -> str:
    # A blank line before <pre> makes it its own HTML block, which ends only at </pre>;
    # the escaped text cannot contain a literal </pre>.
    return f"\n<pre>\n{html.escape(text)}\n</pre>\n"


def render_summary(log: str, exit_code: int, run_url: str | None, handle: str) -> str:
    result = _RESULT.search(log)
    mirror = _MIRROR.search(log)
    delivered = _DELIVERED.findall(log)
    problems = [m.group(0) for m in _PROBLEM.finditer(log)]

    if result is None:
        headline = f"## ❌ tweet-relay: check did not complete (exit {exit_code})"
    else:
        sent, withheld, failed, bootstrapped, outage = result.groups()
        ok = exit_code == 0 and failed == "0" and outage == "False"
        icon, verdict = ("✅", "ok") if ok else ("❌", "failed")
        if outage == "True":
            verdict = "no mirror reachable"
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
        lines += ["", "### Delivered", ""]
        lines += [f"- https://x.com/{handle}/status/{i}" for i in delivered]

    if problems:
        lines += ["", "### Problems", _pre("\n".join(problems))]

    tail = log[-_MAX_LOG_CHARS:]
    if len(log) > _MAX_LOG_CHARS:
        tail = f"[... {len(log) - _MAX_LOG_CHARS} earlier characters omitted ...]\n" + tail
    lines += ["", "<details><summary>Full log</summary>", _pre(tail), "</details>", ""]
    return "\n".join(lines)
