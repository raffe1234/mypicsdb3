from __future__ import annotations

from mypicsdb3.preferences import (
    DEFAULT_ALBUM_VIEW_MODE,
    HOME_VIEW_KEYS,
    MAIN_MENU_NODE_KEYS,
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
