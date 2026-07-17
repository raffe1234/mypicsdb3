from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from pathlib import Path

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


def test_home_rows_show_current_or_default_selection():
    settings = settings_by_id()
    defaults = ["recent_taken", "recent_added", "random_memories", "recent_albums", "random_albums", "on_this_day", "favorites", "rated", "geotagged"]
    for number, expected in enumerate(defaults, start=1):
        setting = settings["home_row_%d" % number]
        assert setting.findtext("default") == expected
        control = setting.find("control")
        assert control is not None
        assert control.attrib == {"type": "spinner", "format": "string"}


def test_english_catalogue_is_separated_and_has_clear_labels():
    text = STRINGS.read_text(encoding="utf-8")
    for label in ("Default items per home-screen row", "Pictures per browser page", "Row 1 content", "Row 9 content"):
        assert ('msgid "%s"' % label) in text
        assert ('msgstr "%s"' % label) in text
    assert not re.search(r'msgstr "[^"]*"\nmsgctxt "#', text)
