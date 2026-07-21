from __future__ import annotations

from dataclasses import dataclass
from typing import FrozenSet, Iterable, Optional, Sequence, Tuple


@dataclass(frozen=True)
class HomeView:
    key: str
    string_id: int
    fallback: str


@dataclass(frozen=True)
class AlbumViewMode:
    mode_id: int
    string_id: int
    fallback: str


HOME_VIEWS: Tuple[HomeView, ...] = (
    HomeView("recent_taken", 30001, "Recently taken"),
    HomeView("recent_added", 30002, "Recently added"),
    HomeView("random_memories", 30003, "Random memories"),
    HomeView("recent_albums", 30004, "Recent albums"),
    HomeView("random_albums", 30005, "Random albums"),
    HomeView("on_this_day", 30006, "On this day"),
    HomeView("favorites", 30010, "Favorites"),
    HomeView("rated", 30011, "Rated pictures"),
    HomeView("geotagged", 30012, "Geotagged pictures"),
)
HOME_VIEW_KEYS: Tuple[str, ...] = tuple(view.key for view in HOME_VIEWS)
HOME_VIEW_BY_KEY = {view.key: view for view in HOME_VIEWS}
DEFAULT_HOME_ROWS: Tuple[str, ...] = (
    "recent_taken",
    "recent_added",
    "random_memories",
    "recent_albums",
    "random_albums",
    "on_this_day",
    "none",
    "none",
    "none",
)

ALBUM_VIEW_MODES: Tuple[AlbumViewMode, ...] = (
    AlbumViewMode(0, 32201, "Use skin default"),
    AlbumViewMode(50, 32202, "List"),
    AlbumViewMode(52, 32203, "Icon wall"),
    AlbumViewMode(53, 32204, "Shift"),
    AlbumViewMode(54, 32205, "Info wall"),
    AlbumViewMode(55, 32206, "Wide list"),
    AlbumViewMode(500, 32207, "Wall"),
)
ALBUM_VIEW_MODE_BY_ID = {mode.mode_id: mode for mode in ALBUM_VIEW_MODES}
DEFAULT_ALBUM_VIEW_MODE = 55


def normalize_home_layout(rows: Sequence[object]) -> Tuple[Tuple[str, ...], FrozenSet[str]]:
    """Return every home view once, with enabled views first in saved order."""
    ordered_enabled = []
    seen = set()
    for raw_value in rows:
        key = str(raw_value or "").strip()
        if key in HOME_VIEW_BY_KEY and key not in seen:
            ordered_enabled.append(key)
            seen.add(key)

    ordered = ordered_enabled + [key for key in HOME_VIEW_KEYS if key not in seen]
    return tuple(ordered), frozenset(ordered_enabled)


def serialize_home_layout(order: Iterable[object], enabled: Iterable[object]) -> Tuple[str, ...]:
    """Serialize the ordered enabled views to the legacy nine home-row settings."""
    enabled_keys = {str(value) for value in enabled if str(value) in HOME_VIEW_BY_KEY}
    normalized_order = []
    seen = set()
    for raw_value in order:
        key = str(raw_value)
        if key in HOME_VIEW_BY_KEY and key not in seen:
            normalized_order.append(key)
            seen.add(key)
    normalized_order.extend(key for key in HOME_VIEW_KEYS if key not in seen)

    rows = [key for key in normalized_order if key in enabled_keys]
    rows.extend("none" for _ in range(len(HOME_VIEW_KEYS) - len(rows)))
    return tuple(rows[: len(HOME_VIEW_KEYS)])


def parse_persisted_home_layout(value: object) -> Optional[Tuple[Tuple[str, ...], FrozenSet[str]]]:
    """Read the full order and enabled state used by the home-screen editor."""
    raw_value = str(value or "").strip()
    if not raw_value:
        return None

    order = []
    enabled = set()
    seen = set()
    for token in raw_value.split("|"):
        token = token.strip()
        is_enabled = not token.startswith("!")
        key = token.lstrip("!")
        if key not in HOME_VIEW_BY_KEY or key in seen:
            continue
        order.append(key)
        seen.add(key)
        if is_enabled:
            enabled.add(key)

    if not order:
        return None
    order.extend(key for key in HOME_VIEW_KEYS if key not in seen)
    return tuple(order), frozenset(enabled)


def serialize_persisted_home_layout(order: Iterable[object], enabled: Iterable[object]) -> str:
    """Store every home view so disabled rows retain their chosen position."""
    enabled_keys = {str(value) for value in enabled if str(value) in HOME_VIEW_BY_KEY}
    normalized_order = []
    seen = set()
    for raw_value in order:
        key = str(raw_value)
        if key in HOME_VIEW_BY_KEY and key not in seen:
            normalized_order.append(key)
            seen.add(key)
    normalized_order.extend(key for key in HOME_VIEW_KEYS if key not in seen)
    return "|".join(
        key if key in enabled_keys else "!" + key
        for key in normalized_order
    )


def normalize_album_view_mode(value: object) -> int:
    try:
        mode_id = int(str(value).strip())
    except (TypeError, ValueError):
        return DEFAULT_ALBUM_VIEW_MODE
    if mode_id not in ALBUM_VIEW_MODE_BY_ID:
        return DEFAULT_ALBUM_VIEW_MODE
    return mode_id
