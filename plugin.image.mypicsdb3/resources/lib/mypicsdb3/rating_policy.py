from __future__ import annotations

from typing import Any, Sequence, Tuple


RATING_POLICY_ALL = "all"
RATING_POLICY_RATED_AND_UNRATED = "rated_and_unrated"
RATING_POLICY_VALUES = frozenset({
    RATING_POLICY_ALL,
    RATING_POLICY_RATED_AND_UNRATED,
    "1",
    "2",
    "3",
    "4",
    "5",
})


def normalize_rating_policy(value: Any) -> str:
    text = str(value or "").strip().lower()
    aliases = {
        "": RATING_POLICY_ALL,
        "none": RATING_POLICY_ALL,
        "off": RATING_POLICY_ALL,
        "0": RATING_POLICY_ALL,
        "rated-unrated": RATING_POLICY_RATED_AND_UNRATED,
        "rated_unrated": RATING_POLICY_RATED_AND_UNRATED,
    }
    text = aliases.get(text, text)
    return text if text in RATING_POLICY_VALUES else RATING_POLICY_ALL


def rating_policy_label(policy: Any) -> str:
    normalized = normalize_rating_policy(policy)
    if normalized == RATING_POLICY_ALL:
        return "All pictures"
    if normalized == RATING_POLICY_RATED_AND_UNRATED:
        return "Rated and unrated"
    return "%s+" % normalized


def rating_sql_predicate(policy: Any, column: str = "p.rating") -> Tuple[str, Sequence[Any]]:
    """Return a trusted SQL predicate and bound parameters for a display policy.

    ``NULL`` means that no embedded rating was found. A stored value of ``0``
    is an explicit zero rating. The ``rated_and_unrated`` policy includes NULL
    and positive ratings while excluding explicit zero ratings.
    """
    normalized = normalize_rating_policy(policy)
    if normalized == RATING_POLICY_ALL:
        return "", ()
    if normalized == RATING_POLICY_RATED_AND_UNRATED:
        return "(%s IS NULL OR %s>=1)" % (column, column), ()
    return "%s>=?" % column, (int(normalized),)
