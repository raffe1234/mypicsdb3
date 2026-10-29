"""Small indexed random-key windows spread across a large picture catalogue.

This keeps bounded indexed lookups, avoiding ORDER BY RANDOM()/RAND().  Small
requests use the existing single-pivot path.  The caller de-duplicates windows
and may fill a sparse catalogue using its existing full-size pivot query.
"""

from __future__ import annotations

import random
from typing import List, Optional, Tuple


def random_window_plan(limit: int, seed: Optional[float]) -> List[Tuple[float, int]]:
    """Return distributed (pivot, count) requests for a large random batch."""

    if limit < 48:
        return []  # Retain the historical single-pivot behaviour.
    count = min(4, max(2, limit // 40))
    if seed is not None:
        try:
            normalized_seed = float(seed) % 1.0
        except (TypeError, ValueError):
            normalized_seed = 0.0
        rng = random.Random(normalized_seed)
    else:
        rng = random.Random()
    buckets = list(range(count))
    rng.shuffle(buckets)
    base, extra = divmod(limit, count)
    return [
        ((bucket + rng.random()) / count, base + (i < extra))
        for i, bucket in enumerate(buckets)
    ]
