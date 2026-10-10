"""Run summary rendered from a run's log (plan A-9).

The log is our own output, but it quotes third-party bytes: mirror warnings and the
delivery service's failure reason. It is rendered into a page GitHub displays as
HTML, so it is treated as hostile (§4).
"""
from tweet_relay.report import render_summary

H = "santtiagom_"
RUN = "https://github.com/o/r/actions/runs/1"

CLEAN = """\
2026-10-10 13:41:33,800 INFO    tweet_relay.sources.nitter_rss: fetched 16 posts from https://nitter.kareem.one
2026-10-10 13:41:34,100 INFO    tweet_relay.pipeline: delivered tweet_id=2107969700978409979
2026-10-10 13:41:37,200 INFO    tweet_relay.pipeline: delivered tweet_id=2107970999408877664
2026-10-10 13:41:37,300 INFO    tweet_relay.pipeline: check complete: sent=2 withheld=0
sent=2 withheld=0 failed=0 bootstrapped=False outage=False
"""

FAILED = """\
2026-10-10 13:41:33,800 INFO    tweet_relay.sources.nitter_rss: fetched 16 posts from https://nitter.kareem.one
2026-10-10 13:41:34,395 ERROR   tweet_relay.pipeline: delivery failed for 2107969700978409979, stopping batch: unrecognised response, not treating as delivered: 'Your Account is Paused'
sent=0 withheld=6 failed=1 bootstrapped=False outage=False
"""


def test_clean_run_headline_reports_success_and_counts():
    out = render_summary(CLEAN, exit_code=0, run_url=RUN, handle=H)
    assert "✅" in out.splitlines()[0]
    assert "sent 2" in out


def test_clean_run_names_the_mirror_that_answered():
    assert "nitter.kareem.one" in render_summary(CLEAN, exit_code=0, run_url=RUN, handle=H)


def test_every_delivered_post_is_linked():
    out = render_summary(CLEAN, exit_code=0, run_url=RUN, handle=H)
    assert f"https://x.com/{H}/status/2107969700978409979" in out
    assert f"https://x.com/{H}/status/2107970999408877664" in out


def test_failed_run_headline_and_reason():
    out = render_summary(FAILED, exit_code=1, run_url=RUN, handle=H)
    assert "❌" in out.splitlines()[0]
    assert "Your Account is Paused" in out


def test_run_that_never_finished_says_so():
    """A crash or build failure leaves no summary line; that must not read as quiet."""
    out = render_summary("Traceback (most recent call last):\n  boom\n", exit_code=2,
                         run_url=RUN, handle=H)
    assert "❌" in out.splitlines()[0]
    assert "did not complete" in out


def test_non_zero_exit_is_never_reported_as_success():
    out = render_summary(CLEAN, exit_code=1, run_url=RUN, handle=H)
    assert "✅" not in out


def test_full_log_is_included():
    out = render_summary(CLEAN, exit_code=0, run_url=RUN, handle=H)
    assert "check complete: sent=2" in out


def test_run_url_is_included():
    assert RUN in render_summary(CLEAN, exit_code=0, run_url=RUN, handle=H)


def test_html_in_the_log_is_escaped():
    hostile = FAILED + "2026-10-10 WARNING x: <script>alert(1)</script></pre></details>\n"
    out = render_summary(hostile, exit_code=1, run_url=RUN, handle=H)
    assert "<script>" not in out
    assert "</pre></details>" not in out
    assert "&lt;script&gt;" in out


def test_markdown_in_the_log_cannot_break_out_of_its_block():
    hostile = FAILED + "\n\n# Injected heading\n[click](https://evil.example)\n"
    out = render_summary(hostile, exit_code=1, run_url=RUN, handle=H)
    # Every log line must sit inside a <pre> block, where markdown is not parsed.
    outside = out.split("<pre>")[0] + "".join(p.split("</pre>", 1)[1] for p in out.split("<pre>")[1:])
    assert "# Injected heading" not in outside
    assert "evil.example" not in outside


def test_very_long_logs_are_truncated():
    out = render_summary("x" * 2_000_000, exit_code=2, run_url=RUN, handle=H)
    assert len(out) < 200_000
