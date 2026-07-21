from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_album_default_action_is_registered_as_a_kodi_context_item() -> None:
    addon = ROOT / "plugin.image.mypicsdb3" / "addon.xml"
    root = ET.parse(addon).getroot()
    extension = next(
        node
        for node in root.findall("extension")
        if node.attrib.get("point") == "kodi.context.item"
    )
    item = extension.find("./menu/item")

    assert item is not None
    assert item.attrib["library"] == "context.py"
    assert item.findtext("label") == "32215"
    assert item.findtext("visible") == (
        "String.StartsWith(Container.FolderPath,plugin://plugin.image.mypicsdb3/folder)"
    )
    assert (ROOT / "plugin.image.mypicsdb3" / "context.py").is_file()
