from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

from update_estuary_upstreams import (  # noqa: E402
    parse_tag,
    skin_version_for_tag,
    update_config_data,
)


def release(tag: str, prerelease: bool = False, draft: bool = False) -> dict[str, object]:
    return {
        "tag_name": tag,
        "prerelease": prerelease,
        "draft": draft,
    }


def config_data() -> dict[str, object]:
    return {
        "retain_versions": 3,
        "channels": {
            "omega": {
                "kodi_major": 21,
                "codename": "Omega",
                "include_prereleases": False,
                "patch_revision": 3,
                "releases": [],
            },
            "piers": {
                "kodi_major": 22,
                "codename": "Piers",
                "include_prereleases": True,
                "patch_revision": 1,
                "releases": [],
            },
        },
    }


def test_parse_and_skin_versions():
    assert parse_tag("22.0b1-Piers")["stage"] == "b"
    assert parse_tag("v22.0b1-Piers")["major"] == 22
    assert skin_version_for_tag("21.3-Omega", 3) == "21.3.3"
    assert skin_version_for_tag("22.0a3-Piers", 1) == "22.0.0~alpha3.1"
    assert skin_version_for_tag("22.0b1-Piers", 1) == "22.0.0~beta1.1"
    assert skin_version_for_tag("22.0rc2-Piers", 1) == "22.0.0~rc2.1"


def test_update_selects_latest_five_by_channel_and_ignores_drafts():
    data = config_data()
    releases = [
        release("22.0b2-Piers", prerelease=True),
        release("22.0b1-Piers", prerelease=True),
        release("22.0a3-Piers", prerelease=True),
        release("22.0a2-Piers", prerelease=True),
        release("21.4-Omega", draft=True),
        release("21.3-Omega"),
        release("21.2-Omega"),
        release("21.1-Omega"),
        release("21.0rc2-Omega", prerelease=True),
    ]

    assert update_config_data(data, releases)
    channels = data["channels"]
    assert [item["ref"] for item in channels["omega"]["releases"]] == [
        "21.3-Omega",
        "21.2-Omega",
        "21.1-Omega",
    ]
    assert [item["ref"] for item in channels["piers"]["releases"]] == [
        "22.0b2-Piers",
        "22.0b1-Piers",
        "22.0a3-Piers",
    ]

    unchanged = copy.deepcopy(data)
    assert not update_config_data(unchanged, releases)


def test_saved_release_response_can_be_serialized(tmp_path: Path):
    payload = [release("21.3-Omega"), release("22.0b1-Piers", prerelease=True)]
    path = tmp_path / "releases.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    assert json.loads(path.read_text(encoding="utf-8"))[0]["tag_name"] == "21.3-Omega"
