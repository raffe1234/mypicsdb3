from __future__ import annotations

from pathlib import Path

from mypicsdb3.home_layout_editor import HomeLayoutState


def test_home_layout_state_toggles_and_moves_rows() -> None:
    state = HomeLayoutState(
        [
            "recent_taken",
            "recent_added",
            "random_memories",
            "recent_albums",
            "random_albums",
            "on_this_day",
            "on_this_day_random",
            "favorites",
            "rated",
            "geotagged",
        ],
        {"recent_taken", "recent_added"},
    )

    state.toggle(6)
    target = state.move(6, -1)

    order, enabled = state.snapshot()
    assert target == 5
    assert order[5] == "on_this_day_random"
    assert "on_this_day_random" in enabled


def test_home_layout_state_defaults_enable_first_six_rows() -> None:
    state = HomeLayoutState(["geotagged"], {"geotagged"})

    state.reset()

    order, enabled = state.snapshot()
    assert order[:6] == (
        "recent_taken",
        "recent_added",
        "random_memories",
        "recent_albums",
        "random_albums",
        "on_this_day",
    )
    assert enabled == frozenset(order[:6])


def test_home_layout_state_keeps_nine_enabled_views_when_one_early_view_is_off() -> None:
    order = [
        "recent_taken",
        "recent_added",
        "random_memories",
        "recent_albums",
        "random_albums",
        "on_this_day",
        "on_this_day_random",
        "favorites",
        "rated",
        "geotagged",
    ]
    state = HomeLayoutState(order, set(order[1:]))

    _, enabled = state.snapshot()

    assert len(enabled) == 9
    assert "recent_taken" not in enabled
    assert "geotagged" in enabled


def test_home_layout_state_limits_enabled_views_to_nine_rows() -> None:
    state = HomeLayoutState(
        [
            "recent_taken",
            "recent_added",
            "random_memories",
            "recent_albums",
            "random_albums",
            "on_this_day",
            "on_this_day_random",
            "favorites",
            "rated",
            "geotagged",
        ],
        {
            "recent_taken",
            "recent_added",
            "random_memories",
            "recent_albums",
            "random_albums",
            "on_this_day",
            "on_this_day_random",
            "favorites",
            "rated",
        },
    )

    state.toggle(9)

    _, enabled = state.snapshot()
    assert len(enabled) == 9
    assert "geotagged" not in enabled


def test_home_layout_editor_media_is_packaged() -> None:
    media = (
        Path(__file__).resolve().parents[1]
        / "plugin.image.mypicsdb3"
        / "resources"
        / "skins"
        / "Default"
        / "media"
    )
    expected = {
        "home-editor-background.png",
        "home-editor-panel.png",
        "home-editor-focus.png",
        "home-editor-toggle-on.png",
        "home-editor-toggle-on-focus.png",
        "home-editor-toggle-off.png",
        "home-editor-toggle-off-focus.png",
    }
    assert expected <= {path.name for path in media.glob("*.png")}


def test_home_layout_xml_contains_ten_view_choices() -> None:
    import xml.etree.ElementTree as ET

    xml_path = (
        Path(__file__).resolve().parents[1]
        / "plugin.image.mypicsdb3"
        / "resources"
        / "skins"
        / "Default"
        / "1080i"
        / "home_layout_editor.xml"
    )
    root = ET.parse(xml_path).getroot()
    controls = {
        int(node.attrib["id"]): node
        for node in root.findall("./controls/control")
        if "id" in node.attrib
    }

    assert all(1001 + index in controls for index in range(10))
    assert all(controls[1101 + index].attrib["type"] == "radiobutton" for index in range(10))
    assert all(controls[1201 + index].findtext("label") == "▲" for index in range(10))
    assert all(controls[1301 + index].findtext("label") == "▼" for index in range(10))
    assert {1401, 1402, 1403} <= controls.keys()


def test_smart_home_layout_state_adds_orders_and_changes_mode() -> None:
    from mypicsdb3.home_layout_editor import SmartHomeLayoutState
    from mypicsdb3.preferences import HomeLayoutItem

    state = SmartHomeLayoutState(
        [
            HomeLayoutItem(kind="builtin", key="recent_taken", enabled=True),
            HomeLayoutItem(kind="builtin", key="recent_added", enabled=True),
        ]
    )

    assert state.add_smart(42, "square") is True
    assert state.add_smart(42, "poster") is False
    target = state.move(2, -1)
    state.set_mode(target, "landscape")

    items = state.snapshot()
    assert target == 1
    assert items[1].kind == "smart"
    assert items[1].saved_search_id == 42
    assert items[1].mode == "landscape"
    assert items[1].enabled is True


def test_smart_home_layout_state_limits_visible_rows_to_nine() -> None:
    from mypicsdb3.home_layout_editor import SmartHomeLayoutState
    from mypicsdb3.preferences import HOME_VIEW_KEYS, HomeLayoutItem

    state = SmartHomeLayoutState(
        [
            HomeLayoutItem(kind="builtin", key=key, enabled=index < 9)
            for index, key in enumerate(HOME_VIEW_KEYS)
        ]
    )

    assert state.toggle(9) is False
    assert sum(1 for item in state.snapshot() if item.enabled) == 9


def test_smart_home_editor_adds_collection_with_selected_mode() -> None:
    from mypicsdb3.home_layout_editor import (
        SmartHomeEditorText,
        show_smart_home_layout_editor,
    )
    from mypicsdb3.preferences import HomeLayoutItem

    class FakeDialog:
        def __init__(self):
            self.answers = iter((1, 0, 2, 3))
            self.ok_calls = []

        def select(self, _heading, _options, preselect=-1):
            return next(self.answers)

        def ok(self, heading, message):
            self.ok_calls.append((heading, message))

    class FakeGui:
        def __init__(self):
            self.dialog = FakeDialog()

        def Dialog(self):
            return self.dialog

    text = SmartHomeEditorText(
        heading="Home rows",
        on="On",
        off="Off",
        move_up="Up",
        move_down="Down",
        save="Save",
        cancel="Cancel",
        defaults="Defaults",
        add_collection="Add",
        remove_collection="Remove",
        display_mode="Mode",
        poster="Poster",
        square="Square",
        landscape="Wide",
        maximum_rows="Maximum",
        no_collections="None",
    )
    gui = FakeGui()

    result = show_smart_home_layout_editor(
        (HomeLayoutItem(kind="builtin", key="recent_taken", enabled=True),),
        {"recent_taken": "Recently taken"},
        {42: "Spain favorites"},
        text,
        xbmcgui_module=gui,
    )

    assert result is not None
    assert len(result) == 2
    assert result[1].kind == "smart"
    assert result[1].saved_search_id == 42
    assert result[1].mode == "landscape"
    assert result[1].enabled is True
    assert gui.dialog.ok_calls == []
