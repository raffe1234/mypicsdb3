from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Dict, FrozenSet, Iterable, List, Mapping, Optional, Sequence, Tuple


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


@dataclass(frozen=True)
class MainMenuNode:
    key: str
    string_id: int
    fallback: str
    route: str


HOME_VIEWS: Tuple[HomeView, ...] = (
    HomeView("recent_taken", 30001, "Recently taken"),
    HomeView("recent_added", 30002, "Recently added"),
    HomeView("random_memories", 30003, "Random memories"),
    HomeView("recent_albums", 30004, "Recent albums"),
    HomeView("random_albums", 30005, "Random albums"),
    HomeView("on_this_day", 30006, "On this day"),
    HomeView("on_this_day_random", 32606, "On this day - random"),
    HomeView("favorites", 30010, "Favorites"),
    HomeView("rated", 30011, "Rated pictures"),
    HomeView("geotagged", 30012, "Geotagged pictures"),
)
HOME_VIEW_KEYS: Tuple[str, ...] = tuple(view.key for view in HOME_VIEWS)
HOME_VIEW_BY_KEY = {view.key: view for view in HOME_VIEWS}
HOME_ROW_COUNT = 9
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


SMART_HOME_LAYOUT_VERSION = 1
# Legacy 0.4.0-0.4.10 layouts may contain poster/square/landscape. From
# 0.4.11 all smart Home rows use the standard poster widget while the opened
# collection follows Default album view. Keep the field only for downgrade
# compatibility with existing home_layout_v2 data.
SMART_HOME_MODES: Tuple[str, ...] = ("poster", "square", "landscape")
DEFAULT_SMART_HOME_MODE = "poster"


@dataclass(frozen=True)
class HomeLayoutItem:
    kind: str
    key: str = ""
    saved_search_id: int = 0
    enabled: bool = False
    mode: str = DEFAULT_SMART_HOME_MODE

    @property
    def token(self) -> str:
        if self.kind == "smart":
            return "smart:%d" % self.saved_search_id
        return self.key


def default_home_layout_items() -> Tuple[HomeLayoutItem, ...]:
    enabled = {key for key in DEFAULT_HOME_ROWS if key in HOME_VIEW_BY_KEY}
    return tuple(
        HomeLayoutItem(kind="builtin", key=key, enabled=key in enabled)
        for key in HOME_VIEW_KEYS
    )


def migrate_home_layout_items(
    order: Sequence[object], enabled: Iterable[object]
) -> Tuple[HomeLayoutItem, ...]:
    normalized_order, _ = normalize_home_layout(order)
    enabled_keys = {str(value) for value in enabled}
    return tuple(
        HomeLayoutItem(
            kind="builtin",
            key=key,
            enabled=key in enabled_keys,
        )
        for key in normalized_order
    )


def normalize_smart_home_mode(value: object) -> str:
    # Per-row display modes were removed in 0.4.11. Accept every legacy value
    # but normalize it to the one compatibility mode still understood by old
    # skins and downgraded plug-in versions.
    return DEFAULT_SMART_HOME_MODE


def parse_home_layout_v2(
    value: object,
    available_saved_search_ids: Optional[Iterable[int]] = None,
) -> Optional[Tuple[HomeLayoutItem, ...]]:
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        payload = json.loads(raw)
    except (TypeError, ValueError):
        return None
    if not isinstance(payload, Mapping) or payload.get("version") != SMART_HOME_LAYOUT_VERSION:
        return None
    raw_items = payload.get("items")
    if not isinstance(raw_items, list):
        return None

    available = (
        None
        if available_saved_search_ids is None
        else {int(value) for value in available_saved_search_ids}
    )
    items: List[HomeLayoutItem] = []
    seen_builtin = set()
    seen_smart = set()
    enabled_count = 0
    for raw_item in raw_items:
        if not isinstance(raw_item, Mapping):
            continue
        kind = str(raw_item.get("type") or "")
        enabled = bool(raw_item.get("enabled")) and enabled_count < HOME_ROW_COUNT
        if kind == "builtin":
            key = str(raw_item.get("key") or "")
            if key not in HOME_VIEW_BY_KEY or key in seen_builtin:
                continue
            seen_builtin.add(key)
            item = HomeLayoutItem(kind="builtin", key=key, enabled=enabled)
        elif kind == "smart":
            try:
                saved_id = int(raw_item.get("id") or 0)
            except (TypeError, ValueError):
                continue
            if saved_id <= 0 or saved_id in seen_smart:
                continue
            if available is not None and saved_id not in available:
                continue
            seen_smart.add(saved_id)
            item = HomeLayoutItem(
                kind="smart",
                saved_search_id=saved_id,
                enabled=enabled,
                mode=normalize_smart_home_mode(raw_item.get("mode")),
            )
        else:
            continue
        if item.enabled:
            enabled_count += 1
        items.append(item)

    items.extend(
        HomeLayoutItem(kind="builtin", key=key, enabled=False)
        for key in HOME_VIEW_KEYS
        if key not in seen_builtin
    )
    return tuple(items) if items else None


def serialize_home_layout_v2(items: Sequence[HomeLayoutItem]) -> str:
    payload_items: List[Dict[str, Any]] = []
    seen_builtin = set()
    seen_smart = set()
    enabled_count = 0
    for item in items:
        enabled = bool(item.enabled) and enabled_count < HOME_ROW_COUNT
        if item.kind == "builtin":
            if item.key not in HOME_VIEW_BY_KEY or item.key in seen_builtin:
                continue
            seen_builtin.add(item.key)
            payload_items.append(
                {"type": "builtin", "key": item.key, "enabled": enabled}
            )
        elif item.kind == "smart":
            saved_id = int(item.saved_search_id or 0)
            if saved_id <= 0 or saved_id in seen_smart:
                continue
            seen_smart.add(saved_id)
            payload_items.append(
                {
                    "type": "smart",
                    "id": saved_id,
                    "enabled": enabled,
                }
            )
        else:
            continue
        if enabled:
            enabled_count += 1
    payload_items.extend(
        {"type": "builtin", "key": key, "enabled": False}
        for key in HOME_VIEW_KEYS
        if key not in seen_builtin
    )
    return json.dumps(
        {"version": SMART_HOME_LAYOUT_VERSION, "items": payload_items},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def remove_saved_search_from_home_layout(
    items: Sequence[HomeLayoutItem], saved_search_id: int
) -> Tuple[HomeLayoutItem, ...]:
    return tuple(
        item
        for item in items
        if not (item.kind == "smart" and item.saved_search_id == saved_search_id)
    )


def home_layout_slots(
    items: Sequence[HomeLayoutItem],
    saved_search_names: Mapping[int, str],
) -> Tuple[Dict[str, Any], ...]:
    slots: List[Dict[str, Any]] = []
    for item in items:
        if not item.enabled:
            continue
        if item.kind == "builtin" and item.key in HOME_VIEW_BY_KEY:
            slots.append(
                {
                    "row": item.key,
                    "smart_id": 0,
                    "smart_name": "",
                    "smart_mode": DEFAULT_SMART_HOME_MODE,
                }
            )
        elif item.kind == "smart" and item.saved_search_id in saved_search_names:
            slots.append(
                {
                    "row": "smart",
                    "smart_id": item.saved_search_id,
                    "smart_name": str(saved_search_names[item.saved_search_id]),
                    "smart_mode": normalize_smart_home_mode(item.mode),
                }
            )
        if len(slots) >= HOME_ROW_COUNT:
            break
    slots.extend(
        {
            "row": "none",
            "smart_id": 0,
            "smart_name": "",
            "smart_mode": DEFAULT_SMART_HOME_MODE,
        }
        for _ in range(HOME_ROW_COUNT - len(slots))
    )
    return tuple(slots)

MAIN_MENU_NODES: Tuple[MainMenuNode, ...] = (
    MainMenuNode("recent_taken", 30001, "Recently taken", "recent-taken"),
    MainMenuNode("recent_added", 30002, "Recently added", "recent-added"),
    MainMenuNode("random_memories", 30003, "Random memories", "random"),
    MainMenuNode("recent_albums", 30004, "Recent albums", "recent-folders"),
    MainMenuNode("random_albums", 30005, "Random albums", "random-folders"),
    MainMenuNode("on_this_day", 30006, "On this day", "on-this-day"),
    MainMenuNode("on_this_day_random", 32606, "On this day - random", "on-this-day-random"),
    MainMenuNode("videos", 32600, "Videos", "videos"),
    MainMenuNode("years", 30007, "Years", "years"),
    MainMenuNode("cameras", 30008, "Cameras", "cameras"),
    MainMenuNode("keywords", 30009, "Keywords", "keywords"),
    MainMenuNode("favorites", 30010, "Favorites", "favorites"),
    MainMenuNode("rated", 30011, "Rated pictures", "rated"),
    MainMenuNode("geotagged", 30012, "Geotagged pictures", "geotagged"),
)
MAIN_MENU_NODE_KEYS: Tuple[str, ...] = tuple(node.key for node in MAIN_MENU_NODES)

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
    rows.extend("none" for _ in range(HOME_ROW_COUNT - len(rows)))
    return tuple(rows[:HOME_ROW_COUNT])


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
    enabled = set(
        [key for key in order if key in enabled][:HOME_ROW_COUNT]
    )
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
    enabled_keys = set(
        [key for key in normalized_order if key in enabled_keys][:HOME_ROW_COUNT]
    )
    return "|".join(
        key if key in enabled_keys else "!" + key
        for key in normalized_order
    )


def parse_hidden_main_menu_nodes(value: object) -> FrozenSet[str]:
    """Read the canonical pipe-separated list of hidden add-on menu nodes."""
    hidden = {
        token.strip()
        for token in str(value or "").split("|")
        if token.strip() in MAIN_MENU_NODE_KEYS
    }
    return frozenset(hidden)


def serialize_hidden_main_menu_nodes(hidden: Iterable[object]) -> str:
    """Store hidden add-on menu nodes in stable display order."""
    hidden_keys = {
        str(value)
        for value in hidden
        if str(value) in MAIN_MENU_NODE_KEYS
    }
    return "|".join(key for key in MAIN_MENU_NODE_KEYS if key in hidden_keys)


def normalize_album_view_mode(value: object) -> int:
    try:
        mode_id = int(str(value).strip())
    except (TypeError, ValueError):
        return DEFAULT_ALBUM_VIEW_MODE
    if mode_id not in ALBUM_VIEW_MODE_BY_ID:
        return DEFAULT_ALBUM_VIEW_MODE
    return mode_id
