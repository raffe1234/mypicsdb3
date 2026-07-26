#!/usr/bin/env python3
from __future__ import annotations

import argparse
import re
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PLUGIN_XML = ROOT / "plugin.image.mypicsdb3" / "addon.xml"
REPOSITORY_XML = ROOT / "repository.mypicsdb3" / "addon.xml"
PACKAGE_INIT = ROOT / "plugin.image.mypicsdb3" / "resources" / "lib" / "mypicsdb3" / "__init__.py"
VERSION_RE = re.compile(r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)(?:[-+][0-9A-Za-z.-]+)?$")


def update_xml(path: Path, version: str) -> None:
    tree = ET.parse(path)
    root = tree.getroot()
    root.set("version", version)
    ET.indent(tree, space="  ")
    tree.write(path, encoding="UTF-8", xml_declaration=True, short_empty_elements=True)
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write("\n")


def xml_version(path: Path) -> str:
    return ET.parse(path).getroot().attrib["version"]


def validate_version(parser: argparse.ArgumentParser, value: str, label: str) -> None:
    if not VERSION_RE.fullmatch(value):
        parser.error("%s must use semantic version syntax such as 0.2.0" % label)


def main() -> int:
    parser = argparse.ArgumentParser(description="Update the MyPicsDB 3 project version")
    parser.add_argument("version", help="Plug-in semantic version, for example 0.2.27")
    parser.add_argument(
        "--repository-version",
        help=(
            "Update the repository add-on too. Omit this for normal plug-in releases "
            "so repository.mypicsdb3 keeps its existing version."
        ),
    )
    args = parser.parse_args()
    validate_version(parser, args.version, "Plug-in version")
    if args.repository_version is not None:
        validate_version(parser, args.repository_version, "Repository version")

    update_xml(PLUGIN_XML, args.version)
    source = PACKAGE_INIT.read_text(encoding="utf-8")
    source, count = re.subn(
        r'^VERSION\s*=\s*"[^"]+"$',
        'VERSION = "%s"' % args.version,
        source,
        flags=re.MULTILINE,
    )
    if count != 1:
        raise RuntimeError("Could not update VERSION in %s" % PACKAGE_INIT)
    with PACKAGE_INIT.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write(source)

    if args.repository_version is not None:
        update_xml(REPOSITORY_XML, args.repository_version)
        print("Repository add-on version updated to", args.repository_version)
    else:
        print("Repository add-on version remains", xml_version(REPOSITORY_XML))

    print("Plug-in version updated to", args.version)
    print("Remember to update CHANGELOG.md before releasing.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
