#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

from estuary_skin import DEFAULT_OUTPUT, EstuaryConfig, patch_skin  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Create an Omega Estuary fork with MyPicsDB 3 picture widgets")
    parser.add_argument("skin_dir", type=Path, help="Path to the Kodi 21 Omega skin.estuary source directory")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()

    plugin_xml = ROOT / "plugin.image.mypicsdb3" / "addon.xml"
    plugin_version = ET.parse(plugin_xml).getroot().attrib["version"]
    output = patch_skin(args.skin_dir, args.output, EstuaryConfig.load(), plugin_version)
    print("Created:", output)
    print("Kodi add-on id: skin.estuary.mypicsdb3")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
