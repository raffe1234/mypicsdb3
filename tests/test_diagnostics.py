from __future__ import annotations

from types import SimpleNamespace

from mypicsdb3.diagnostics import collect_diagnostics


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
    settings = SimpleNamespace(
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

    rendered = repr(snapshot)
    assert "private-db.example" not in rendered
    assert "secret-user" not in rendered
    assert "secret-password" not in rendered
    assert "/private/profile" not in rendered
    assert "Private source" not in rendered
    assert "smb://" not in rendered
