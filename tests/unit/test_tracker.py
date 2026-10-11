"""GitHubIssueTracker: soft warnings as GitHub issues (spec 002 FR-10, AC-2.3, AC-2.4,
§6; contract warning-tracker.md; plan DD-8). The REST API is faked with respx."""
import json
import logging
from datetime import datetime, timezone

import httpx
import pytest
import respx

from tweet_relay.mirrors.models import Reason
from tweet_relay.mirrors.tracker import LABEL, GitHubIssueTracker, TrackerUnavailable, title_for

API = "https://api.github.com/repos/joaq-uinv/twitter_bot"
TOKEN = "ghs_test-token-do-not-log"
T = datetime(2026, 10, 11, 12, 0, tzinfo=timezone.utc)


def tracker():
    return GitHubIssueTracker(token=TOKEN, repo="joaq-uinv/twitter_bot", now=lambda: T)


def issue(n, host, created="2026-10-10T08:00:00Z", **extra):
    return {"number": n, "title": title_for(host), "created_at": created, "labels": [{"name": LABEL}],
            **extra}


def listing(*issues):
    return respx.get(f"{API}/issues").mock(httpx.Response(200, json=list(issues)))


def test_title_is_fixed_text_plus_host():
    assert title_for("nitter.pp.ua") == "Mirror unhealthy for 24h: nitter.pp.ua"


@respx.mock
def test_open_warnings_are_read_by_label_and_exact_title():
    route = listing(issue(7, "nitter.pp.ua"),
                    {"number": 8, "title": "Something else", "created_at": "2026-10-10T08:00:00Z"},
                    issue(9, "a.example", pull_request={"url": "x"}),          # a PR, not an issue
                    {"number": 10, "title": "Mirror unhealthy for 24h: <bad host>",
                     "created_at": "2026-10-10T08:00:00Z"})
    assert tracker().open_warnings() == {"nitter.pp.ua": datetime(2026, 10, 10, 8, tzinfo=timezone.utc)}
    params = route.calls[0].request.url.params
    assert params["labels"] == LABEL and params["state"] == "open"
    assert route.calls[0].request.headers["authorization"] == f"Bearer {TOKEN}"


@respx.mock
def test_open_creates_one_labelled_issue():
    listing()
    create = respx.post(f"{API}/issues").mock(httpx.Response(201, json={"number": 11}))
    tracker().open("nitter.pp.ua", T, Reason.TIMED_OUT)
    body = json.loads(create.calls[0].request.content)
    assert body["title"] == title_for("nitter.pp.ua") and body["labels"] == [LABEL]
    assert "timed_out" in body["body"] and "joaq-uinv.github.io/twitter_bot" in body["body"]


@respx.mock
def test_open_is_idempotent():
    """Contract 1: a rerun after a partial failure must not duplicate the issue."""
    listing(issue(7, "nitter.pp.ua"))
    create = respx.post(f"{API}/issues").mock(httpx.Response(201, json={"number": 11}))
    tracker().open("nitter.pp.ua", T, Reason.TIMED_OUT)
    assert create.call_count == 0


@respx.mock
def test_update_adds_one_comment():
    """AC-2.3."""
    listing(issue(7, "nitter.pp.ua"))
    comment = respx.post(f"{API}/issues/7/comments").mock(httpx.Response(201, json={}))
    tracker().update("nitter.pp.ua", Reason.SENT_ELSEWHERE)
    assert comment.call_count == 1
    assert "sent_elsewhere" in json.loads(comment.calls[0].request.content)["body"]


@respx.mock
def test_close_comments_then_closes():
    """AC-2.4."""
    listing(issue(7, "nitter.pp.ua"))
    comment = respx.post(f"{API}/issues/7/comments").mock(httpx.Response(201, json={}))
    patch = respx.patch(f"{API}/issues/7").mock(httpx.Response(200, json={}))
    tracker().close("nitter.pp.ua")
    assert comment.call_count == 1
    assert json.loads(patch.calls[0].request.content) == {"state": "closed"}


@respx.mock
@pytest.mark.parametrize("response", [httpx.Response(401, text=f"bad credentials {TOKEN}"),
                                      httpx.Response(403, text="rate limited"),
                                      httpx.Response(502)])
def test_api_failures_raise_tracker_unavailable_without_the_token(response, caplog):
    respx.get(f"{API}/issues").mock(response)
    with caplog.at_level(logging.DEBUG):
        with pytest.raises(TrackerUnavailable) as exc:
            tracker().open_warnings()
    assert TOKEN not in str(exc.value) and TOKEN not in repr(exc.value)
    assert TOKEN not in caplog.text


@respx.mock
def test_network_failure_raises_tracker_unavailable():
    respx.get(f"{API}/issues").mock(side_effect=httpx.ConnectError("down"))
    with pytest.raises(TrackerUnavailable):
        tracker().open_warnings()


def test_repr_hides_the_token():
    assert TOKEN not in repr(tracker())


def test_cli_uses_github_tracker_only_with_credentials(monkeypatch):
    from tweet_relay import cli
    from tweet_relay.mirrors.tracker import NullTracker
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    assert isinstance(cli._warning_tracker(), NullTracker)
    monkeypatch.setenv("GITHUB_TOKEN", TOKEN)
    monkeypatch.setenv("GITHUB_REPOSITORY", "joaq-uinv/twitter_bot")
    assert isinstance(cli._warning_tracker(), GitHubIssueTracker)
