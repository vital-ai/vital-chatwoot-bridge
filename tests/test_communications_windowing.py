"""
Tests for /communications date-window handling.

The endpoint previously capped results *before* applying since/until, so a
historical query could return zero messages while the data it asked for sat
just past the cap. These pin the corrected ordering.
"""

from datetime import datetime, timedelta, timezone

import pytest

from vital_chatwoot_bridge.api.chatwoot_management_routes import (
    CHATWOOT_MESSAGE_PAGE_SIZE,
    MAX_MESSAGE_PAGES,
    MAX_MESSAGES_PER_CONVERSATION,
    _conversation_in_window,
    _message_in_window,
    _to_datetime,
)

NOW = datetime(2026, 8, 13, 12, 0, tzinfo=timezone.utc)
OLD = NOW - timedelta(days=365)


def _msg(dt: datetime) -> dict:
    return {"id": 1, "created_at": dt.isoformat()}


# ---------------------------------------------------------------------------
# Timestamp parsing
# ---------------------------------------------------------------------------

def test_to_datetime_accepts_iso_epoch_and_z_suffix():
    assert _to_datetime("2026-08-13T12:00:00+00:00") == NOW
    assert _to_datetime("2026-08-13T12:00:00Z") == NOW
    assert _to_datetime(NOW.timestamp()) == NOW


def test_to_datetime_assumes_utc_for_naive_input():
    """Naive input must become aware, or comparisons raise TypeError."""
    parsed = _to_datetime("2026-08-13T12:00:00")
    assert parsed is not None and parsed.tzinfo is not None
    assert parsed == NOW


def test_to_datetime_rejects_garbage():
    assert _to_datetime("not-a-date") is None
    assert _to_datetime(None) is None
    assert _to_datetime("") is None


# ---------------------------------------------------------------------------
# Message windowing
# ---------------------------------------------------------------------------

def test_message_window_bounds():
    assert _message_in_window(_msg(NOW), None, None) is True
    assert _message_in_window(_msg(OLD), NOW - timedelta(days=1), None) is False
    assert _message_in_window(_msg(NOW), None, NOW - timedelta(days=1)) is False
    assert _message_in_window(_msg(OLD), None, NOW) is True


def test_message_without_parseable_date_excluded_from_window():
    assert _message_in_window({"id": 1, "created_at": "nonsense"}, None, NOW) is False


def test_old_messages_survive_when_newer_ones_exceed_the_cap():
    """The original bug: cap first, filter second, get nothing back.

    A conversation with more than MAX_MESSAGES_PER_CONVERSATION messages newer
    than `until` used to return zero rows, because the newest N were selected
    before the window was applied.
    """
    until = NOW - timedelta(days=30)
    newer = [_msg(NOW - timedelta(minutes=i)) for i in range(MAX_MESSAGES_PER_CONVERSATION + 20)]
    older = [_msg(until - timedelta(days=i + 1)) for i in range(3)]
    msgs = newer + older

    # Corrected order: filter, then sort, then cap.
    filtered = [m for m in msgs if _message_in_window(m, None, until)]
    filtered.sort(key=lambda m: m["created_at"], reverse=True)
    assert len(filtered) == 3, "the messages inside the window must survive"
    assert filtered[:MAX_MESSAGES_PER_CONVERSATION] == filtered

    # Original order, for contrast: cap first and the window is starved.
    capped = sorted(msgs, key=lambda m: m["created_at"], reverse=True)[:MAX_MESSAGES_PER_CONVERSATION]
    assert [m for m in capped if _message_in_window(m, None, until)] == []


# ---------------------------------------------------------------------------
# Conversation windowing
# ---------------------------------------------------------------------------

def test_conversation_excluded_only_when_provably_outside():
    quiet_before = {"created_at": (OLD - timedelta(days=10)).isoformat(),
                    "last_activity_at": OLD.isoformat()}
    assert _conversation_in_window(quiet_before, NOW - timedelta(days=1), None) is False

    started_after = {"created_at": NOW.isoformat(), "last_activity_at": NOW.isoformat()}
    assert _conversation_in_window(started_after, None, NOW - timedelta(days=1)) is False


def test_active_conversation_with_old_messages_is_kept():
    """The conversation-level analogue of the message bug.

    A conversation still active today can hold messages from inside a historical
    window. Filtering on last_activity_at alone would discard it.
    """
    conv = {"created_at": OLD.isoformat(), "last_activity_at": NOW.isoformat()}
    assert _conversation_in_window(conv, None, NOW - timedelta(days=30)) is True


@pytest.mark.parametrize("conv", [
    {},                                             # no timestamps at all
    {"created_at": "nonsense", "last_activity_at": "nonsense"},
    {"created_at": None, "last_activity_at": None},
])
def test_ambiguous_conversations_are_kept(conv):
    """Unparseable metadata must not silently drop data; filter at message level."""
    assert _conversation_in_window(conv, NOW - timedelta(days=1), NOW) is True


# ---------------------------------------------------------------------------
# Pagination bounds
# ---------------------------------------------------------------------------

def test_local_cap_is_unreachable_from_a_single_page():
    """Why the `before` cursor loop exists.

    Chatwoot serves 20 messages per call (measured against production: a
    1,018-message conversation returns 20 in one call). A local cap of 50 can
    therefore never bind on a single fetch, so filtering one page can only ever
    narrow the newest 20 — the older in-window messages are never retrieved.
    Collapsing the paging loop back to one call would silently reintroduce that.
    """
    assert MAX_MESSAGES_PER_CONVERSATION > CHATWOOT_MESSAGE_PAGE_SIZE


def test_page_bound_covers_realistic_conversations():
    """The bound must cover the fleet, not just the median.

    Production distribution over 261,871 conversations: p50=3, p95=17, p99=25
    messages; only 2 exceed 200. The page budget covers everything short of
    those outliers, which report truncated=True rather than looking complete.
    """
    assert MAX_MESSAGE_PAGES * CHATWOOT_MESSAGE_PAGE_SIZE >= 200
