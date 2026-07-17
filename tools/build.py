#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import shutil
import tarfile
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path
from typing import Iterable, Sequence

ROOT = Path(__file__).resolve().parents[1]
DIST = ROOT / "dist"
BUILD = ROOT / "build"
STATIC_ADDON_DIRS = [ROOT / "plugin.image.mypicsdb3", ROOT / "repository.mypicsdb3"]
EXCLUDED_PARTS = {".git", "dist", "build", ".cache", "__pycache__", ".pytest_cache", ".venv", "venv", "htmlcov"}
EXCLUDED_NAMES = {".coverage", "kodi-addon-checker.log"}


def addon_version(addon_dir: Path) -> str:
    return ET.parse(addon_dir / "addon.xml").getroot().attrib["version"]


def zip_addon(addon_dir: Path, output: Path) -> None:
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for path in sorted(addon_dir.rglob("*")):
            if not path.is_file() or "__pycache__" in path.parts or path.suffix == ".pyc":
                continue
            arcname = Path(addon_dir.name) / path.relative_to(addon_dir)
            info = zipfile.ZipInfo.from_file(path, arcname.as_posix())
            info.external_attr = 0o100644 << 16
            with path.open("rb") as source:
                archive.writestr(info, source.read(), compress_type=zipfile.ZIP_DEFLATED, compresslevel=9)



def addon_asset_paths(addon_dir: Path) -> tuple[Path, Path]:
    root = ET.parse(addon_dir / "addon.xml").getroot()
    metadata = next(
        (extension for extension in root.findall("extension") if extension.attrib.get("point") == "xbmc.addon.metadata"),
        None,
    )
    if metadata is None or metadata.find("assets") is None:
        raise RuntimeError("Missing metadata assets in %s" % addon_dir.name)
    assets = metadata.find("assets")
    icon = assets.findtext("icon")
    fanart = assets.findtext("fanart")
    if not icon or not fanart:
        raise RuntimeError("Missing icon or fanart declaration in %s" % addon_dir.name)
    return addon_dir / icon, addon_dir / fanart


def copy_repository_entry(addon_dir: Path, zip_path: Path, repo_root: Path) -> None:
    target = repo_root / addon_dir.name
    target.mkdir(parents=True, exist_ok=True)
    shutil.copy2(zip_path, target / zip_path.name)
    shutil.copy2(addon_dir / "addon.xml", target / "addon.xml")
    icon_path, fanart_path = addon_asset_paths(addon_dir)
    shutil.copy2(icon_path, target / "icon.png")
    shutil.copy2(fanart_path, target / "fanart.jpg")
    digest = hashlib.sha256(zip_path.read_bytes()).hexdigest()
    (target / (zip_path.name + ".sha256")).write_text(digest + "\n", encoding="ascii")


def build_addons_xml(repo_root: Path, addon_dirs: Sequence[Path]) -> None:
    root = ET.Element("addons")
    for addon_dir in addon_dirs:
        root.append(ET.parse(addon_dir / "addon.xml").getroot())
    ET.indent(root, space="  ")
    payload = ET.tostring(root, encoding="utf-8", xml_declaration=True)
    addons_xml = repo_root / "addons.xml"
    addons_xml.write_bytes(payload + b"\n")
    (repo_root / "addons.xml.md5").write_text(hashlib.md5(addons_xml.read_bytes()).hexdigest() + "\n", encoding="ascii")


def source_files() -> Iterable[Path]:
    for path in sorted(ROOT.rglob("*")):
        if not path.is_file():
            continue
        relative = path.relative_to(ROOT)
        if path.name in EXCLUDED_NAMES or any(part in EXCLUDED_PARTS for part in relative.parts):
            continue
        yield path


def build_source_archives(version: str) -> None:
    prefix = Path("mypicsdb3-%s" % version)
    tar_output = DIST / ("mypicsdb3-%s.tar.gz" % version)
    with tarfile.open(tar_output, "w:gz", compresslevel=9) as archive:
        for path in source_files():
            archive.add(path, arcname=prefix / path.relative_to(ROOT), recursive=False)

    zip_output = DIST / ("mypicsdb3-%s-source.zip" % version)
    with zipfile.ZipFile(zip_output, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for path in source_files():
            arcname = prefix / path.relative_to(ROOT)
            info = zipfile.ZipInfo.from_file(path, arcname.as_posix())
            info.external_attr = 0o100644 << 16
            archive.writestr(info, path.read_bytes(), compress_type=zipfile.ZIP_DEFLATED, compresslevel=9)


def write_checksums() -> None:
    entries = []
    for path in sorted(DIST.glob("*")):
        if path.is_file() and path.name != "SHA256SUMS.txt":
            entries.append("%s  %s" % (hashlib.sha256(path.read_bytes()).hexdigest(), path.name))
    (DIST / "SHA256SUMS.txt").write_text("\n".join(entries) + "\n", encoding="ascii")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build MyPicsDB 3 Kodi packages and repository metadata")
    parser.add_argument("--skip-skin", action="store_true", help="Build only the plug-in and repository add-ons")
    parser.add_argument("--estuary-source", type=Path, help="Use a local Kodi 21 skin.estuary source directory")
    parser.add_argument("--force-estuary-download", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    from estuary_skin import DEFAULT_OUTPUT, prepare_skin
    from verify import main as verify

    addon_dirs = list(STATIC_ADDON_DIRS)
    if not args.skip_skin:
        plugin_version = addon_version(ROOT / "plugin.image.mypicsdb3")
        skin_dir = prepare_skin(
            plugin_version=plugin_version,
            source_dir=args.estuary_source,
            output_dir=DEFAULT_OUTPUT,
            force_download=args.force_estuary_download,
        )
        addon_dirs.append(skin_dir)

    verify(addon_dirs)
    project_version = addon_version(ROOT / "plugin.image.mypicsdb3")

    if DIST.exists():
        shutil.rmtree(DIST)
    DIST.mkdir()
    repo_root = DIST / "repository"
    repo_root.mkdir()

    for addon_dir in addon_dirs:
        version = addon_version(addon_dir)
        zip_path = DIST / ("%s-%s.zip" % (addon_dir.name, version))
        zip_addon(addon_dir, zip_path)
        copy_repository_entry(addon_dir, zip_path, repo_root)
    build_addons_xml(repo_root, addon_dirs)
    build_source_archives(project_version)
    write_checksums()

    print("Built:")
    for path in sorted(DIST.glob("*")):
        if path.is_file():
            print(" -", path.relative_to(ROOT))
    print(" -", repo_root.relative_to(ROOT))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
