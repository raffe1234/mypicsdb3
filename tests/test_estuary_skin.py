from __future__ import annotations

import json
import sys
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

from estuary_skin import EstuaryConfig, extract_skin_from_archive, patch_skin  # noqa: E402


def config() -> EstuaryConfig:
    return EstuaryConfig(
        kodi_branch="omega",
        ref="21.3-Omega",
        archive_url="https://example.invalid/xbmc.zip",
        source_addon_id="skin.estuary",
        target_addon_id="skin.estuary.mypicsdb3",
        target_name="Estuary MyPicsDB 3",
        skin_version="21.3.1",
        project_url="https://github.com/raffe1234/mypicsdb3",
    )


def create_estuary_fixture(path: Path) -> Path:
    (path / "xml").mkdir(parents=True)
    (path / "resources").mkdir()
    (path / "addon.xml").write_text(
        """<?xml version="1.0" encoding="UTF-8"?>
<addon id="skin.estuary" name="Estuary" version="4.0.0" provider-name="Kodi">
  <requires><import addon="xbmc.gui" version="5.17.0" /></requires>
  <extension point="xbmc.gui.skin" debugging="false"><res width="1920" height="1080" aspect="16:9" default="true" folder="xml" /></extension>
  <extension point="xbmc.addon.metadata">
    <summary lang="en_GB">Estuary</summary>
    <description lang="en_GB">Default skin</description>
    <platform>all</platform><license>CC-BY-SA-4.0</license>
    <assets><icon>resources/icon.png</icon><fanart>resources/fanart.jpg</fanart></assets>
  </extension>
</addon>
""",
        encoding="utf-8",
    )
    (path / "xml" / "Home.xml").write_text(
        """<window>
  <controls>
    <control type="group" id="4000">
      <visible>pictures</visible>
    </control>
    <control type="group" id="17000">
      <visible>games</visible>
    </control>
  </controls>
</window>
""",
        encoding="utf-8",
    )
    (path / "xml" / "Other.xml").write_text("<window />\n", encoding="utf-8")
    return path


def test_patch_skin_creates_separate_addon_and_widgets(tmp_path: Path):
    source = create_estuary_fixture(tmp_path / "skin.estuary")
    output = tmp_path / "skin.estuary.mypicsdb3"
    patch_skin(source, output, config(), "0.2.0")

    root = ET.parse(output / "addon.xml").getroot()
    assert root.attrib["id"] == "skin.estuary.mypicsdb3"
    assert root.attrib["name"] == "Estuary MyPicsDB 3"
    assert root.attrib["version"] == "21.3.1"
    dependencies = {node.attrib["addon"]: node.attrib.get("version") for node in root.findall("./requires/import")}
    assert dependencies["xbmc.gui"] == "5.17.0"
    assert dependencies["plugin.image.mypicsdb3"] == "0.2.0"

    home = (output / "xml" / "Home.xml").read_text(encoding="utf-8")
    assert "plugin://plugin.image.mypicsdb3/recent-taken?limit=15" in home
    assert 'id="17000"' in home
    assert (output / "xml" / "Other.xml").is_file()
    assert (output / "MYPICSDB3_UPSTREAM.md").is_file()


def test_extract_skin_from_official_archive_layout(tmp_path: Path):
    archive_path = tmp_path / "xbmc.zip"
    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.writestr("xbmc-21.3-Omega/addons/skin.estuary/addon.xml", "<addon />")
        archive.writestr("xbmc-21.3-Omega/addons/skin.estuary/xml/Home.xml", "<window />")
        archive.writestr("xbmc-21.3-Omega/addons/other.addon/addon.xml", "<addon />")
    output = tmp_path / "skin.estuary"
    extract_skin_from_archive(archive_path, output, "skin.estuary")
    assert (output / "addon.xml").read_text(encoding="utf-8") == "<addon />"
    assert (output / "xml" / "Home.xml").is_file()
    assert not (output / "other.addon").exists()


def test_upstream_config_is_complete():
    data = json.loads((ROOT / "contrib" / "estuary" / "upstream.json").read_text(encoding="utf-8"))
    assert data["ref"] == "21.3-Omega"
    assert data["target_addon_id"] == "skin.estuary.mypicsdb3"
    assert data["skin_version"].startswith("21.3.")
