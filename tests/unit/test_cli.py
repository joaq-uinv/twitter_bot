"""CLI behaviour. Config errors must be actionable and must not restart-loop."""
import os, pytest
os.environ.setdefault("CONFIG_ERROR_PAUSE_SECONDS", "0")
from tweet_relay import cli


def test_missing_delivery_credentials_exits_two_with_guidance(monkeypatch, capsys):
    monkeypatch.setenv("X_PROFILE_URL", "@santtiagom_")
    monkeypatch.setenv("CALLMEBOT_PHONE", "")
    monkeypatch.setenv("CALLMEBOT_APIKEY", "")
    monkeypatch.setattr(cli, "CONFIG_ERROR_PAUSE", 0)
    with pytest.raises(SystemExit) as exc:
        cli.main(["run", "--once"])
    assert exc.value.code == 2
    err = capsys.readouterr().err
    assert "CALLMEBOT_PHONE" in err and "callmebot" in err.lower()


def test_malformed_profile_url_exits_two(monkeypatch, capsys):
    """AC-5.2."""
    monkeypatch.setenv("X_PROFILE_URL", "https://evil.example.com/someone")
    monkeypatch.setattr(cli, "CONFIG_ERROR_PAUSE", 0)
    with pytest.raises(SystemExit) as exc:
        cli.main(["run", "--once"])
    assert exc.value.code == 2


def test_dry_run_needs_no_delivery_credentials(monkeypatch):
    """Diagnostics must work before CallMeBot is set up."""
    monkeypatch.setenv("X_PROFILE_URL", "@santtiagom_")
    monkeypatch.setenv("CALLMEBOT_PHONE", "")
    monkeypatch.setenv("CALLMEBOT_APIKEY", "")
    cfg = cli.Config()
    cfg.require_delivery  # exists
    with pytest.raises(ValueError):
        cfg.require_delivery()


# --- regression: a failed delivery exited 0 (2026-10-10, plan A-8) ---
#
# The pipeline recorded result.failed, but `run --once` only exited non-zero on a
# source outage. Three weeks of paused-account runs were all green in GitHub Actions,
# so the platform's own failure email - the one channel that does not depend on
# the delivery service - never fired (§7).

def _run_once_with(monkeypatch, config, result):
    from tweet_relay.pipeline import RunResult
    class FakePipeline:
        def __init__(self, *a, **kw): pass
        def run_once(self): return RunResult(**result)
    monkeypatch.setattr(cli, "Pipeline", FakePipeline)
    return cli.cmd_run(config, once=True, dry_run=False)


def test_failed_delivery_exits_non_zero(monkeypatch, config):
    assert _run_once_with(monkeypatch, config, {"sent": 0, "withheld": 6, "failed": 1}) == 1


def test_partial_delivery_then_failure_exits_non_zero(monkeypatch, config):
    assert _run_once_with(monkeypatch, config, {"sent": 3, "failed": 1}) == 1


def test_clean_run_exits_zero(monkeypatch, config):
    assert _run_once_with(monkeypatch, config, {"sent": 2}) == 0


def test_summary_line_reports_failures(monkeypatch, config, capsys):
    _run_once_with(monkeypatch, config, {"failed": 1})
    assert "failed=1" in capsys.readouterr().out


# --- summarize (plan A-9) ---

def test_summarize_renders_stdin_without_any_configuration(monkeypatch, capsys):
    """It must explain the runs that died on bad config, so it cannot need config."""
    import io
    monkeypatch.setattr("sys.stdin", io.StringIO("Configuration error:\n\nboom\n"))
    code = cli.main(["summarize", "--exit-code", "2", "--handle", "santtiagom_",
                     "--run-url", "https://github.com/o/r/actions/runs/1"])
    out = capsys.readouterr().out
    assert code == 0
    assert "did not complete" in out and "runs/1" in out
