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
    "favorites",
    "rated",
    "geotagged",
}

DEFAULT_ROWS = [
    "recent_taken",
    "recent_added",
    "random_memories",
    "recent_albums",
    "random_albums",
    "on_this_day",
    "favorites",
    "rated",
    "geotagged",
]

ROUTES = [
    "recent-taken?limit=15",
    "recent-added?limit=15",
    "random?limit=15",
    "recent-folders?limit=15",
    "random-folders?limit=15",
    "on-this-day?limit=15",
    "favorites?limit=15",
    "rated?limit=15",
    "geotagged?limit=15",
]

HEADINGS = [
    "Recently taken",
    "Recently added",
    "Random memories",
    "Recent albums",
    "Random albums",
    "On this day",
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
    for position, expected_default in enumerate(DEFAULT_ROWS, start=1):
        setting = settings[f"home_row_{position}"]
        assert setting.findtext("default") == expected_default
        values = {option.text for option in setting.findall("./constraints/options/option")}
        assert values == VIEW_VALUES

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
    assert "$ADDON[plugin.image.mypicsdb3" not in home
