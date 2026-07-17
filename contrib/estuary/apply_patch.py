#!/usr/bin/env python3
from __future__ import annotations

import argparse
import re
import shutil
import sys
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description="Create an Omega Estuary fork with MyPicsDB 3 picture widgets")
    parser.add_argument("skin_dir", type=Path, help="Path to the Omega skin.estuary source directory")
    parser.add_argument("--output", type=Path, help="Output directory; defaults to a sibling named skin.estuary.mypicsdb3")
    args = parser.parse_args()

    source = args.skin_dir.resolve()
    if not (source / "addon.xml").is_file() or not (source / "xml" / "Home.xml").is_file():
        parser.error("The input directory is not an Estuary source directory")
    output = (args.output or source.with_name("skin.estuary.mypicsdb3")).resolve()
    if output.exists():
        parser.error("Output already exists: %s" % output)
    shutil.copytree(source, output)

    addon_path = output / "addon.xml"
    home_path = output / "xml" / "Home.xml"
    shutil.copy2(addon_path, addon_path.with_suffix(".xml.mypicsdb3-backup"))
    shutil.copy2(home_path, home_path.with_suffix(".xml.mypicsdb3-backup"))

    addon = addon_path.read_text(encoding="utf-8-sig")
    if 'id="skin.estuary"' not in addon:
        raise RuntimeError("Expected skin.estuary id was not found")
    addon = addon.replace('id="skin.estuary"', 'id="skin.estuary.mypicsdb3"', 1)
    addon = addon.replace('name="Estuary"', 'name="Estuary MyPicsDB 3"', 1)
    addon_path.write_text(addon, encoding="utf-8", newline="\n")

    fragment_path = Path(__file__).with_name("Home-pictures-group.xml")
    fragment = fragment_path.read_text(encoding="utf-8").rstrip() + "\n"
    home = home_path.read_text(encoding="utf-8-sig")
    pattern = re.compile(
        r'(?ms)^\s*<control type="group" id="4000">.*?(?=^\s*<control type="group" id="17000">)'
    )
    patched, count = pattern.subn(fragment, home, count=1)
    if count != 1:
        raise RuntimeError("Could not locate the Omega Pictures home group")
    home_path.write_text(patched, encoding="utf-8", newline="\n")

    print("Created:", output)
    print("Kodi add-on id: skin.estuary.mypicsdb3")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
