from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from pathlib import Path

from mypicsdb3.config import from_getter

ROOT = Path(__file__).resolve().parents[1]
SETTINGS = ROOT / "plugin.image.mypicsdb3" / "resources" / "settings.xml"
STRINGS = ROOT / "plugin.image.mypicsdb3" / "resources" / "language" / "resource.language.en_gb" / "strings.po"


def settings_by_id():
    root = ET.parse(SETTINGS).getroot()
    return {node.attrib["id"]: node for node in root.findall(".//setting") if "id" in node.attrib}


def test_general_numeric_settings_show_labels_and_values():
    settings = settings_by_id()
    for setting_id, label in (("widget_limit", "32011"), ("browser_page_size", "32012")):
        setting = settings[setting_id]
        assert setting.attrib["label"] == label
        control = setting.find("control")
        assert control is not None
        assert control.attrib == {"type": "spinner", "format": "string"}
    assert settings["widget_limit"].findtext("./constraints/maximum") == "50"


def test_home_widget_limit_clamps_legacy_values_to_50():
    values = {"widget_limit": "100"}
    settings = from_getter(lambda key: values.get(key, ""), "/tmp/mypicsdb3")

    assert settings.widget_limit == 50


def test_home_screen_uses_editor_and_internal_legacy_slots():
    settings = settings_by_id()
    editor = settings["configure_home_screen"]
    assert editor.attrib["type"] == "action"
    control = editor.find("control")
    assert control.attrib == {"type": "button", "format": "action"}
    assert control.findtext("close") == "true"
    defaults = ["recent_taken", "recent_added", "random_memories", "recent_albums", "random_albums", "on_this_day", "none", "none", "none"]
    for number, expected in enumerate(defaults, start=1):
        setting = settings["home_row_%d" % number]
        assert setting.findtext("default") == expected
        assert setting.findtext("level") == "4"
        assert setting.findtext("visible") == "false"


def test_album_view_setting_shows_named_choices():
    setting = settings_by_id()["album_view_mode"]
    assert setting.findtext("default") == "55"
    assert setting.find("control").attrib == {"type": "list", "format": "integer"}


def test_minimum_rating_setting_has_explicit_null_and_zero_semantics():
    setting = settings_by_id()["minimum_rating_policy"]
    assert setting.findtext("default") == "all"
    assert setting.find("control").attrib == {"type": "list", "format": "string"}
    assert [option.text for option in setting.findall("./constraints/options/option")] == [
        "all",
        "rated_and_unrated",
        "1",
        "2",
        "3",
        "4",
        "5",
    ]


def test_english_catalogue_is_separated_and_has_clear_labels():
    text = STRINGS.read_text(encoding="utf-8")
    for label in (
        "Default items per home-screen row",
        "Pictures per browser page",
        "Default album view",
        "Configure home-screen rows",
        "Minimum picture rating",
        "Rated and unrated (exclude rating 0)",
    ):
        assert ('msgid "%s"' % label) in text
        assert ('msgstr "%s"' % label) in text
    assert not re.search(r'msgstr "[^"]*"\nmsgctxt "#', text)
