from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

VIEW_VALUES = {
    "none",
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
    "smart",
}

DEFAULT_ROWS = [
    "recent_taken",
    "recent_added",
    "random_memories",
    "recent_albums",
    "random_albums",
    "on_this_day",
    "none",
    "none",
    "none",
]

ROUTES = [
    "recent-taken?widget=1&amp;home=1",
    "recent-added?widget=1&amp;home=1",
    "random?widget=1&amp;home=1",
    "recent-folders?widget=1&amp;home=1",
    "random-folders?widget=1&amp;home=1",
    "on-this-day?widget=1&amp;home=1",
    "on-this-day-random?widget=1&amp;home=1",
    "favorites?widget=1&amp;home=1",
    "rated?widget=1&amp;home=1",
    "geotagged?widget=1&amp;home=1",
]

HEADINGS = [
    "Recently taken",
    "Recently added",
    "Random memories",
    "Recent albums",
    "Random albums",
    "On this day",
    "On this day - random",
    "Favorites",
    "Rated pictures",
    "Geotagged pictures",
]

def test_home_screen_settings_offer_nine_ordered_slots() -> None:
    root = ET.parse(
        ROOT / "plugin.image.mypicsdb3" / "resources" / "settings.xml"
    ).getroot()
    settings = {node.attrib["id"]: node for node in root.findall(".//setting")}

    assert settings["show_media_sources"].findtext("default") == "true"
    assert settings["widget_limit"].findtext("default") == "10"
    assert settings["widget_limit"].findtext("./constraints/minimum") == "4"
    assert settings["widget_limit"].findtext("./constraints/maximum") == "40"
    assert settings["home_widget_limit"].findtext("visible") == "false"
    assert settings["home_widget_limit_migrated_v2"].findtext("visible") == "false"
    configure = settings["configure_home_screen"]
    assert configure.attrib["type"] == "action"
    assert configure.findtext("data") == (
        "RunPlugin(plugin://plugin.image.mypicsdb3/action/configure-home)"
    )
    assert configure.find("control").attrib == {"type": "button", "format": "action"}
    assert configure.findtext("./control/close") == "true"
    assert settings["home_layout"].findtext("level") == "4"
    assert settings["home_layout"].findtext("visible") == "false"
    assert settings["home_layout_v2"].findtext("level") == "4"
    assert settings["home_layout_v2"].findtext("visible") == "false"
    for position, expected_default in enumerate(DEFAULT_ROWS, start=1):
        setting = settings[f"home_row_{position}"]
        assert setting.findtext("default") == expected_default
        assert setting.findtext("level") == "4"
        assert setting.findtext("visible") == "false"
        values = {option.text for option in setting.findall("./constraints/options/option")}
        assert values == VIEW_VALUES
        assert settings[f"home_smart_id_{position}"].attrib["type"] == "integer"
        assert settings[f"home_smart_name_{position}"].attrib["type"] == "string"
        assert settings[f"home_smart_mode_{position}"].findtext("default") == "poster"


def test_general_settings_offer_estuary_album_views() -> None:
    root = ET.parse(
        ROOT / "plugin.image.mypicsdb3" / "resources" / "settings.xml"
    ).getroot()
    settings = {node.attrib["id"]: node for node in root.findall(".//setting")}

    setting = settings["album_view_mode"]
    assert setting.findtext("default") == "55"
    assert {option.text for option in setting.findall("./constraints/options/option")} == {
        "0",
        "50",
        "52",
        "53",
        "54",
        "55",
        "500",
    }


def test_general_settings_offer_addon_menu_visibility_editor() -> None:
    root = ET.parse(
        ROOT / "plugin.image.mypicsdb3" / "resources" / "settings.xml"
    ).getroot()
    settings = {node.attrib["id"]: node for node in root.findall(".//setting")}

    configure = settings["configure_main_menu"]
    assert configure.attrib["type"] == "action"
    assert configure.findtext("data") == (
        "RunPlugin(plugin://plugin.image.mypicsdb3/action/configure-menu)"
    )
    assert configure.find("control").attrib == {
        "type": "button",
        "format": "action",
    }
    hidden = settings["hidden_main_menu_nodes"]
    assert hidden.findtext("level") == "4"
    assert hidden.findtext("visible") == "false"

def test_home_fragment_has_visible_titles_and_all_routes() -> None:
    home = (ROOT / "contrib" / "estuary" / "Home-pictures-group.xml").read_text(
        encoding="utf-8"
    )

    assert "Addon.SettingBool(plugin.image.mypicsdb3,show_media_sources)" in home
    for position in range(1, 10):
        assert f"Addon.SettingStr(plugin.image.mypicsdb3,home_row_{position})" in home
    for route in ROUTES:
        assert f"plugin://plugin.image.mypicsdb3/{route}" in home
    for heading in HEADINGS:
        assert f'value="{heading}"' in home
    assert home.count('<param name="widget_limit" value="40"/>') == 117
    assert home.count("widget=1&amp;home=1") == 117
    assert home.count("saved-search?id=$INFO[Addon.SettingInt") == 27
    assert "Addon.SettingInt(plugin.image.mypicsdb3,home_widget_limit)" not in home
    assert "&amp;limit=" not in home
    assert "Window(Home).Property(MyPicsDB3.HomeWidgetGeneration)" in home
    assert "WidgetListSquareMyPicsDB" in home
    assert "WidgetListLandscapeMyPicsDB" in home
    assert "$ADDON[plugin.image.mypicsdb3" not in home
