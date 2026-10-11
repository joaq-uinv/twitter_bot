"""Mirror-health value types (spec 002 FR-5, FR-6, FR-16; data-model.md).

Everything published is a validated host, a member of a closed set, a time or a
number. These types make that structural: there is nowhere to put free text.
"""
import dataclasses
from datetime import datetime, timezone

import pytest

from tweet_relay.mirrors.models import Freshness, ProbeOutcome, ProbeResult, Reason, Role

T = datetime(2026, 10, 11, 12, 0, tzinfo=timezone.utc)


def test_reason_is_exactly_the_closed_set():
    assert {r.value for r in Reason} == {
        "timed_out", "unreachable", "refused_answer", "sent_elsewhere", "too_large",
        "malformed_content", "wrong_account", "no_posts", "stale", "refused_address"}


def test_role_and_freshness_are_exact():
    assert {r.value for r in Role} == {"in_use", "former", "candidate"}
    assert {f.value for f in Freshness} == {"fresh", "stale", "unknown"}


@pytest.mark.parametrize("cls,allowed", [(ProbeOutcome, set()), (ProbeResult, {"host"})])
def test_no_free_text_fields(cls, allowed):
    """FR-16: the only string a result may carry is the validated host."""
    texty = {f.name for f in dataclasses.fields(cls) if "str" in str(f.type).split(" | ")}
    assert texty == allowed


def test_outcome_reason_present_iff_unusable():
    ProbeOutcome(usable=True, reason=None, ms=10, newest=T)
    ProbeOutcome(usable=False, reason=Reason.TIMED_OUT, ms=None, newest=None)
    with pytest.raises(ValueError):
        ProbeOutcome(usable=True, reason=Reason.TIMED_OUT, ms=10, newest=T)
    with pytest.raises(ValueError):
        ProbeOutcome(usable=False, reason=None, ms=None, newest=None)


def test_outcome_newest_present_iff_usable():
    with pytest.raises(ValueError):
        ProbeOutcome(usable=True, reason=None, ms=10, newest=None)
    with pytest.raises(ValueError):
        ProbeOutcome(usable=False, reason=Reason.NO_POSTS, ms=5, newest=T)


def _result(**kw):
    base = dict(t=T, host="nitter.pp.ua", role=Role.IN_USE, usable=True,
                freshness=Freshness.FRESH, reason=None, ms=10, newest=T)
    return ProbeResult(**{**base, **kw})


def test_result_freshness_absent_iff_unusable():
    _result(usable=False, freshness=None, reason=Reason.UNREACHABLE, newest=None, ms=None)
    with pytest.raises(ValueError):
        _result(freshness=None)
    with pytest.raises(ValueError):
        _result(usable=False, freshness=Freshness.FRESH, reason=Reason.UNREACHABLE, newest=None)


def test_result_stale_reason_iff_usable_and_stale():
    _result(freshness=Freshness.STALE, reason=Reason.STALE)
    with pytest.raises(ValueError):
        _result(freshness=Freshness.STALE, reason=None)
    with pytest.raises(ValueError):
        _result(usable=False, freshness=None, reason=Reason.STALE, newest=None)


@pytest.mark.parametrize("freshness,healthy", [
    (Freshness.FRESH, True), (Freshness.UNKNOWN, True), (Freshness.STALE, False)])
def test_healthy_counts_unknown_freshness(freshness, healthy):
    """D-4: unknown freshness is healthy."""
    reason = Reason.STALE if freshness is Freshness.STALE else None
    assert _result(freshness=freshness, reason=reason).healthy is healthy


def test_unusable_is_never_healthy():
    assert not _result(usable=False, freshness=None, reason=Reason.TIMED_OUT,
                       newest=None, ms=None).healthy
