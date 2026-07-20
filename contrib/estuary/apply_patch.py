#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

from estuary_skin import (  # noqa: E402
    DEFAULT_OUTPUT,
    EstuaryProjectConfig,
    patch_skin,
)


def main() -> int:
    project = EstuaryProjectConfig.load()
    parser = argparse.ArgumentParser(
        description="Create an Estuary fork with MyPicsDB 3 picture widgets"
    )
    parser.add_argument(
        "skin_dir",
        type=Path,
        help="Path to a matching official skin.estuary source directory",
    )
    parser.add_argument(
        "--channel",
        choices=tuple(project.channels),
        default=next(iter(project.channels)),
    )
    parser.add_argument("--release-index", type=int, default=0)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()

    plugin_xml = ROOT / "plugin.image.mypicsdb3" / "addon.xml"
    plugin_version = ET.parse(plugin_xml).getroot().attrib["version"]
    config = project.release_config(args.channel, args.release_index)
    output = patch_skin(args.skin_dir, args.output, config, plugin_version)
    print("Created:", output)
    print("Kodi channel:", config.channel)
    print("Kodi source:", config.ref)
    print("Kodi add-on id:", config.target_addon_id)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
