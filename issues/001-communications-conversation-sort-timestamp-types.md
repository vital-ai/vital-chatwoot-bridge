# 001 — `/communications` conversation sort is fragile to timestamp type changes

**Status:** open
**Severity:** low (latent — not reachable with current Chatwoot serialization)
**Component:** `vital_chatwoot_bridge/api/chatwoot_management_routes.py`
**Found:** 2026-08-13, during review of the Phase 5 windowing fix (`planning/performance/PLAN.md`)

---

## Summary

The conversation sort in `get_communications` compares raw Chatwoot timestamp values with an
integer fallback:

```python
# chatwoot_management_routes.py:1350-1353
all_convs.sort(
    key=lambda c: c.get("last_activity_at") or c.get("created_at") or 0,
    reverse=True,
)
```

This raises `TypeError: '<' not supported between instances of 'str' and 'int'` if the sorted
values are ever a mix of strings and integers.

**Failure mode is a clean 500, not silent corruption.** The endpoint's outer handler ends in
`except Exception` (`chatwoot_management_routes.py:1568-1573`), which logs with `exc_info=True`
and re-raises as `HTTP 500 "Communications lookup failed: ..."`. So the failure is loud,
attributable in logs, and cannot be mistaken for an empty result — which is what keeps this at
low severity despite the whole-request blast radius.

## Why it does not fire today

Chatwoot 4.3.0 serializes conversation timestamps as **epoch integers**, verified against
production across both endpoints that return conversations — 37 conversations sampled, every
`last_activity_at` and `created_at` an `int`, none null or absent:

```
contact-conversations endpoint (the one get_communications uses): 12 sampled — int x12, int x12
account conversations endpoint:                                   25 sampled — int x25, int x25
e.g. conv 1151: last_activity_at=1786378531 (int), created_at=1763570452 (int)
```

Every value is an `int`, and the `or 0` fallback is also an `int`, so the comparison is
type-consistent. The fallback cannot introduce a mismatch on its own: it only fires when both
fields are falsy, and `0` is the same type as the values it sorts against. Mixed types therefore
require Chatwoot itself to emit a string, which 4.3.0 does not do.

## When it would fire

1. **A Chatwoot upgrade changes the serialization to ISO 8601 strings.** The `or 0` fallback then
   mixes `str` with `int` the moment any conversation is missing both fields. Note this is not
   hypothetical elsewhere in the same payload — *message* timestamps already come back as ISO
   strings (`"2026-08-12T02:54:06Z"`), so the two shapes coexist in this API today.
2. **A partially-populated payload** where some conversations carry string timestamps and others
   fall through to `0`.

The blast radius is the whole endpoint, not one conversation: a single bad value fails the sort
for the entire request.

## Proposed fix

Route the sort key through the existing `_to_datetime()` helper (added for the Phase 5 windowing
work), which already normalizes ISO strings, `Z` suffixes and epoch seconds to timezone-aware
datetimes:

```python
all_convs.sort(
    key=lambda c: _to_datetime(c.get("last_activity_at"))
                  or _to_datetime(c.get("created_at"))
                  or datetime.min.replace(tzinfo=timezone.utc),
    reverse=True,
)
```

This makes the key type-stable regardless of which shape Chatwoot sends, and sorts
missing-timestamp conversations last instead of ordering them by a bare `0`.

Note the same `or 0` pattern appears on the message sort inside `_fetch_messages`
(`key=lambda m: m.get("created_at") or 0`). Message timestamps are ISO strings today, so that key
is `str`-consistent and string sort happens to be chronologically correct for ISO 8601 — but it
carries the identical fragility in mirror image and should be fixed in the same pass.

## Related: deprecated `utcfromtimestamp`

`chatwoot_management_routes.py:1487` uses `datetime.utcfromtimestamp()`, which is deprecated as of
Python 3.12 (the runtime here) and scheduled for removal:

```
DeprecationWarning: datetime.datetime.utcfromtimestamp() is deprecated
```

Replace with `datetime.fromtimestamp(value, tz=timezone.utc)`, which is what `_to_datetime()`
already does — so folding this call into that helper resolves both items together.

## Verification

- Confirmed Chatwoot returns epoch ints for conversation timestamps (live API, account 4).
- Confirmed message timestamps are ISO strings in the same response.
- Confirmed the deprecation warning fires on Python 3.12.2.
- No mixed-type payloads observed in production, hence "latent" rather than "active".
