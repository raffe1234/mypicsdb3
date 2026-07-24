from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def context_items() -> dict[str, ET.Element]:
    addon = ROOT / "plugin.image.mypicsdb3" / "addon.xml"
    root = ET.parse(addon).getroot()
    extension = next(
        node
        for node in root.findall("extension")
        if node.attrib.get("point") == "kodi.context.item"
    )
    return {
        item.attrib["library"]: item
        for item in extension.findall("./menu/item")
    }


def test_rating_settings_are_registered_as_a_kodi_context_item() -> None:
    item = context_items()["rating_context.py"]

    assert item.findtext("label") == "32400"
    assert item.findtext("visible") == (
        "String.StartsWith(Container.FolderPath,plugin://plugin.image.mypicsdb3)"
    )
    assert (ROOT / "plugin.image.mypicsdb3" / "rating_context.py").is_file()


def test_album_default_action_is_registered_as_a_kodi_context_item() -> None:
    item = context_items()["context.py"]

    assert item.findtext("label") == "32215"
    assert item.findtext("visible") == (
        "String.StartsWith(Container.FolderPath,plugin://plugin.image.mypicsdb3/folder)"
    )
    assert (ROOT / "plugin.image.mypicsdb3" / "context.py").is_file()
