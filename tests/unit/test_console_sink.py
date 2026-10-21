"""Dry-run sink (spec 003 contract message-sink: ConsoleSink)."""
from tweet_relay.sinks.console import ConsoleSink


def test_prints_the_message_and_its_card(capsys):
    ConsoleSink().send("hello\nworld", preview_url="https://fxtwitter.com/a/status/1")
    out = capsys.readouterr().out.splitlines()
    assert "| hello" in out and "| world" in out
    assert "| card: https://fxtwitter.com/a/status/1" in out
    assert all(line.startswith("| ") for line in out)     # plan A-10: never a log line


def test_a_dry_run_chat_is_always_private():
    assert ConsoleSink().chat_is_private() is True
