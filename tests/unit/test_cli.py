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


# --- dry runs (plan A-10) ---

def test_summary_line_states_dry_run(monkeypatch, config, capsys):
    from tweet_relay.pipeline import RunResult
    class FakePipeline:
        def __init__(self, *a, **kw): pass
        def run_once(self): return RunResult(sent=2)
    monkeypatch.setattr(cli, "Pipeline", FakePipeline)
    cli.cmd_run(config, once=True, dry_run=True)
    assert "dry_run=True" in capsys.readouterr().out


def test_dry_run_never_changes_delivery_history(monkeypatch, config):
    """I-4: the documented "sends nothing" check must also *record* nothing, or the
    posts it rendered are marked seen and never delivered for real."""
    import pathlib
    from tests.doubles import FakeSource, RecordingSink, tweet
    from tweet_relay.pipeline import Pipeline
    from tweet_relay.state import load_state
    src = FakeSource([tweet(1, minutes=1)])
    Pipeline(config, src, RecordingSink()).run_once()          # bootstrap
    src.tweets.append(tweet(2, minutes=2))
    before = pathlib.Path(config.STATE_PATH).read_bytes()
    monkeypatch.setattr(cli, "NitterRssSource", lambda cfg: src)
    assert cli.cmd_run(config, once=True, dry_run=True) == 0
    assert pathlib.Path(config.STATE_PATH).read_bytes() == before
    assert load_state(config.STATE_PATH, "santtiagom_").is_new(2)


def test_dry_run_with_no_history_leaves_none_behind(monkeypatch, config):
    import pathlib
    from tests.doubles import FakeSource, tweet
    monkeypatch.setattr(cli, "NitterRssSource", lambda cfg: FakeSource([tweet(1)]))
    cli.cmd_run(config, once=True, dry_run=True)
    assert not pathlib.Path(config.STATE_PATH).exists()


# --- probe-mirrors (spec 002 AC-1.1, AC-1.7, FR-7, FR-19; plan DD-6) ---

def _probe_env(monkeypatch, tmp_path, outcomes, tracker=None):
    import json, socket
    from datetime import datetime, timedelta, timezone
    from tests.doubles import FakeTracker, FixtureMirrorProbe, StaticDirectory
    from tweet_relay import config as config_module
    from tweet_relay.mirrors.directory import DirectoryRead
    monkeypatch.setenv("X_PROFILE_URL", "@santtiagom_")
    monkeypatch.setenv("NITTER_INSTANCES", "https://a.example,https://b.example")
    monkeypatch.setattr(config_module.socket, "getaddrinfo",
                        lambda *a, **k: (_ for _ in ()).throw(socket.gaierror("offline")))
    monkeypatch.setattr(cli, "HttpMirrorProbe", lambda cfg: FixtureMirrorProbe(outcomes))
    monkeypatch.setattr(cli, "StatusD420Directory", lambda cfg: StaticDirectory(DirectoryRead([], 0, 0)))
    if tracker is not None:
        monkeypatch.setattr(cli, "_warning_tracker", lambda: tracker)
    data, site = tmp_path / "data", tmp_path / "site"
    return ["probe-mirrors", "--data", str(data), "--site-out", str(site)], site


def _outcome(good):
    from datetime import datetime, timezone
    from tweet_relay.mirrors.models import ProbeOutcome, Reason
    if good:
        return ProbeOutcome(usable=True, reason=None, ms=50, newest=datetime.now(timezone.utc))
    return ProbeOutcome(usable=False, reason=Reason.SENT_ELSEWHERE, ms=40, newest=None)


def test_probe_mirrors_ok_exits_zero_and_writes_status(monkeypatch, tmp_path, capsys):
    import json
    argv, site = _probe_env(monkeypatch, tmp_path, {"a.example": _outcome(True), "b.example": _outcome(True)})
    assert cli.main(argv) == 0
    assert capsys.readouterr().out.strip().splitlines()[-1] == "cause=ok"
    assert json.loads((site / "status.json").read_text())["round"]["at_risk"] is False


def test_probe_mirrors_at_risk_exits_three_and_names_each_mirror(monkeypatch, tmp_path, capsys):
    """AC-1.1, AC-1.7: the cause and each in-use mirror's state are stated."""
    argv, _ = _probe_env(monkeypatch, tmp_path, {"a.example": _outcome(True), "b.example": _outcome(False)})
    assert cli.main(argv) == 3
    out = capsys.readouterr().out
    assert out.strip().splitlines()[-1] == "cause=at_risk"
    assert "a.example: healthy" in out and "b.example: sent_elsewhere" in out


def test_probe_mirrors_tracker_failure_is_check_broken(monkeypatch, tmp_path, capsys):
    from tests.doubles import FakeTracker
    argv, site = _probe_env(monkeypatch, tmp_path, {"a.example": _outcome(True), "b.example": _outcome(True)},
                            tracker=FakeTracker(fail=True))
    assert cli.main(argv) == 1
    assert capsys.readouterr().out.strip().splitlines()[-1] == "cause=check_broken"
    assert (site / "status.json").exists()                    # still published


def test_probe_mirrors_unexpected_error_is_check_broken(monkeypatch, tmp_path, capsys):
    class Exploding:
        def probe(self, host, handle):
            raise RuntimeError("bug")

        def close(self):
            pass
    argv, _ = _probe_env(monkeypatch, tmp_path, {})
    monkeypatch.setattr(cli, "HttpMirrorProbe", lambda cfg: Exploding())
    assert cli.main(argv) == 1
    assert capsys.readouterr().out.strip().splitlines()[-1] == "cause=check_broken"


def test_probe_mirrors_needs_its_arguments(monkeypatch):
    monkeypatch.setenv("X_PROFILE_URL", "@santtiagom_")
    with pytest.raises(SystemExit) as exc:
        cli.main(["probe-mirrors"])
    assert exc.value.code == 2
