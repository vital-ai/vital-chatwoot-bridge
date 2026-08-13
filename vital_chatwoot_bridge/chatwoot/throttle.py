"""
Shared throttling and retry behaviour for the Chatwoot HTTP clients.

Both ``ChatwootClientAPI`` (public/client API, webhook path) and
``ChatwootAPIClient`` (management API) talk to the same Chatwoot instance and
must not overwhelm it.  This module holds the behaviour they share so the two
cannot drift apart again — historically only the first had any protection, so
every management route, including all contact lookups, ran unthrottled with no
429 handling at all (see ``issues/002``).

**Concurrency budgets are deliberately separate, not shared.**  A single global
semaphore is the more principled design — Chatwoot is one shared resource — but
the webhook budget is tuned small (3) for sustained blast traffic, and applying
that to interactive management routes would serialize them: one
``GET /communications`` can issue a few hundred upstream calls, which at a depth
of 3 takes tens of seconds.  Two bounded budgets are strictly better than one
bounded and one unbounded; unifying them means re-tuning both together, which is
a separate exercise.

Both budgets are **per process**.  Under N ECS tasks the fleet-wide ceiling is
``N x limit``; only a MemoryDB-backed limiter would be global.
"""

import asyncio
import logging
import random
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

# Ceiling on retry backoff. A server-supplied Retry-After is honoured up to this
# point; beyond it the request fails fast rather than holding a worker and a
# concurrency slot hostage.
MAX_RETRY_DELAY = 30.0

# Statuses worth retrying: rate limited, or the server explicitly unavailable.
RETRY_STATUSES = (429, 503)


def apply_jitter(delay: float) -> float:
    """Equal jitter: half the delay fixed, half random.

    Without this, every caller rejected in the same instant retries in the same
    instant, reproducing the burst that caused the rejection.
    """
    delay = min(delay, MAX_RETRY_DELAY)
    return delay / 2 + random.uniform(0, delay / 2)


def backoff_delay(response: httpx.Response, attempt: int, base_delay: float) -> float:
    """Exponential backoff, preferring the server's Retry-After when present."""
    retry_after = response.headers.get("Retry-After")
    if retry_after:
        try:
            return float(retry_after)
        except ValueError:
            pass
    return base_delay * (2 ** (attempt - 1))


async def request_with_retry(
    client: httpx.AsyncClient,
    method: str,
    url: str,
    *,
    semaphore: asyncio.Semaphore,
    max_attempts: int,
    base_delay: float,
    label: str = "Chatwoot API",
    **kwargs,
) -> httpx.Response:
    """Execute an HTTP request under a concurrency bound, with retry.

    Retries 429/503 with jittered exponential backoff; other 5xx get a single
    retry. Returns the last response for the caller to interpret — this never
    raises on status, matching the existing behaviour of both clients.

    The concurrency slot is released while sleeping between attempts, so a
    backing-off request does not block others.
    """
    last_response: Optional[httpx.Response] = None

    for attempt in range(1, max_attempts + 1):
        async with semaphore:
            last_response = await client.request(method, url, **kwargs)

        status = last_response.status_code

        # Success or a client error we should not retry.
        if status < 500 and status not in RETRY_STATUSES:
            return last_response

        if status in RETRY_STATUSES:
            delay = backoff_delay(last_response, attempt, base_delay)
        else:
            # Other 5xx — a single retry, then give up.
            delay = base_delay
            if attempt >= 2:
                break

        if attempt < max_attempts:
            delay = apply_jitter(delay)
            logger.warning(
                f"🚦 {label} {status} on {method} {url} — "
                f"retry {attempt}/{max_attempts} after {delay:.1f}s"
            )
            await asyncio.sleep(delay)

    # All retries exhausted — hand back the last response.
    return last_response
