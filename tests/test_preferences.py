from __future__ import annotations

from mypicsdb3.preferences import (
    DEFAULT_ALBUM_VIEW_MODE,
    HOME_VIEW_KEYS,
    MAIN_MENU_NODE_KEYS,
    HomeLayoutItem,
    home_layout_slots,
    parse_home_layout_v2,
    remove_saved_search_from_home_layout,
    serialize_home_layout_v2,
    normalize_album_view_mode,
    normalize_home_layout,
    parse_hidden_main_menu_nodes,
    parse_persisted_home_layout,
    serialize_hidden_main_menu_nodes,
    serialize_home_layout,
    serialize_persisted_home_layout,
)


def test_legacy_home_rows_migrate_without_duplicates() -> None:
    order, enabled = normalize_home_layout(
        ["favorites", "recent_taken", "favorites", "none", "rated"]
    )

    assert order[:3] == ("favorites", "recent_taken", "rated")
    assert set(order) == set(HOME_VIEW_KEYS)
    assert enabled == frozenset({"favorites", "recent_taken", "rated"})
    assert serialize_home_layout(order, enabled)[:4] == (
        "favorites",
        "recent_taken",
        "rated",
        "none",
    )


def test_persisted_layout_keeps_disabled_views_in_position() -> None:
    order = (
        "recent_taken",
        "favorites",
        "recent_added",
        "random_memories",
        "recent_albums",
        "random_albums",
        "on_this_day",
        "on_this_day_random",
        "rated",
        "geotagged",
    )
    enabled = {"recent_taken", "recent_added", "on_this_day"}

    encoded = serialize_persisted_home_layout(order, enabled)
    decoded = parse_persisted_home_layout(encoded)

    assert encoded.startswith("recent_taken|!favorites|recent_added")
    assert decoded == (order, frozenset(enabled))


def test_album_view_mode_accepts_only_supported_estuary_ids() -> None:
    assert normalize_album_view_mode("54") == 54
    assert normalize_album_view_mode(500) == 500
    assert normalize_album_view_mode("999") == DEFAULT_ALBUM_VIEW_MODE
    assert normalize_album_view_mode("") == DEFAULT_ALBUM_VIEW_MODE


def test_hidden_main_menu_nodes_are_validated_and_canonicalized() -> None:
    hidden = parse_hidden_main_menu_nodes(
        "favorites|unknown|recent_taken|favorites"
    )

    assert hidden == frozenset({"favorites", "recent_taken"})
    assert serialize_hidden_main_menu_nodes(hidden) == "recent_taken|favorites"
    assert set(MAIN_MENU_NODE_KEYS) >= hidden


def test_home_layout_offers_both_on_this_day_variants() -> None:
    assert "on_this_day" in HOME_VIEW_KEYS
    assert "on_this_day_random" in HOME_VIEW_KEYS

    order, enabled = normalize_home_layout(
        ["on_this_day", "on_this_day_random"]
    )

    assert order[:2] == ("on_this_day", "on_this_day_random")
    assert enabled == frozenset({"on_this_day", "on_this_day_random"})
    assert serialize_home_layout(order, enabled)[:2] == (
        "on_this_day",
        "on_this_day_random",
    )


def test_smart_home_layout_roundtrip_materializes_dynamic_slots() -> None:
    items = (
        HomeLayoutItem(kind="builtin", key="recent_taken", enabled=True),
        HomeLayoutItem(kind="smart", saved_search_id=42, enabled=True, mode="square"),
        HomeLayoutItem(kind="builtin", key="recent_added", enabled=False),
    )

    encoded = serialize_home_layout_v2(items)
    decoded = parse_home_layout_v2(encoded, {42})
    slots = home_layout_slots(decoded or (), {42: "Spain favorites"})

    assert decoded is not None
    assert decoded[0].key == "recent_taken"
    assert decoded[1].saved_search_id == 42
    assert decoded[1].mode == "poster"
    assert '"mode"' not in encoded
    assert slots[0]["row"] == "recent_taken"
    assert slots[1] == {
        "row": "smart",
        "smart_id": 42,
        "smart_name": "Spain favorites",
        "smart_mode": "poster",
    }
    assert len(slots) == 9


def test_smart_home_layout_drops_deleted_collection_and_invalid_modes() -> None:
    items = (
        HomeLayoutItem(kind="smart", saved_search_id=7, enabled=True, mode="unknown"),
        HomeLayoutItem(kind="smart", saved_search_id=8, enabled=True, mode="landscape"),
    )
    encoded = serialize_home_layout_v2(items)

    decoded = parse_home_layout_v2(encoded, {8})
    removed = remove_saved_search_from_home_layout(decoded or (), 8)

    assert decoded is not None
    assert all(item.saved_search_id != 7 for item in decoded if item.kind == "smart")
    assert next(item for item in decoded if item.kind == "smart").mode == "poster"
    assert all(item.kind != "smart" for item in removed)


def test_smart_home_layout_drops_all_smart_rows_when_no_saved_searches_exist() -> None:
    encoded = serialize_home_layout_v2(
        (
            HomeLayoutItem(kind="smart", saved_search_id=12, enabled=True),
            HomeLayoutItem(kind="builtin", key="recent_taken", enabled=True),
        )
    )

    decoded = parse_home_layout_v2(encoded, set())

    assert decoded is not None
    assert all(item.kind != "smart" for item in decoded)
    assert next(item for item in decoded if item.key == "recent_taken").enabled is True
