"""
Generic hierarchical environment variable parser.

Scans os.environ for keys matching a given prefix, splits on ``__``
(double underscore) to produce path segments, and assembles a nested dict.

Example:
    CW_BRIDGE__api_inboxes__loopmessage__name=LoopMessage iMessages
    CW_BRIDGE__api_inboxes__loopmessage__supports_outbound=true

    parse_env_tree("CW_BRIDGE") returns:
    {
        "api_inboxes": {
            "loopmessage": {
                "name": "LoopMessage iMessages",
                "supports_outbound": "true",
            }
        }
    }

Values are returned as raw strings.  Use ``coerce_value()`` or the
Pydantic model layer for type conversion.
"""

import os
import logging
from typing import Any, Dict

logger = logging.getLogger(__name__)

_PREFIX = "CW_BRIDGE"
_SEP = "__"


def parse_env_tree(prefix: str = _PREFIX) -> Dict[str, Any]:
    """Scan environment for ``<prefix>__*`` keys and return a nested dict.

    Each key is split by ``__``.  The first segment must equal *prefix*
    and is stripped; remaining segments form the path into the dict.

    Returns:
        Nested dict assembled from all matching env vars.
    """
    full_prefix = f"{prefix}{_SEP}"
    tree: Dict[str, Any] = {}

    for key, value in os.environ.items():
        if not key.startswith(full_prefix):
            continue

        # Strip the prefix portion (e.g. "CW_BRIDGE__")
        remainder = key[len(full_prefix):]
        parts = remainder.split(_SEP)

        if not parts or parts == [""]:
            continue

        # Walk / create nested dicts for intermediate segments
        node = tree
        for segment in parts[:-1]:
            if segment not in node:
                node[segment] = {}
            elif not isinstance(node[segment], dict):
                # Conflict: a leaf value already exists at this path.
                # Overwrite with a dict (last env var wins).
                node[segment] = {}
            node = node[segment]

        node[parts[-1]] = value

    if tree:
        logger.info(f"📋 ENV_PARSER: Parsed {_count_leaves(tree)} env vars under {prefix}")
    return tree


def coerce_value(value: str) -> Any:
    """Best-effort coerce a string value to a Python primitive.

    Rules:
        - ``"true"`` / ``"false"`` → bool
        - All-digit strings → int
        - Everything else → str (unchanged)
    """
    lower = value.lower()
    if lower == "true":
        return True
    if lower == "false":
        return False
    if value.isdigit():
        return int(value)
    return value


def coerce_dict(d: Dict[str, Any]) -> Dict[str, Any]:
    """Recursively coerce leaf string values in a nested dict."""
    out: Dict[str, Any] = {}
    for k, v in d.items():
        if isinstance(v, dict):
            out[k] = coerce_dict(v)
        elif isinstance(v, str):
            out[k] = coerce_value(v)
        else:
            out[k] = v
    return out


def _count_leaves(d: Dict) -> int:
    """Count leaf (non-dict) values in a nested dict."""
    count = 0
    for v in d.values():
        if isinstance(v, dict):
            count += _count_leaves(v)
        else:
            count += 1
    return count
