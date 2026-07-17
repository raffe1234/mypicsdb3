#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import shutil
import tempfile
import urllib.request
import xml.etree.ElementTree as ET
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Iterable, Optional

ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT / "contrib" / "estuary" / "upstream.json"
FRAGMENT_PATH = ROOT / "contrib" / "estuary" / "Home-pictures-group.xml"
DEFAULT_CACHE = ROOT / ".cache" / "estuary"
DEFAULT_OUTPUT = ROOT / "build" / "skin.estuary.mypicsdb3"


@dataclass(frozen=True)
class EstuaryConfig:
    kodi_branch: str
    ref: str
    archive_url: str
    source_addon_id: str
    target_addon_id: str
    target_name: str
    skin_version: str
    project_url: str

    @classmethod
    def load(cls, path: Path = CONFIG_PATH) -> "EstuaryConfig":
        data = json.loads(path.read_text(encoding="utf-8"))
        return cls(**data)


def _safe_member_parts(name: str) -> tuple[str, ...]:
    path = PurePosixPath(name)
    if path.is_absolute() or ".." in path.parts:
        raise RuntimeError("Unsafe archive member: %s" % name)
    return tuple(part for part in path.parts if part not in {"", "."})


def _find_skin_prefix(names: Iterable[str], source_addon_id: str) -> tuple[str, ...]:
    suffix = ("addons", source_addon_id, "addon.xml")
    matches = []
    for name in names:
        parts = _safe_member_parts(name)
        if len(parts) >= len(suffix) and parts[-len(suffix) :] == suffix:
            matches.append(parts[: -1])
    if len(matches) != 1:
        raise RuntimeError("Expected exactly one %s source tree, found %d" % (source_addon_id, len(matches)))
    return matches[0]


def extract_skin_from_archive(archive_path: Path, output_dir: Path, source_addon_id: str) -> Path:
    if output_dir.exists():
        shutil.rmtree(output_dir)
    output_dir.mkdir(parents=True)

    with zipfile.ZipFile(archive_path) as archive:
        prefix = _find_skin_prefix(archive.namelist(), source_addon_id)
        extracted = 0
        for member in archive.infolist():
            parts = _safe_member_parts(member.filename)
            if len(parts) < len(prefix) or parts[: len(prefix)] != prefix:
                continue
            relative_parts = parts[len(prefix) :]
            if not relative_parts:
                continue
            target = output_dir.joinpath(*relative_parts)
            if member.is_dir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(member) as source, target.open("wb") as destination:
                shutil.copyfileobj(source, destination)
            extracted += 1
    if extracted == 0 or not (output_dir / "addon.xml").is_file() or not (output_dir / "xml" / "Home.xml").is_file():
        raise RuntimeError("The downloaded archive did not contain a usable Estuary skin")
    return output_dir


def download_archive(config: EstuaryConfig, cache_dir: Path = DEFAULT_CACHE, force: bool = False) -> Path:
    cache_dir.mkdir(parents=True, exist_ok=True)
    destination = cache_dir / (config.ref + ".zip")
    if destination.is_file() and destination.stat().st_size > 1024 and not force:
        return destination

    request = urllib.request.Request(
        config.archive_url,
        headers={"User-Agent": "MyPicsDB3-Estuary-Builder/%s" % config.skin_version},
    )
    temporary = destination.with_suffix(".zip.part")
    try:
        with urllib.request.urlopen(request, timeout=120) as response, temporary.open("wb") as output:
            shutil.copyfileobj(response, output)
        if temporary.stat().st_size <= 1024:
            raise RuntimeError("Downloaded Estuary archive is unexpectedly small")
        with zipfile.ZipFile(temporary) as archive:
            archive.testzip()
        temporary.replace(destination)
    finally:
        temporary.unlink(missing_ok=True)
    return destination


def _metadata_extension(root: ET.Element) -> ET.Element:
    for extension in root.findall("extension"):
        if extension.attrib.get("point") == "xbmc.addon.metadata":
            return extension
    return ET.SubElement(root, "extension", {"point": "xbmc.addon.metadata"})


def _replace_localized(metadata: ET.Element, tag: str, text: str) -> None:
    candidates = [node for node in metadata.findall(tag) if node.attrib.get("lang") in {None, "en_GB"}]
    if candidates:
        candidates[0].text = text
        for duplicate in candidates[1:]:
            metadata.remove(duplicate)
    else:
        ET.SubElement(metadata, tag, {"lang": "en_GB"}).text = text


def _set_metadata_value(metadata: ET.Element, tag: str, text: str) -> None:
    node = metadata.find(tag)
    if node is None:
        node = ET.SubElement(metadata, tag)
    node.text = text


def patch_addon_xml(addon_path: Path, config: EstuaryConfig, plugin_version: str) -> None:
    tree = ET.parse(addon_path)
    root = tree.getroot()
    if root.attrib.get("id") != config.source_addon_id:
        raise RuntimeError("Expected add-on id %s, found %s" % (config.source_addon_id, root.attrib.get("id")))

    root.set("id", config.target_addon_id)
    root.set("name", config.target_name)
    root.set("version", config.skin_version)
    root.set("provider-name", "Estuary contributors and MyPicsDB 3 contributors")

    requires = root.find("requires")
    if requires is None:
        requires = ET.Element("requires")
        root.insert(0, requires)
    plugin_import = None
    for dependency in requires.findall("import"):
        if dependency.attrib.get("addon") == "plugin.image.mypicsdb3":
            plugin_import = dependency
            break
    if plugin_import is None:
        plugin_import = ET.SubElement(requires, "import")
    plugin_import.set("addon", "plugin.image.mypicsdb3")
    plugin_import.set("version", plugin_version)

    metadata = _metadata_extension(root)
    _replace_localized(metadata, "summary", "Estuary for Kodi 21 Omega with MyPicsDB 3 picture widgets")
    _replace_localized(
        metadata,
        "description",
        "A separately maintained Estuary fork for Kodi 21 Omega. It adds fast MyPicsDB 3 rows to the Pictures home screen while keeping the rest of Estuary unchanged.",
    )
    _replace_localized(
        metadata,
        "disclaimer",
        "Independent community fork based on Kodi's Estuary skin. It is not an official Kodi skin release.",
    )
    _set_metadata_value(metadata, "source", config.project_url)
    _set_metadata_value(metadata, "website", config.project_url)
    _set_metadata_value(
        metadata,
        "news",
        "Based on Estuary from Kodi %s. Adds MyPicsDB 3 widgets to the Pictures home screen." % config.ref,
    )

    ET.indent(tree, space="  ")
    tree.write(addon_path, encoding="UTF-8", xml_declaration=True, short_empty_elements=True)
    with addon_path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write("\n")


def patch_home_xml(home_path: Path, fragment_path: Path = FRAGMENT_PATH) -> None:
    fragment = fragment_path.read_text(encoding="utf-8").rstrip() + "\n"
    home = home_path.read_text(encoding="utf-8-sig")
    pattern = re.compile(
        r'(?ms)^\s*<control type="group" id="4000">.*?(?=^\s*<control type="group" id="17000">)'
    )
    patched, count = pattern.subn(fragment, home, count=1)
    if count != 1:
        raise RuntimeError("Could not locate the Kodi 21 Omega Pictures home group")
    with home_path.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write(patched)


def patch_skin(source_dir: Path, output_dir: Path, config: EstuaryConfig, plugin_version: str) -> Path:
    source_dir = source_dir.resolve()
    if not (source_dir / "addon.xml").is_file() or not (source_dir / "xml" / "Home.xml").is_file():
        raise RuntimeError("The input directory is not a usable Estuary source directory: %s" % source_dir)
    if output_dir.exists():
        shutil.rmtree(output_dir)
    shutil.copytree(source_dir, output_dir)

    patch_addon_xml(output_dir / "addon.xml", config, plugin_version)
    patch_home_xml(output_dir / "xml" / "Home.xml")
    notice = """# Estuary MyPicsDB 3\n\nThis package is generated from Kodi's Estuary source at `{ref}` and patched by\nthe MyPicsDB 3 project. Standard Estuary remains installed separately.\n\nUpstream source: https://github.com/xbmc/xbmc/tree/{ref}/addons/skin.estuary\nMyPicsDB 3 source: {project}\n""".format(ref=config.ref, project=config.project_url)
    with (output_dir / "MYPICSDB3_UPSTREAM.md").open("w", encoding="utf-8", newline="\n") as handle:
        handle.write(notice)
    return output_dir


def prepare_skin(
    plugin_version: str,
    source_dir: Optional[Path] = None,
    output_dir: Path = DEFAULT_OUTPUT,
    cache_dir: Path = DEFAULT_CACHE,
    force_download: bool = False,
) -> Path:
    config = EstuaryConfig.load()
    if source_dir is None:
        archive = download_archive(config, cache_dir=cache_dir, force=force_download)
        with tempfile.TemporaryDirectory(prefix="mypicsdb3-estuary-") as temporary:
            extracted = Path(temporary) / config.source_addon_id
            extract_skin_from_archive(archive, extracted, config.source_addon_id)
            return patch_skin(extracted, output_dir, config, plugin_version)
    return patch_skin(source_dir, output_dir, config, plugin_version)


def main() -> int:
    parser = argparse.ArgumentParser(description="Build the Estuary MyPicsDB 3 skin from official Kodi source")
    parser.add_argument("--source", type=Path, help="Local skin.estuary directory; skips the download")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--cache", type=Path, default=DEFAULT_CACHE)
    parser.add_argument("--plugin-version", default=None, help="Required MyPicsDB 3 plug-in version")
    parser.add_argument("--force-download", action="store_true")
    args = parser.parse_args()

    plugin_version = args.plugin_version
    if plugin_version is None:
        plugin_xml = ROOT / "plugin.image.mypicsdb3" / "addon.xml"
        plugin_version = ET.parse(plugin_xml).getroot().attrib["version"]
    output = prepare_skin(
        plugin_version=plugin_version,
        source_dir=args.source,
        output_dir=args.output,
        cache_dir=args.cache,
        force_download=args.force_download,
    )
    print("Created:", output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
