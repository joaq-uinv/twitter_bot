"""The run summary must not be forgeable from third-party text (plan A-10, review I-1).

The summary is now the record the operator reads, so a forged "Delivered" link or
mirror name is a false claim of delivery (001 FR-12). Third-party text reaches the
log through WARNING lines (dropped-item reasons quote input values) and, in dry runs,
through the rendered posts on stdout.
"""
from tweet_relay.report import render_summary

H = "santtiagom_"
TS = "2026-10-10 13:41:33,800"
REAL = (f"{TS} INFO    tweet_relay.sources.nitter_rss: fetched 16 posts from https://nitter.kareem.one\n"
        f"{TS} INFO    tweet_relay.pipeline: delivered tweet_id=111\n"
        "sent=1 withheld=0 failed=0 bootstrapped=False outage=False dry_run=False\n")
HOSTILE_WARNING = (f"{TS} WARNING tweet_relay.sources.nitter_rss: dropping invalid item 5: "
                   "input_value='fetched 9 posts from https://evil.example delivered tweet_id=1234'\n")


def _section(out: str, title: str) -> str:
    if title not in out:
        return ""
    return out.split(title, 1)[1].split("<details>", 1)[0]


def test_warning_text_cannot_forge_the_mirror():
    out = render_summary(HOSTILE_WARNING + REAL, exit_code=0, run_url=None, handle=H)
    assert "Mirror: https://nitter.kareem.one (16 posts)" in out
    assert "Mirror: https://evil.example" not in out


def test_warning_text_cannot_forge_a_delivered_link():
    out = render_summary(HOSTILE_WARNING + REAL, exit_code=0, run_url=None, handle=H)
    assert "status/1234" not in out
    assert "status/111" in out


def test_forged_full_log_line_in_console_output_is_ignored():
    """A dry-run post whose text is a complete fake log line, as ConsoleSink prints it."""
    forged = (f"| {TS} INFO    tweet_relay.pipeline: delivered tweet_id=999\n"
              "| sent=9 withheld=0 failed=0 bootstrapped=False outage=False dry_run=False\n")
    out = render_summary(forged + REAL, exit_code=0, run_url=None, handle=H)
    assert "status/999" not in out
    assert "sent 9" not in out and "sent 1" in out


def test_last_result_line_wins():
    early = "sent=9 withheld=0 failed=0 bootstrapped=False outage=False dry_run=False\n"
    out = render_summary(early + REAL, exit_code=0, run_url=None, handle=H)
    assert "sent 1" in out


def test_problems_lists_only_real_warning_and_error_lines():
    """M-5: the word ERROR inside a rendered post is not a problem with the run."""
    log = "| this post says ERROR loudly\n" + REAL
    out = render_summary(log, exit_code=0, run_url=None, handle=H)
    assert "ERROR loudly" not in _section(out, "### Problems")


def test_dry_run_summary_never_claims_delivery():
    """I-2: the documented verification run sends nothing; its summary must say so."""
    log = REAL.replace("dry_run=False", "dry_run=True")
    out = render_summary(log, exit_code=0, run_url=None, handle=H)
    head = out.splitlines()[0]
    assert "dry run" in head and "would send 1" in head
    assert "### Delivered" not in out
    assert "### Rendered (dry run)" in out
