from __future__ import annotations

import json
import zipfile
from datetime import datetime, timezone
from types import SimpleNamespace

from mypicsdb3.diagnostics import collect_diagnostics, write_support_bundle


class Catalog:
    def overview(self):
        return {
            "backend": "mysql",
            "pictures": 120,
            "videos": 5,
            "missing": 2,
            "folders": 18,
            "sources": 4,
            "enabled_sources": 3,
        }

    def latest_scan(self):
        return {
            "started_at": "2026-08-07 08:00:00.000000",
            "finished_at": "2026-08-07 08:03:30.000000",
            "status": "completed",
        }


class Kodi:
    def __init__(self, profile_path="/private/profile"):
        self.profile_path = profile_path
        self.settings = SimpleNamespace(
            home_widget_limit=20,
            random_home_refresh_hours=6,
            include_videos=True,
            debug_logging=True,
            mysql_host="private-db.example",
            mysql_username="secret-user",
            mysql_password="secret-password",
            profile_path="/private/profile",
        )

    def installed_addon_version(self, addon_id):
        return {
            "screensaver.mypicsdb3": "0.7.0",
            "repository.mypicsdb3": "0.2.26",
            "skin.estuary.mypicsdb3": "21.3.16",
        }.get(addon_id, "")

    def current_skin_id(self):
        return "skin.estuary.mypicsdb3"

    def scan_status(self):
        return {
            "token": "scan-1",
            "kind": "manual",
            "state": "running",
            "pictures_seen": 25,
            "started_at": 1000.0,
            "source": "Private source",
            "path": "smb://secret-user:secret-password@server/private/photo.jpg",
        }

    def home_widget_generations(self):
        return {"content": 42, "random": 9}

    def picture_playlist_compatibility(self):
        return False

    def music_slideshow_session(self):
        return {
            "token": "private-music-session-token",
            "playlist_fingerprint": "private-playlist-fingerprint",
        }


def test_collect_diagnostics_excludes_private_connection_and_source_details():
    runtime = SimpleNamespace(catalog=Catalog(), kodi=Kodi())

    snapshot = collect_diagnostics(runtime, now=1125.0)

    assert snapshot["backend"] == "mysql"
    assert snapshot["schema_version"] == 7
    assert snapshot["query_model_version"] == 1
    assert snapshot["screensaver_version"] == "0.7.0"
    assert snapshot["skin"] == {
        "id": "skin.estuary.mypicsdb3",
        "version": "21.3.16",
    }
    assert snapshot["active_scan"] == {
        "kind": "manual",
        "state": "running",
        "pictures_seen": 25,
        "elapsed_seconds": 125.0,
    }
    assert snapshot["last_scan"]["duration_seconds"] == 210.0
    assert snapshot["home_generations"] == {"content": 42, "random": 9}
    assert snapshot["picture_playlist_compatibility"] == "incompatible"
    assert snapshot["music_slideshow_session"] == {
        "active": True,
        "playlist_fingerprint_present": True,
    }

    rendered = repr(snapshot)
    assert "private-db.example" not in rendered
    assert "secret-user" not in rendered
    assert "secret-password" not in rendered
    assert "/private/profile" not in rendered
    assert "Private source" not in rendered
    assert "smb://" not in rendered
    assert "private-music-session-token" not in rendered
    assert "private-playlist-fingerprint" not in rendered


def test_support_bundle_contains_only_sanitized_diagnostics(tmp_path) -> None:
    profile = str(tmp_path / "addon-profile")
    runtime = SimpleNamespace(catalog=Catalog(), kodi=Kodi(profile))
    generated_at = datetime(2026, 8, 7, 11, 30, 45, tzinfo=timezone.utc)

    path = write_support_bundle(
        runtime,
        now=1125.0,
        generated_at=generated_at,
    )

    assert path.endswith(
        "support-bundles/mypicsdb3-support-20260807-113045Z-v0.8.9.zip"
    )
    with zipfile.ZipFile(path) as archive:
        assert sorted(archive.namelist()) == ["README.txt", "diagnostics.json"]
        payload = json.loads(archive.read("diagnostics.json"))
        readme = archive.read("README.txt").decode("utf-8")

    assert payload["format_version"] == 1
    assert payload["generated_at"] == "2026-08-07T11:30:45Z"
    assert payload["diagnostics"]["plugin_version"] == "0.8.9"
    assert payload["diagnostics"]["active_scan"] == {
        "kind": "manual",
        "state": "running",
        "pictures_seen": 25,
        "elapsed_seconds": 125.0,
    }
    assert payload["privacy"] == {
        "database_credentials_included": False,
        "database_host_included": False,
        "profile_paths_included": False,
        "source_uris_included": False,
        "current_scan_path_included": False,
        "kodi_log_included": False,
    }

    exported = json.dumps(payload, ensure_ascii=False)
    for secret in (
        "secret-password",
        "private-db.example",
        "addon-profile",
        "smb://",
        "Private source",
        "scan-1",
        "private-music-session-token",
        "private-playlist-fingerprint",
    ):
        assert secret not in exported
    assert "does not include" in readme
