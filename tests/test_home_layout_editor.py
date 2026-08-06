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
    assert {1401, 1402, 1403, 1404, 1405} <= controls.keys()
    assert controls[104].attrib["type"] == "label"
    assert controls[1404].attrib["type"] == "button"
    assert controls[1405].attrib["type"] == "button"


def test_smart_home_layout_state_adds_orders_and_normalizes_legacy_mode() -> None:
    from mypicsdb3.home_layout_editor import SmartHomeLayoutState
    from mypicsdb3.preferences import HomeLayoutItem

    state = SmartHomeLayoutState(
        [
            HomeLayoutItem(kind="builtin", key="recent_taken", enabled=True),
            HomeLayoutItem(kind="builtin", key="recent_added", enabled=True),
        ]
    )

    assert state.add_smart(42) is True
    assert state.add_smart(42) is False
    target = state.move(2, -1)

    items = state.snapshot()
    assert target == 1
    assert items[1].kind == "smart"
    assert items[1].saved_search_id == 42
    assert items[1].mode == "poster"
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


def test_smart_home_editor_adds_collection_without_display_mode_prompt() -> None:
    from mypicsdb3.home_layout_editor import (
        SmartHomeEditorText,
        show_smart_home_layout_editor,
    )
    from mypicsdb3.preferences import HomeLayoutItem

    class FakeDialog:
        def __init__(self):
            self.answers = iter((1, 0, 3))
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
        row_heading="Row",
        visible_heading="Enabled",
        order_heading="Order",
        on="On",
        off="Off",
        move_up="Up",
        move_down="Down",
        save="Save",
        cancel="Cancel",
        defaults="Defaults",
        add_collection="Add",
        remove_collection="Remove",
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
    assert result[1].mode == "poster"
    assert result[1].enabled is True
    assert gui.dialog.ok_calls == []


def test_smart_home_xml_editor_uses_inline_controls_and_scrolls(monkeypatch) -> None:
    import sys
    import types

    from mypicsdb3.home_layout_editor import (
        SmartHomeEditorText,
        show_smart_home_layout_editor,
    )
    from mypicsdb3.preferences import HOME_VIEW_KEYS, HomeLayoutItem

    class FakeControl:
        def __init__(self):
            self.label = ""
            self.visible = True
            self.enabled = True
            self.selected = False

        def setLabel(self, value):
            self.label = value

        def setVisible(self, value):
            self.visible = bool(value)

        def setEnabled(self, value):
            self.enabled = bool(value)

        def setSelected(self, value):
            self.selected = bool(value)

    class FakeDialog:
        def select(self, _heading, _options, preselect=-1):
            raise AssertionError("The XML editor must not open a row action list")

        def ok(self, _heading, _message):
            raise AssertionError("No warning is expected in this scenario")

    class FakeWindowXMLDialog:
        last_instance = None

        def __init__(self, *_args):
            FakeWindowXMLDialog.last_instance = self
            self.controls = {}
            self.focus_id = 0
            self.closed = False

        def getControl(self, control_id):
            return self.controls.setdefault(control_id, FakeControl())

        def setFocusId(self, control_id):
            self.focus_id = control_id
            self.onFocus(control_id)

        def getFocusId(self):
            return self.focus_id

        def close(self):
            self.closed = True

        def doModal(self):
            self.onInit()
            # Toggle the first row directly, then move the tenth row below the
            # visible page boundary. The same down-arrow control remains focused
            # after the editor scrolls from rows 1-10 to rows 2-11.
            self.onClick(1101)
            self.onClick(1310)
            assert self.top_index == 1
            assert self.focus_id == 1310
            self.onClick(1401)

    fake_gui = types.SimpleNamespace(
        Dialog=lambda: FakeDialog(),
        WindowXMLDialog=FakeWindowXMLDialog,
    )
    fake_xbmc = types.SimpleNamespace(LOGERROR=4, log=lambda *_args: None)
    fake_addon = types.SimpleNamespace(
        Addon=lambda: types.SimpleNamespace(getAddonInfo=lambda _key: "/addon")
    )
    monkeypatch.setitem(sys.modules, "xbmcgui", fake_gui)
    monkeypatch.setitem(sys.modules, "xbmc", fake_xbmc)
    monkeypatch.setitem(sys.modules, "xbmcaddon", fake_addon)

    items = [
        HomeLayoutItem(kind="builtin", key=key, enabled=index < 6)
        for index, key in enumerate(HOME_VIEW_KEYS)
    ]
    items.append(
        HomeLayoutItem(
            kind="smart",
            saved_search_id=42,
            enabled=True,
            mode="landscape",
        )
    )
    labels = {key: key.replace("_", " ").title() for key in HOME_VIEW_KEYS}
    text = SmartHomeEditorText(
        heading="Home rows",
        row_heading="Row",
        visible_heading="Enabled",
        order_heading="Order",
        on="On",
        off="Off",
        move_up="Up",
        move_down="Down",
        save="Save",
        cancel="Cancel",
        defaults="Defaults",
        add_collection="Add",
        remove_collection="Remove",
        maximum_rows="Maximum",
        no_collections="None",
    )

    result = show_smart_home_layout_editor(
        items,
        labels,
        {42: "Spain favorites"},
        text,
    )

    assert result is not None
    assert result[0].enabled is False
    assert result[9].kind == "smart"
    assert result[9].mode == "poster"
    assert result[10].key == "geotagged"
    dialog = FakeWindowXMLDialog.last_instance
    assert dialog is not None
    assert dialog.controls[1010].label == labels["geotagged"]


def test_action_list_dialog_xml_has_dynamic_list_and_side_actions() -> None:
    import xml.etree.ElementTree as ET

    xml_path = (
        Path(__file__).resolve().parents[1]
        / "plugin.image.mypicsdb3"
        / "resources"
        / "skins"
        / "Default"
        / "1080i"
        / "action_list_dialog.xml"
    )
    root = ET.parse(xml_path).getroot()
    controls = {
        int(node.attrib["id"]): node
        for node in root.findall("./controls/control")
        if "id" in node.attrib
    }

    assert controls[1000].attrib["type"] == "list"
    assert all(controls[control_id].attrib["type"] == "button" for control_id in (1401, 1402, 1403))
    assert controls[1000].findtext("onright") == "1401"
    assert controls[1401].findtext("onleft") == "1000"
