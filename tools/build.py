#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import shutil
import tarfile
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path
from typing import Iterable

ROOT = Path(__file__).resolve().parents[1]
DIST = ROOT / "dist"
ADDON_DIRS = [ROOT / "plugin.image.mypicsdb3", ROOT / "repository.mypicsdb3"]
EXCLUDED_PARTS = {".git", "dist", "__pycache__", ".pytest_cache", ".venv", "venv", "htmlcov"}
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


def copy_repository_entry(addon_dir: Path, zip_path: Path, repo_root: Path) -> None:
    target = repo_root / addon_dir.name
    target.mkdir(parents=True, exist_ok=True)
    shutil.copy2(zip_path, target / zip_path.name)
    for filename in ("addon.xml", "icon.png", "fanart.jpg"):
        shutil.copy2(addon_dir / filename, target / filename)
    digest = hashlib.sha256(zip_path.read_bytes()).hexdigest()
    (target / (zip_path.name + ".sha256")).write_text(digest + "\n", encoding="ascii")


def build_addons_xml(repo_root: Path) -> None:
    root = ET.Element("addons")
    for addon_dir in ADDON_DIRS:
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


def main() -> int:
    from verify import main as verify

    verify()
    versions = {addon_version(addon_dir) for addon_dir in ADDON_DIRS}
    if len(versions) != 1:
        raise SystemExit("ERROR: Add-on versions do not match: %s" % sorted(versions))
    version = versions.pop()

    if DIST.exists():
        shutil.rmtree(DIST)
    DIST.mkdir()
    repo_root = DIST / "repository"
    repo_root.mkdir()

    for addon_dir in ADDON_DIRS:
        zip_path = DIST / ("%s-%s.zip" % (addon_dir.name, version))
        zip_addon(addon_dir, zip_path)
        copy_repository_entry(addon_dir, zip_path, repo_root)
    build_addons_xml(repo_root)
    build_source_archives(version)
    write_checksums()

    print("Built:")
    for path in sorted(DIST.glob("*")):
        if path.is_file():
            print(" -", path.relative_to(ROOT))
    print(" -", repo_root.relative_to(ROOT))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
