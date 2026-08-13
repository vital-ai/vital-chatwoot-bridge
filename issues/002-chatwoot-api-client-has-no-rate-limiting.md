# 002 — `ChatwootAPIClient` has no rate limiting, concurrency bound, or 429 handling

**Status:** RESOLVED 2026-08-13 (undeployed)
**Severity:** medium (active — every management route is exposed)
**Component:** `vital_chatwoot_bridge/chatwoot/api_client.py`
**Found:** 2026-08-13, during review of the Phase 5 `/communications` paging work
**Related:** `planning/performance/PLAN.md` (Phase 4 hardening, Phase 5 cost bounds)

---

## Summary

The codebase has two Chatwoot clients with very different protections, and the unprotected one
serves the larger surface:

| | `ChatwootClientAPI` (`client_api.py`) | `ChatwootAPIClient` (`api_client.py`) |
|---|---|---|
| concurrency semaphore | ✅ `rl_max_chatwoot_concurrency` (3) | ❌ none |
| token bucket / rate limit | ✅ via the webhook queue | ❌ none |
| httpx `limits=` | — | ❌ none (httpx default: 100 max connections) |
| 429 handling | ✅ retry with equal jitter, capped at 30 s | ❌ none — surfaces as `ChatwootAPIError` |
| transport retries | — | `AsyncHTTPTransport(retries=3)` (connection errors only) |

All of the Phase 4 hardening — jitter, backoff cap, the global semaphore — lives in
`ChatwootClientAPI` and does **not** apply to `ChatwootAPIClient`.

`ChatwootAPIClient` is the client behind `get_chatwoot_client()`, used at **29 call sites** across
`chatwoot_management_routes.py`, `inbox_cache.py` and `main.py` — i.e. essentially the whole
management API, including the contact-lookup paths reworked in Phases 1–3.

## Why it matters

1. **Unbounded burst per request.** `GET /communications` fans out across up to
   `MAX_CONVERSATIONS` conversations, each paging up to `MAX_MESSAGE_PAGES` times. Phase 5 added
   `MAX_CONCURRENT_CONVERSATION_FETCHES = 5` to bound *that one endpoint*, but the bound lives in
   the route, not the client. Any other fan-out added later gets no protection by default.
2. **No 429 backoff.** Chatwoot rate-limits the bridge in practice. Measured over the
   2026-07-20 15:00 UTC peak hour:

   | signal | count |
   |---|---|
   | log lines containing both `contacts/search` and `429` | 226 |
   | all log lines containing `429` | 294 |
   | `ChatwootClientAPI` retry warnings (`Chatwoot API 429 … retry n/m`) | 81 |

   Through `ChatwootClientAPI` a 429 retries with equal jitter and a capped delay, and *says so*
   in the logs. Through `ChatwootAPIClient` it raises `ChatwootAPIError` with no backoff, no
   `Retry-After` respect, and **no log line of its own** — the gap between 294 total 429s and 81
   retry warnings is not proof of attribution (the retry log only fires when attempts remain), but
   it does show most 429s leave no diagnostic trace. That observability gap is part of the
   problem: rate limiting on this client is currently invisible except as raw httpx status lines.

3. **Errors on this client were silently reported as complete results.** `/communications`
   swallowed `ChatwootAPIError` per conversation and returned `([], False)` — no messages, not
   truncated — so a rate-limited fetch was indistinguishable from a conversation with nothing in
   the window. Fixed alongside this issue (the handler now returns whatever pages succeeded with
   `truncated=True`), but it illustrates the compounding risk: an unthrottled client whose errors
   are caught per-item turns throttling into silently missing history rather than a visible
   failure. Any other caller catching `ChatwootAPIError` around this client deserves the same
   audit.
4. **Retries amplify the wrong failure.** `AsyncHTTPTransport(retries=3)` retries connection-level
   failures, which is exactly when Chatwoot is already struggling, and it does so with no jitter.
5. **Multi-task scaling.** Per the standing assumption that the bridge runs as N tasks, an
   in-process bound would be `N x limit` fleet-wide; only a MemoryDB-backed limiter is global.
   Any fix should be explicit about which of the two it is providing.

## Proposed fix

Bring `ChatwootAPIClient` up to parity with `ChatwootClientAPI`, ideally by extracting the shared
behaviour rather than duplicating it:

1. Route all requests through a shared `_request()` that acquires the same module-level semaphore
   (`rl_max_chatwoot_concurrency`), so both clients share one concurrency budget against Chatwoot
   rather than two independent ones.
2. Handle `429`/`503` with the existing equal-jitter backoff and `_MAX_RETRY_DELAY` cap, honouring
   `Retry-After`.
3. Set explicit `limits=httpx.Limits(...)` on the client instead of relying on httpx's default of
   100 max connections.
4. Once a shared `_request()` exists, `MAX_CONCURRENT_CONVERSATION_FETCHES` in
   `chatwoot_management_routes.py` becomes redundant and should be removed rather than left as a
   second, differently-sized bound.

## Resolution

Implemented 2026-08-13. `vital_chatwoot_bridge/chatwoot/throttle.py` now holds the shared
behaviour and **both** clients route through `request_with_retry()`:

- `ChatwootAPIClient._request()` added; all **32** direct `self.client.<verb>()` call sites across
  its 37 methods rewritten to use it.
- `ChatwootClientAPI._request()` reduced to a delegation, so the two cannot drift apart again.
  Its retry semantics are preserved exactly (429/503 with jittered exponential backoff honouring
  `Retry-After`, single retry for other 5xx, last response returned rather than raised).
- Pool bounds set on the transport (see below).
- `MAX_CONCURRENT_CONVERSATION_FETCHES` removed from `chatwoot_management_routes.py` — the client
  bound supersedes it, and two differently-sized limits would obscure which one binds.

**Deviation from proposed fix #1 — budgets are separate, not shared.** A single global semaphore
is more principled, but `max_chatwoot_concurrency = 3` is tuned for sustained webhook blasts;
applying it to interactive management routes would serialize them, and one `/communications` call
can issue several hundred upstream requests. Added `rl_max_management_concurrency` (default 8)
instead. Two bounded budgets beat one bounded and one unbounded; unifying them means re-tuning
both together, which is its own exercise. Rationale recorded in `throttle.py`.

**Bug found during implementation:** the first attempt set `limits=` on `httpx.AsyncClient`, which
httpx **silently ignores when a custom `transport=` is supplied** — verified live, the pool was
still at the default `max_connections=100`. Limits belong on the transport. Now measured as
`max_connections=16, max_keepalive=8`.

**Verification:**

- 12 new tests in `tests/test_throttle.py` covering retry policy (429/503 retried, 4xx not,
  generic 5xx retried once, exhausted retries return the last response), backoff (`Retry-After`
  honoured, unparseable header falls back to exponential, jitter bounded by `MAX_RETRY_DELAY` and
  actually varying), and that the semaphore genuinely bounds concurrency under a 20-way fan-out.
- 83 tests pass overall; the production lookup suite still 8/8.
- Live smoke against production: 20 concurrent management calls all succeeded, semaphore returned
  to its configured value, pool bounds confirmed.

Still open: this is per-process. Under N tasks the ceiling is `N x limit`; a global limiter would
need MemoryDB backing.

## Note on scope

This is a refactor touching every management route, so it wants its own change and its own
verification pass — not a rider on a feature branch. The Phase 5 endpoint-level semaphore is a
deliberate stopgap for the one fan-out that was measured to be dangerous; it is not a fix for
this issue.

## Verification

- `api_client.py:43-50` — `httpx.AsyncClient(transport=AsyncHTTPTransport(retries=3),
  timeout=30.0, ...)`, no `limits=`.
- `grep -c "Semaphore\|429\|Retry-After" api_client.py` → 0.
- `grep -rn "get_chatwoot_client()" vital_chatwoot_bridge/ | wc -l` → 29.
- 429 volume measured via CloudWatch Logs Insights over the 2026-07-20 15:00 UTC peak hour.
