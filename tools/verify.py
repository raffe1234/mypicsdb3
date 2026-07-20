#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import py_compile
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Iterable, Sequence

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
STATIC_ADDONS = [ROOT / "plugin.image.mypicsdb3", ROOT / "repository.mypicsdb3"]

def fail(message: str) -> None:
    raise SystemExit("ERROR: " + message)


def addon_dirs(extra_addons: Iterable[Path] = ()) -> list[Path]:
    result = list(STATIC_ADDONS)
    for addon in extra_addons:
        addon = Path(addon)
        if addon not in result:
            result.append(addon)
    return result


def verify_addon(addon: Path) -> None:
    if not addon.is_dir():
        fail("Missing add-on directory: %s" % addon)
    xml_path = addon / "addon.xml"
    root = ET.parse(xml_path).getroot()
    if root.attrib.get("id") != addon.name:
        fail("Folder and add-on id differ: %s" % addon)
    if not (addon / "LICENSE.txt").is_file():
        fail("Missing LICENSE.txt in %s" % addon.name)
    metadata = None
    for extension in root.findall("extension"):
        if extension.attrib.get("point") == "xbmc.addon.metadata":
            metadata = extension
            break
    if metadata is None:
        fail("Missing xbmc.addon.metadata extension in %s" % addon.name)
    assets = metadata.find("assets")
    icon_rel = assets.findtext("icon") if assets is not None else None
    fanart_rel = assets.findtext("fanart") if assets is not None else None
    if not icon_rel or not fanart_rel:
        fail("Missing icon/fanart asset declarations in %s" % addon.name)
    icon_path = addon / icon_rel
    fanart_path = addon / fanart_rel
    if not icon_path.is_file() or not fanart_path.is_file():
        fail("Declared icon/fanart files are missing in %s" % addon.name)
    icon = Image.open(icon_path)
    if icon.size not in {(256, 256), (512, 512)} or icon.mode not in {"RGB", "RGBA", "P"}:
        fail("icon.png must be RGB/RGBA/P 256x256 or 512x512")
    fanart = Image.open(fanart_path)
    if fanart.size not in {(1280, 720), (1920, 1080), (3840, 2160)}:
        fail("fanart.jpg has an unsupported size")

    if addon.name == "skin.estuary.mypicsdb3":
        home = addon / "xml" / "Home.xml"
        if not home.is_file():
            fail("Generated skin is missing xml/Home.xml")
        home_text = home.read_text(encoding="utf-8")
        if "plugin://plugin.image.mypicsdb3/recent-taken?limit=15" not in home_text:
            fail("Generated skin does not contain the MyPicsDB 3 Pictures widgets")
        dependencies = {
            node.attrib.get("addon"): node.attrib.get("version")
            for node in root.findall("./requires/import")
        }
        if "plugin.image.mypicsdb3" not in dependencies:
            fail("Generated skin does not depend on plugin.image.mypicsdb3")


def verify_text_and_xml() -> None:
    for path in ROOT.rglob("*"):
        if not path.is_file() or any(part in {"dist", "build", ".git", "__pycache__", ".cache"} for part in path.parts):
            continue
        data = path.read_bytes()
        if path.suffix.lower() in {".xml", ".txt", ".py", ".md", ".po", ".yml", ".yaml", ".json"}:
            if data.startswith(b"\xef\xbb\xbf"):
                fail("BOM found: %s" % path.relative_to(ROOT))
            if b"\r\n" in data:
                fail("CRLF line endings found: %s" % path.relative_to(ROOT))
        if path.suffix.lower() == ".xml":
            ET.parse(path)
        if path.suffix.lower() == ".json":
            import json

            json.loads(path.read_text(encoding="utf-8"))


def compile_python() -> None:
    roots = [ROOT / "plugin.image.mypicsdb3", ROOT / "tools", ROOT / "contrib" / "estuary"]
    with tempfile.TemporaryDirectory(prefix="mypicsdb3-pyc-") as temp_dir:
        target_root = Path(temp_dir)
        for source_root in roots:
            for path in sorted(source_root.rglob("*.py")):
                target = target_root / (hashlib.sha256(str(path).encode("utf-8")).hexdigest() + ".pyc")
                try:
                    py_compile.compile(str(path), cfile=str(target), doraise=True)
                except py_compile.PyCompileError as exc:
                    fail("Python compilation failed for %s: %s" % (path.relative_to(ROOT), exc))


def main(extra_addons: Sequence[Path] = ()) -> int:
    for addon in addon_dirs(extra_addons):
        verify_addon(addon)
    verify_text_and_xml()
    compile_python()
    print("Verification passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
