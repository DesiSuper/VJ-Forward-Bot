"""Small, dependency-free helpers for per-message forwarding delays."""

from __future__ import annotations

import random
from typing import Any

MAX_RANDOM_GAP_SECONDS = 3600


def normalize_random_gap(value: Any) -> tuple[int, int]:
    """Return a validated minimum/maximum delay; invalid legacy data disables it."""
    if not isinstance(value, dict):
        return 0, 0
    try:
        minimum = int(value.get("min", 0))
        maximum = int(value.get("max", 0))
    except (TypeError, ValueError):
        return 0, 0
    if minimum < 0 or maximum < minimum or maximum > MAX_RANDOM_GAP_SECONDS:
        return 0, 0
    return minimum, maximum


def choose_random_gap(gap: tuple[int, int], default_delay: int = 0) -> int:
    """Pick one delay from the configured range or use the legacy default."""
    minimum, maximum = gap
    if maximum == 0:
        return max(0, int(default_delay))
    return random.randint(minimum, maximum)
