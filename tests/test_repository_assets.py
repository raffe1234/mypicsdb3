from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def load_build_module():
    path = ROOT / "tools" / "build.py"
    spec = importlib.util.spec_from_file_location("mypicsdb3_build", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
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
