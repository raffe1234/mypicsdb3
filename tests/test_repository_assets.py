from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def load_build_module():
    path = ROOT / "tools" / "build.py"
    spec = importlib.util.spec_from_file_location("mypicsdb3_build", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_repository_preserves_declared_asset_paths(tmp_path: Path):
    build = load_build_module()
    addon = tmp_path / "skin.estuary.mypicsdb3"
    screenshots = addon / "resources" / "screenshots"
    screenshots.mkdir(parents=True)
    (addon / "resources" / "icon.png").write_bytes(b"icon")
    (addon / "resources" / "fanart.jpg").write_bytes(b"fanart")
    (screenshots / "screenshot-01.jpg").write_bytes(b"screen")
    (addon / "addon.xml").write_text(
        """<?xml version="1.0" encoding="UTF-8"?>
<addon id="skin.estuary.mypicsdb3" name="Test" version="1.0.0">
  <extension point="xbmc.addon.metadata">
    <assets>
      <icon>resources/icon.png</icon>
      <fanart>resources/fanart.jpg</fanart>
      <screenshot>resources/screenshots/screenshot-01.jpg</screenshot>
    </assets>
  </extension>
</addon>
""",
        encoding="utf-8",
    )
    zip_path = tmp_path / "skin.estuary.mypicsdb3-1.0.0.zip"
    zip_path.write_bytes(b"zip")
    repository = tmp_path / "repository"
    build.copy_repository_entry(addon, zip_path, repository)
    target = repository / addon.name
    assert (target / "resources" / "icon.png").read_bytes() == b"icon"
    assert (target / "resources" / "fanart.jpg").read_bytes() == b"fanart"
    assert (target / "resources" / "screenshots" / "screenshot-01.jpg").read_bytes() == b"screen"


def test_repository_history_keeps_newest_and_preserves_previous_archives(tmp_path: Path):
    build = load_build_module()
    addon_id = "skin.estuary.mypicsdb3"
    previous = tmp_path / "previous"
    previous_addon = previous / addon_id
    previous_addon.mkdir(parents=True)
    previous_entries = []
    for version in ["21.2.3", "21.1.3", "21.0.3"]:
        filename = "%s-%s.zip" % (addon_id, version)
        (previous_addon / filename).write_bytes(version.encode("ascii"))
        (previous_addon / (filename + ".sha256")).write_text(
            "hash-%s\n" % version,
            encoding="ascii",
        )
        previous_entries.append(
            {
                "version": version,
                "filename": filename,
                "source_ref": version.rsplit(".", 1)[0] + "-Omega",
            }
        )
    import json

    (previous_addon / "history.json").write_text(
        json.dumps({"versions": previous_entries}),
        encoding="utf-8",
    )

    current = tmp_path / "current"
    current_addon = current / addon_id
    current_addon.mkdir(parents=True)
    newest_filename = "%s-21.3.4.zip" % addon_id
    (current_addon / newest_filename).write_bytes(b"new")
    (current_addon / (newest_filename + ".sha256")).write_text(
        "new-hash\n",
        encoding="ascii",
    )

    history = build.preserve_previous_skin_archives(
        previous_repo_root=previous,
        repo_root=current,
        addon_id=addon_id,
        current_entries=[
            {
                "version": "21.3.4",
                "filename": newest_filename,
                "source_ref": "21.3-Omega",
            }
        ],
        retain_versions=3,
    )

    assert [entry["version"] for entry in history] == [
        "21.3.4",
        "21.2.3",
        "21.1.3",
    ]
    assert (current_addon / (addon_id + "-21.2.3.zip")).is_file()
    assert not (current_addon / (addon_id + "-21.0.3.zip")).exists()


def load_verify_module():
    path = ROOT / "tools" / "verify.py"
    spec = importlib.util.spec_from_file_location("mypicsdb3_verify", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_repository_manifest_channels_match_upstream_config():
    verify = load_verify_module()
    addon = ROOT / "repository.mypicsdb3"
    root = verify.ET.parse(addon / "addon.xml").getroot()
    verify.verify_repository_manifest(addon, root)


def create_repository_addon(path: Path, version: str = "0.2.26") -> Path:
    path.mkdir(parents=True)
    (path / "addon.xml").write_text(
        '<addon id="repository.mypicsdb3" version="%s" />\n' % version,
        encoding="utf-8",
    )
    (path / "payload.txt").write_text("stable\n", encoding="utf-8")
    return path


def test_reuses_unchanged_repository_archive(tmp_path: Path):
    build = load_build_module()
    addon = create_repository_addon(tmp_path / "repository.mypicsdb3")
    previous_root = tmp_path / "previous"
    previous_archive = (
        previous_root
        / "omega"
        / addon.name
        / "repository.mypicsdb3-0.2.26.zip"
    )
    build.zip_addon(addon, previous_archive)

    found = build.find_previous_addon_archive(
        previous_root, addon, ["omega", "piers"]
    )

    assert found == previous_archive
    output = build.prepare_static_package(
        addon, tmp_path / "packages", previous_root, ["omega"]
    )
    assert output.read_bytes() == previous_archive.read_bytes()


def test_rejects_repository_changes_without_version_bump(tmp_path: Path):
    build = load_build_module()
    addon = create_repository_addon(tmp_path / "repository.mypicsdb3")
    previous_root = tmp_path / "previous"
    previous_archive = (
        previous_root
        / "omega"
        / addon.name
        / "repository.mypicsdb3-0.2.26.zip"
    )
    build.zip_addon(addon, previous_archive)
    (addon / "payload.txt").write_text("changed\n", encoding="utf-8")

    with pytest.raises(RuntimeError, match="changed without a version bump"):
        build.find_previous_addon_archive(previous_root, addon, ["omega"])


def test_unchanged_repository_is_not_a_plugin_release_asset(tmp_path: Path):
    build = load_build_module()
    repository = create_repository_addon(tmp_path / "repository.mypicsdb3")
    plugin = tmp_path / "plugin.image.mypicsdb3"
    plugin.mkdir()
    (plugin / "addon.xml").write_text(
        '<addon id="plugin.image.mypicsdb3" version="0.2.27" />\n',
        encoding="utf-8",
    )

    assert not build.publish_standalone_static_package(repository, "0.2.27")
    assert build.publish_standalone_static_package(plugin, "0.2.27")
