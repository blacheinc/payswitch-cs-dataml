"""
Shared utilities for the PaySwitch Credit Scoring Engine.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any


logger = logging.getLogger("payswitch-cs")


def utc_now_iso() -> str:
    """Return current UTC timestamp in ISO 8601 format."""
    return datetime.now(timezone.utc).isoformat()


def safe_json_loads(raw: str | bytes) -> dict[str, Any]:
    """Parse JSON with a clear error on failure."""
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError) as exc:
        raise ValueError(f"Invalid JSON payload: {exc}") from exc


def clamp(value: float, min_val: float, max_val: float) -> float:
    """Clamp a value to [min_val, max_val]."""
    return max(min_val, min(max_val, value))
