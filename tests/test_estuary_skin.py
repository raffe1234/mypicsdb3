from __future__ import annotations

import json
import sys
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

from estuary_skin import (  # noqa: E402
    EstuaryConfig,
    EstuaryProjectConfig,
    extract_skin_from_archive,
    patch_skin,
)


def config() -> EstuaryConfig:
    return EstuaryConfig(
        channel="omega",
        kodi_branch="omega",
        kodi_major=21,
        codename="Omega",
        minversion="21.0.0",
        maxversion="21.99.99",
        ref="21.3-Omega",
        archive_url="https://example.invalid/xbmc.zip",
        source_addon_id="skin.estuary",
        target_addon_id="skin.estuary.mypicsdb3",
        target_name="Estuary MyPicsDB 3",
        skin_version="21.3.4",
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
    (path / "xml" / "MyPics.xml").write_text(
        """<window>
  <controls>
    <control type="grouplist" id="9000">
      <control type="button" id="624">
        <label>10140</label>
      </control>
      <control type="button" id="621">
        <label>21452</label>
      </control>
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
    patch_skin(source, output, config(), "0.2.7")

    root = ET.parse(output / "addon.xml").getroot()
    assert root.attrib["id"] == "skin.estuary.mypicsdb3"
    assert root.attrib["name"] == "Estuary MyPicsDB 3"
    assert root.attrib["version"] == "21.3.4"
    dependencies = {
        node.attrib["addon"]: node.attrib.get("version")
        for node in root.findall("./requires/import")
    }
    assert dependencies["xbmc.gui"] == "5.17.0"
    assert dependencies["plugin.image.mypicsdb3"] == "0.2.7"

    home = (output / "xml" / "Home.xml").read_text(encoding="utf-8")
    assert "plugin://plugin.image.mypicsdb3/recent-taken?limit=15" in home
    assert 'id="17000"' in home
    pictures = (output / "xml" / "MyPics.xml").read_text(encoding="utf-8")
    assert "$ADDON[plugin.image.mypicsdb3 32215]" in pictures
    assert "plugin://plugin.image.mypicsdb3/action/save-album-view" in pictures
    assert pictures.index('id="625"') < pictures.index('id="624"')
    assert (output / "xml" / "Other.xml").is_file()
    notice = (output / "MYPICSDB3_UPSTREAM.md").read_text(encoding="utf-8")
    assert "Kodi channel: omega" in notice
    assert "21.3-Omega" in notice


def test_patch_skin_fails_closed_when_upstream_boundaries_change(tmp_path: Path):
    source = create_estuary_fixture(tmp_path / "skin.estuary")
    (source / "xml" / "Home.xml").write_text(
        '<window><control type="group" id="4000" /></window>\n',
        encoding="utf-8",
    )
    output = tmp_path / "skin.estuary.mypicsdb3"

    try:
        patch_skin(source, output, config(), "0.2.7")
    except RuntimeError as exc:
        assert "control ids 4000 and 17000" in str(exc)
    else:
        raise AssertionError("Changed upstream Home.xml should stop the build")


def test_patch_skin_fails_closed_when_picture_sideblade_changes(tmp_path: Path):
    source = create_estuary_fixture(tmp_path / "skin.estuary")
    (source / "xml" / "MyPics.xml").write_text(
        '<window><control type="button" id="999" /></window>\n',
        encoding="utf-8",
    )
    output = tmp_path / "skin.estuary.mypicsdb3"

    try:
        patch_skin(source, output, config(), "0.2.10")
    except RuntimeError as exc:
        assert "button id 624" in str(exc)
    else:
        raise AssertionError("Changed upstream MyPics.xml should stop the build")


def test_extract_skin_from_official_archive_layout(tmp_path: Path):
    archive_path = tmp_path / "xbmc.zip"
    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.writestr(
            "xbmc-21.3-Omega/addons/skin.estuary/addon.xml",
            "<addon />",
        )
        archive.writestr(
            "xbmc-21.3-Omega/addons/skin.estuary/xml/Home.xml",
            "<window />",
        )
        archive.writestr(
            "xbmc-21.3-Omega/addons/skin.estuary/xml/MyPics.xml",
            "<window />",
        )
        archive.writestr(
            "xbmc-21.3-Omega/addons/other.addon/addon.xml",
            "<addon />",
        )
    output = tmp_path / "skin.estuary"
    extract_skin_from_archive(archive_path, output, "skin.estuary")
    assert (output / "addon.xml").read_text(encoding="utf-8") == "<addon />"
    assert (output / "xml" / "Home.xml").is_file()
    assert (output / "xml" / "MyPics.xml").is_file()
    assert not (output / "other.addon").exists()


def test_upstream_config_has_versioned_channels_and_history():
    project = EstuaryProjectConfig.load()
    assert project.target_addon_id == "skin.estuary.mypicsdb3"
    assert project.retain_versions == 5
    assert set(project.channels) == {"omega", "piers"}
    assert project.channels["omega"].releases[0].ref == "21.3-Omega"
    assert project.channels["omega"].patch_revision == 4
    assert project.channels["omega"].releases[0].skin_version == "21.3.4"
    assert project.channels["piers"].patch_revision == 2
    assert project.channels["piers"].releases[0].ref == "22.0b1-Piers"
    assert all(
        len(channel.releases) <= project.retain_versions
        for channel in project.channels.values()
    )


def test_upstream_config_is_valid_json():
    data = json.loads(
        (ROOT / "contrib" / "estuary" / "upstream.json").read_text(
            encoding="utf-8"
        )
    )
    assert data["channels"]["omega"]["minversion"] == "21.0.0"
    assert data["channels"]["omega"]["maxversion"] == "21.89.999"
    assert data["channels"]["piers"]["minversion"] == "21.90.0"
    assert data["channels"]["piers"]["kodi_major"] == 22
