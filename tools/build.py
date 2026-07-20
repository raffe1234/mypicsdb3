#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import tarfile
import xml.etree.ElementTree as ET
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Sequence

ROOT = Path(__file__).resolve().parents[1]
DIST = ROOT / "dist"
BUILD = ROOT / "build"
PACKAGES = BUILD / "packages"
STATIC_ADDON_DIRS = [ROOT / "plugin.image.mypicsdb3", ROOT / "repository.mypicsdb3"]
EXCLUDED_PARTS = {
    ".git",
    "dist",
    "build",
    ".cache",
    "__pycache__",
    ".pytest_cache",
    ".venv",
    "venv",
    "htmlcov",
}
EXCLUDED_NAMES = {".coverage", "kodi-addon-checker.log"}


@dataclass(frozen=True)
class SkinBuild:
    channel: str
    addon_dir: Path
    version: str
    source_ref: str
    is_latest: bool


def addon_version(addon_dir: Path) -> str:
    return ET.parse(addon_dir / "addon.xml").getroot().attrib["version"]


def zip_addon(addon_dir: Path, output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(
        output,
        "w",
        compression=zipfile.ZIP_DEFLATED,
        compresslevel=9,
    ) as archive:
        for path in sorted(addon_dir.rglob("*")):
            if not path.is_file() or "__pycache__" in path.parts or path.suffix == ".pyc":
                continue
            arcname = Path(addon_dir.name) / path.relative_to(addon_dir)
            info = zipfile.ZipInfo.from_file(path, arcname.as_posix())
            info.external_attr = 0o100644 << 16
            with path.open("rb") as source:
                archive.writestr(
                    info,
                    source.read(),
                    compress_type=zipfile.ZIP_DEFLATED,
                    compresslevel=9,
                )


def addon_asset_paths(addon_dir: Path) -> list[tuple[Path, Path]]:
    """Return every declared metadata asset and its repository-relative path."""
    root = ET.parse(addon_dir / "addon.xml").getroot()
    metadata = next(
        (
            extension
            for extension in root.findall("extension")
            if extension.attrib.get("point") == "xbmc.addon.metadata"
        ),
        None,
    )
    assets = metadata.find("assets") if metadata is not None else None
    if assets is None:
        raise RuntimeError("Missing metadata assets in %s" % addon_dir.name)

    result: list[tuple[Path, Path]] = []
    for asset in assets:
        value = (asset.text or "").strip()
        if not value:
            continue
        relative = Path(value)
        if relative.is_absolute() or ".." in relative.parts:
            raise RuntimeError(
                "Unsafe metadata asset path in %s: %s" % (addon_dir.name, value)
            )
        source = addon_dir / relative
        if not source.is_file():
            raise RuntimeError(
                "Declared metadata asset is missing in %s: %s"
                % (addon_dir.name, value)
            )
        result.append((source, relative))

    if not result:
        raise RuntimeError("No metadata assets declared in %s" % addon_dir.name)
    return result


def write_zip_hash(zip_path: Path, target_dir: Path) -> None:
    digest = hashlib.sha256(zip_path.read_bytes()).hexdigest()
    (target_dir / (zip_path.name + ".sha256")).write_text(
        digest + "\n",
        encoding="ascii",
    )


def copy_repository_archive(zip_path: Path, addon_id: str, repo_root: Path) -> None:
    target = repo_root / addon_id
    target.mkdir(parents=True, exist_ok=True)
    shutil.copy2(zip_path, target / zip_path.name)
    write_zip_hash(zip_path, target)


def copy_repository_entry(addon_dir: Path, zip_path: Path, repo_root: Path) -> None:
    target = repo_root / addon_dir.name
    target.mkdir(parents=True, exist_ok=True)
    copy_repository_archive(zip_path, addon_dir.name, repo_root)
    shutil.copy2(addon_dir / "addon.xml", target / "addon.xml")

    # Preserve resources/icon.png, resources/fanart.jpg and screenshots instead
    # of flattening them and causing 404 responses in Kodi.
    for source, relative in addon_asset_paths(addon_dir):
        destination = target / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)


def build_addons_xml(repo_root: Path, addon_dirs: Sequence[Path]) -> None:
    root = ET.Element("addons")
    for addon_dir in addon_dirs:
        root.append(ET.parse(addon_dir / "addon.xml").getroot())
    ET.indent(root, space="  ")
    payload = ET.tostring(root, encoding="utf-8", xml_declaration=True)
    addons_xml = repo_root / "addons.xml"
    addons_xml.write_bytes(payload + b"\n")
    (repo_root / "addons.xml.md5").write_text(
        hashlib.md5(addons_xml.read_bytes()).hexdigest() + "\n",
        encoding="ascii",
    )


def source_files() -> Iterable[Path]:
    for path in sorted(ROOT.rglob("*")):
        if not path.is_file():
            continue
        relative = path.relative_to(ROOT)
        if path.name in EXCLUDED_NAMES or any(
            part in EXCLUDED_PARTS for part in relative.parts
        ):
            continue
        yield path


def build_source_archives(version: str) -> None:
    prefix = Path("mypicsdb3-%s" % version)
    tar_output = DIST / ("mypicsdb3-%s.tar.gz" % version)
    with tarfile.open(tar_output, "w:gz", compresslevel=9) as archive:
        for path in source_files():
            archive.add(
                path,
                arcname=prefix / path.relative_to(ROOT),
                recursive=False,
            )

    zip_output = DIST / ("mypicsdb3-%s-source.zip" % version)
    with zipfile.ZipFile(
        zip_output,
        "w",
        compression=zipfile.ZIP_DEFLATED,
        compresslevel=9,
    ) as archive:
        for path in source_files():
            arcname = prefix / path.relative_to(ROOT)
            info = zipfile.ZipInfo.from_file(path, arcname.as_posix())
            info.external_attr = 0o100644 << 16
            archive.writestr(
                info,
                path.read_bytes(),
                compress_type=zipfile.ZIP_DEFLATED,
                compresslevel=9,
            )


def write_checksums() -> None:
    entries = []
    for path in sorted(DIST.glob("*")):
        if path.is_file() and path.name != "SHA256SUMS.txt":
            entries.append(
                "%s  %s"
                % (hashlib.sha256(path.read_bytes()).hexdigest(), path.name)
            )
    (DIST / "SHA256SUMS.txt").write_text(
        "\n".join(entries) + "\n",
        encoding="ascii",
    )


def package(addon_dir: Path, package_dir: Path) -> Path:
    version = addon_version(addon_dir)
    output = package_dir / ("%s-%s.zip" % (addon_dir.name, version))
    zip_addon(addon_dir, output)
    return output


def build_skin_packages(
    selected_channels: Sequence[str],
    history_limit: int,
    plugin_version: str,
    estuary_source: Path | None,
    force_download: bool,
) -> list[SkinBuild]:
    from estuary_skin import EstuaryProjectConfig, prepare_skin

    project = EstuaryProjectConfig.load()
    result: list[SkinBuild] = []
    for channel_name in selected_channels:
        channel = project.channels[channel_name]
        release_count = min(
            max(1, history_limit),
            project.retain_versions,
            len(channel.releases),
        )
        for release_index in range(release_count):
            config = project.release_config(channel_name, release_index)
            output_dir = (
                BUILD
                / "estuary"
                / channel_name
                / config.skin_version
                / config.target_addon_id
            )
            source = estuary_source if release_index == 0 else None
            addon_dir = prepare_skin(
                plugin_version=plugin_version,
                source_dir=source,
                output_dir=output_dir,
                force_download=force_download,
                config=config,
            )
            result.append(
                SkinBuild(
                    channel=channel_name,
                    addon_dir=addon_dir,
                    version=config.skin_version,
                    source_ref=config.ref,
                    is_latest=release_index == 0,
                )
            )
    return result


def read_previous_history(previous_repo_root: Path | None, addon_id: str) -> list[dict[str, str]]:
    if previous_repo_root is None:
        return []
    history_path = previous_repo_root / addon_id / "history.json"
    if not history_path.is_file():
        return []
    data = json.loads(history_path.read_text(encoding="utf-8"))
    entries = data.get("versions", []) if isinstance(data, dict) else []
    return [
        {
            "version": str(item["version"]),
            "filename": str(item["filename"]),
            "source_ref": str(item.get("source_ref", "unknown")),
        }
        for item in entries
        if isinstance(item, dict)
        and item.get("version")
        and item.get("filename")
    ]


def preserve_previous_skin_archives(
    previous_repo_root: Path | None,
    repo_root: Path,
    addon_id: str,
    current_entries: list[dict[str, str]],
    retain_versions: int,
) -> list[dict[str, str]]:
    history = list(current_entries)
    seen = {entry["version"] for entry in history}
    previous_entries = read_previous_history(previous_repo_root, addon_id)
    previous_addon_dir = (
        previous_repo_root / addon_id if previous_repo_root is not None else None
    )
    target = repo_root / addon_id

    for entry in previous_entries:
        if len(history) >= retain_versions:
            break
        if entry["version"] in seen or previous_addon_dir is None:
            continue
        filename = entry["filename"]
        source_zip = previous_addon_dir / filename
        source_hash = previous_addon_dir / (filename + ".sha256")
        if not source_zip.is_file() or not source_hash.is_file():
            continue
        shutil.copy2(source_zip, target / filename)
        shutil.copy2(source_hash, target / source_hash.name)
        history.append(entry)
        seen.add(entry["version"])

    (target / "history.json").write_text(
        json.dumps({"versions": history[:retain_versions]}, indent=2) + "\n",
        encoding="utf-8",
    )
    return history[:retain_versions]


def build_repository_tree(
    repo_root: Path,
    static_packages: dict[Path, Path],
    skins: Sequence[SkinBuild],
    retain_versions: int,
    previous_repo_root: Path | None = None,
) -> None:
    repo_root.mkdir(parents=True, exist_ok=True)
    latest_skin = next((skin for skin in skins if skin.is_latest), None)
    if latest_skin is None:
        raise RuntimeError("A repository channel must contain a latest Estuary skin")

    indexed_addons = list(STATIC_ADDON_DIRS) + [latest_skin.addon_dir]
    for addon_dir, zip_path in static_packages.items():
        copy_repository_entry(addon_dir, zip_path, repo_root)

    current_entries: list[dict[str, str]] = []
    for skin in skins:
        zip_path = package(skin.addon_dir, PACKAGES / skin.channel)
        if skin.is_latest:
            copy_repository_entry(skin.addon_dir, zip_path, repo_root)
        else:
            # Older versions are retained as installable archives but deliberately
            # omitted from addons.xml; Kodi should only auto-select the latest one.
            copy_repository_archive(zip_path, skin.addon_dir.name, repo_root)
        current_entries.append(
            {
                "version": skin.version,
                "filename": zip_path.name,
                "source_ref": skin.source_ref,
            }
        )

    preserve_previous_skin_archives(
        previous_repo_root=previous_repo_root,
        repo_root=repo_root,
        addon_id=latest_skin.addon_dir.name,
        current_entries=current_entries,
        retain_versions=retain_versions,
    )
    build_addons_xml(repo_root, indexed_addons)


def parse_args() -> argparse.Namespace:
    from estuary_skin import EstuaryProjectConfig

    project = EstuaryProjectConfig.load()
    parser = argparse.ArgumentParser(
        description="Build MyPicsDB 3 Kodi packages and repository metadata"
    )
    parser.add_argument(
        "--skip-skin",
        action="store_true",
        help="Build only the plug-in and repository add-ons",
    )
    parser.add_argument(
        "--channel",
        action="append",
        choices=tuple(project.channels),
        help="Build only this Estuary channel; repeat for multiple channels",
    )
    parser.add_argument(
        "--history-limit",
        type=int,
        default=1,
        help="Retain this many patched Estuary versions per channel (default: 1)",
    )
    parser.add_argument(
        "--estuary-source",
        type=Path,
        help="Use a local skin.estuary source for one channel and its latest release",
    )
    parser.add_argument("--force-estuary-download", action="store_true")
    parser.add_argument(
        "--previous-repository",
        type=Path,
        help="Merge retained skin archives from a previous dist/repository tree",
    )
    args = parser.parse_args()
    if args.history_limit < 1:
        parser.error("--history-limit must be at least 1")
    if args.estuary_source and (len(args.channel or []) != 1 or args.history_limit != 1):
        parser.error(
            "--estuary-source requires exactly one --channel and --history-limit 1"
        )
    return args


def main() -> int:
    from estuary_skin import EstuaryProjectConfig
    from verify import main as verify

    args = parse_args()
    project = EstuaryProjectConfig.load()
    selected_channels = args.channel or list(project.channels)
    project_version = addon_version(ROOT / "plugin.image.mypicsdb3")

    if BUILD.exists():
        shutil.rmtree(BUILD)
    BUILD.mkdir()

    skin_builds: list[SkinBuild] = []
    if not args.skip_skin:
        skin_builds = build_skin_packages(
            selected_channels=selected_channels,
            history_limit=args.history_limit,
            plugin_version=project_version,
            estuary_source=args.estuary_source,
            force_download=args.force_estuary_download,
        )

    verify([skin.addon_dir for skin in skin_builds])

    if DIST.exists():
        shutil.rmtree(DIST)
    DIST.mkdir()
    PACKAGES.mkdir(parents=True, exist_ok=True)

    static_packages: dict[Path, Path] = {}
    for addon_dir in STATIC_ADDON_DIRS:
        zip_path = package(addon_dir, PACKAGES / "static")
        static_packages[addon_dir] = zip_path
        shutil.copy2(zip_path, DIST / zip_path.name)

    if args.skip_skin:
        legacy_root = DIST / "repository"
        legacy_root.mkdir()
        for addon_dir, zip_path in static_packages.items():
            copy_repository_entry(addon_dir, zip_path, legacy_root)
        build_addons_xml(legacy_root, STATIC_ADDON_DIRS)
    else:
        for channel_name in selected_channels:
            channel_skins = [
                skin for skin in skin_builds if skin.channel == channel_name
            ]
            build_repository_tree(
                DIST / "repository" / channel_name,
                static_packages,
                channel_skins,
                retain_versions=project.retain_versions,
                previous_repo_root=(
                    args.previous_repository / channel_name
                    if args.previous_repository
                    else None
                ),
            )
            latest = next(skin for skin in channel_skins if skin.is_latest)
            latest_zip = package(latest.addon_dir, PACKAGES / channel_name)
            shutil.copy2(latest_zip, DIST / latest_zip.name)

        # Keep the old repository URL alive. Existing repository.mypicsdb3 0.2.6
        # installations read this index once and can then update to the new
        # multi-directory repository add-on.
        legacy_channel = "omega" if "omega" in selected_channels else selected_channels[0]
        legacy_skins = [skin for skin in skin_builds if skin.channel == legacy_channel]
        build_repository_tree(
            DIST / "repository",
            static_packages,
            legacy_skins,
            retain_versions=1,
            previous_repo_root=None,
        )

    build_source_archives(project_version)
    write_checksums()

    print("Built:")
    for path in sorted(DIST.glob("*")):
        if path.is_file():
            print(" -", path.relative_to(ROOT))
    print(" -", (DIST / "repository").relative_to(ROOT))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
