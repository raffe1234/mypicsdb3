#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import py_compile
import tempfile
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
ADDONS = [ROOT / "plugin.image.mypicsdb3", ROOT / "repository.mypicsdb3"]


def fail(message: str) -> None:
    raise SystemExit("ERROR: " + message)


def main() -> int:
    for addon in ADDONS:
        if not addon.is_dir():
            fail("Missing add-on directory: %s" % addon)
        xml_path = addon / "addon.xml"
        root = ET.parse(xml_path).getroot()
        if root.attrib.get("id") != addon.name:
            fail("Folder and add-on id differ: %s" % addon)
        for required in ("LICENSE.txt", "icon.png", "fanart.jpg"):
            if not (addon / required).is_file():
                fail("Missing %s in %s" % (required, addon.name))
        icon = Image.open(addon / "icon.png")
        if icon.size not in {(256, 256), (512, 512)} or icon.mode not in {"RGB", "P"}:
            fail("icon.png must be solid RGB/P 256x256 or 512x512")
        fanart = Image.open(addon / "fanart.jpg")
        if fanart.size not in {(1280, 720), (1920, 1080), (3840, 2160)}:
            fail("fanart.jpg has an unsupported size")

    for path in ROOT.rglob("*"):
        if not path.is_file() or any(part in {"dist", ".git", "__pycache__"} for part in path.parts):
            continue
        data = path.read_bytes()
        if path.suffix.lower() in {".xml", ".txt", ".py", ".md", ".po", ".yml", ".yaml"}:
            if data.startswith(b"\xef\xbb\xbf"):
                fail("BOM found: %s" % path.relative_to(ROOT))
            if b"\r\n" in data:
                fail("CRLF line endings found: %s" % path.relative_to(ROOT))
        if path.suffix.lower() == ".xml":
            ET.parse(path)

    with tempfile.TemporaryDirectory(prefix="mypicsdb3-pyc-") as temp_dir:
        target_root = Path(temp_dir)
        for path in sorted((ROOT / "plugin.image.mypicsdb3").rglob("*.py")):
            target = target_root / (hashlib.sha256(str(path).encode("utf-8")).hexdigest() + ".pyc")
            try:
                py_compile.compile(str(path), cfile=str(target), doraise=True)
            except py_compile.PyCompileError as exc:
                fail("Python compilation failed for %s: %s" % (path.relative_to(ROOT), exc))
    print("Verification passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
