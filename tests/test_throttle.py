"""
Tests for the shared Chatwoot request throttling / retry behaviour.

This logic previously existed only in ChatwootClientAPI and was untested; the
management client had none of it, so every management route ran unthrottled with
no 429 handling (issues/002). Both clients now share throttle.request_with_retry.
"""

import asyncio

import httpx
import pytest

from vital_chatwoot_bridge.chatwoot.throttle import (
    MAX_RETRY_DELAY,
    apply_jitter,
    backoff_delay,
    request_with_retry,
)


def _response(status: int, headers: dict = None) -> httpx.Response:
    return httpx.Response(
        status_code=status,
        headers=headers or {},
        request=httpx.Request("GET", "https://example.invalid/x"),
    )


class _ScriptedClient:
    """httpx-shaped stub returning a scripted sequence of statuses."""

    def __init__(self, statuses, headers=None):
        self._statuses = list(statuses)
        self._headers = headers or {}
        self.calls = 0

    async def request(self, method, url, **kwargs):
        self.calls += 1
        status = self._statuses.pop(0) if self._statuses else 200
        return _response(status, self._headers)


@pytest.fixture(autouse=True)
def _no_sleeping(monkeypatch):
    """Collapse backoff so tests assert behaviour, not wall-clock."""
    async def _instant(_):
        return None
    monkeypatch.setattr(asyncio, "sleep", _instant)


async def _run(client, attempts=3, base_delay=1.0):
    return await request_with_retry(
        client, "GET", "https://example.invalid/x",
        semaphore=asyncio.Semaphore(2),
        max_attempts=attempts,
        base_delay=base_delay,
    )


# ---------------------------------------------------------------------------
# Retry policy
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_success_does_not_retry():
    c = _ScriptedClient([200])
    assert (await _run(c)).status_code == 200
    assert c.calls == 1


@pytest.mark.asyncio
async def test_429_is_retried_then_succeeds():
    c = _ScriptedClient([429, 429, 200])
    assert (await _run(c)).status_code == 200
    assert c.calls == 3


@pytest.mark.asyncio
async def test_503_is_retried():
    c = _ScriptedClient([503, 200])
    assert (await _run(c)).status_code == 200
    assert c.calls == 2


@pytest.mark.asyncio
async def test_client_errors_are_not_retried():
    """404/422 are answers, not failures — retrying wastes an upstream call."""
    for status in (400, 404, 422):
        c = _ScriptedClient([status, 200])
        assert (await _run(c)).status_code == status
        assert c.calls == 1


@pytest.mark.asyncio
async def test_generic_5xx_gets_a_single_retry_only():
    c = _ScriptedClient([500, 500, 500])
    assert (await _run(c)).status_code == 500
    assert c.calls == 2, "generic 5xx should be tried twice, not max_attempts times"


@pytest.mark.asyncio
async def test_exhausted_retries_return_last_response():
    """Never raises on status — the caller interprets the result."""
    c = _ScriptedClient([429, 429, 429])
    assert (await _run(c)).status_code == 429
    assert c.calls == 3


# ---------------------------------------------------------------------------
# Backoff
# ---------------------------------------------------------------------------

def test_retry_after_header_is_honoured():
    assert backoff_delay(_response(429, {"Retry-After": "7"}), attempt=1, base_delay=1.0) == 7.0


def test_unparseable_retry_after_falls_back_to_exponential():
    r = _response(429, {"Retry-After": "in a bit"})
    assert backoff_delay(r, attempt=3, base_delay=1.0) == 4.0


def test_backoff_is_exponential_in_attempt():
    r = _response(429)
    delays = [backoff_delay(r, attempt=a, base_delay=1.0) for a in (1, 2, 3)]
    assert delays == [1.0, 2.0, 4.0]


def test_jitter_stays_within_half_to_full_and_respects_cap():
    for _ in range(200):
        d = apply_jitter(10.0)
        assert 5.0 <= d <= 10.0
    # A large Retry-After must not park a worker indefinitely.
    assert apply_jitter(3600.0) <= MAX_RETRY_DELAY


def test_jitter_actually_varies():
    """Identical delays across callers would reproduce the burst that caused the 429."""
    assert len({apply_jitter(10.0) for _ in range(50)}) > 1


# ---------------------------------------------------------------------------
# Concurrency bound
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_semaphore_bounds_concurrent_requests(monkeypatch):
    """The bound is the whole point: without it a fan-out bursts at Chatwoot."""
    monkeypatch.undo()  # restore real asyncio.sleep for this test
    live = 0
    peak = 0

    class _Tracking:
        async def request(self, method, url, **kwargs):
            nonlocal live, peak
            live += 1
            peak = max(peak, live)
            await asyncio.sleep(0.01)
            live -= 1
            return _response(200)

    sem = asyncio.Semaphore(3)
    client = _Tracking()
    await asyncio.gather(*[
        request_with_retry(client, "GET", "https://example.invalid/x",
                           semaphore=sem, max_attempts=1, base_delay=0.0)
        for _ in range(20)
    ])
    assert peak <= 3, f"semaphore breached: {peak} concurrent requests"
