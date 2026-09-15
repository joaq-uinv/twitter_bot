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
