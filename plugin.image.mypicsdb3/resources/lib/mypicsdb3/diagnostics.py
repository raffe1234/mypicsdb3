from __future__ import annotations

import json
import os
import time
import zipfile
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from . import SCHEMA_VERSION, VERSION
from .query_model import QUERY_MODEL_VERSION
from .utils import duration_seconds


SCREENSAVER_ADDON_ID = "screensaver.mypicsdb3"
REPOSITORY_ADDON_ID = "repository.mypicsdb3"


def _optional_addon_version(kodi, addon_id: str) -> str:
    getter = getattr(kodi, "installed_addon_version", None)
    if not callable(getter):
        return ""
    try:
        return str(getter(addon_id) or "")
    except Exception:
        return ""


def _current_skin(kodi) -> Dict[str, str]:
    getter = getattr(kodi, "current_skin_id", None)
    if not callable(getter):
        return {"id": "", "version": ""}
    try:
        skin_id = str(getter() or "")
    except Exception:
        skin_id = ""
    if not skin_id:
        return {"id": "", "version": ""}
    return {
        "id": skin_id,
        "version": _optional_addon_version(kodi, skin_id),
    }


def collect_diagnostics(runtime, now: Optional[float] = None) -> Dict[str, Any]:
    """Return a privacy-safe, read-only support snapshot.

    The snapshot intentionally excludes database credentials, local profile paths,
    source URIs and the current scan path. It is suitable as the data foundation
    for both the Kodi diagnostics view and a future support-bundle exporter.
    """

    overview = runtime.catalog.overview()
    latest = runtime.catalog.latest_scan()
    active_getter = getattr(runtime.kodi, "scan_status", None)
    try:
        active = active_getter() if callable(active_getter) else {}
    except Exception:
        active = {}
    if not isinstance(active, dict):
        active = {}

    settings = runtime.kodi.settings
    current_time = time.time() if now is None else float(now)
    active_started_at = active.get("started_at") if active else None
    try:
        active_elapsed = (
            max(0.0, current_time - float(active_started_at))
            if active_started_at is not None
            else None
        )
    except (TypeError, ValueError):
        active_elapsed = None

    return {
        "plugin_version": VERSION,
        "screensaver_version": _optional_addon_version(
            runtime.kodi, SCREENSAVER_ADDON_ID
        ),
        "repository_version": _optional_addon_version(
            runtime.kodi, REPOSITORY_ADDON_ID
        ),
        "skin": _current_skin(runtime.kodi),
        "backend": str(overview.get("backend") or ""),
        "schema_version": SCHEMA_VERSION,
        "query_model_version": QUERY_MODEL_VERSION,
        "indexed_media": int(overview.get("pictures") or 0),
        "indexed_videos": int(overview.get("videos") or 0),
        "missing_media": int(overview.get("missing") or 0),
        "indexed_albums": int(overview.get("folders") or 0),
        "sources": int(overview.get("sources") or 0),
        "enabled_sources": int(overview.get("enabled_sources") or 0),
        "last_scan": {
            "status": str(latest.get("status") or "") if latest else "",
            "finished_at": str(latest.get("finished_at") or "") if latest else "",
            "duration_seconds": (
                duration_seconds(latest.get("started_at"), latest.get("finished_at"))
                if latest
                else None
            ),
        },
        "active_scan": (
            {
                "kind": str(active.get("kind") or "manual"),
                "state": str(active.get("state") or "running"),
                "pictures_seen": int(active.get("pictures_seen") or 0),
                "elapsed_seconds": active_elapsed,
            }
            if active
            else None
        ),
        "home_widget_limit": int(getattr(settings, "home_widget_limit", 10)),
        "random_home_refresh_hours": int(
            getattr(settings, "random_home_refresh_hours", 2)
        ),
        "include_videos": bool(getattr(settings, "include_videos", False)),
        "debug_logging": bool(getattr(settings, "debug_logging", False)),
    }


SUPPORT_BUNDLE_FORMAT_VERSION = 1
SUPPORT_BUNDLE_DIRNAME = "support-bundles"
SUPPORT_BUNDLE_README = """MyPicsDB 3 support bundle\n\nThis bundle is privacy-safe by default. It contains a structured diagnostics\nsnapshot only. It does not include database passwords, database host names,\nKodi/add-on profile paths, source URIs, the current scan path, or kodi.log.\n\nPlease inspect diagnostics.json before sharing the bundle.\n"""


def build_support_bundle_payload(
    runtime,
    *,
    now: Optional[float] = None,
    generated_at: Optional[datetime] = None,
) -> Dict[str, Any]:
    """Build the JSON payload used by the privacy-safe support bundle."""

    timestamp = generated_at or datetime.now(timezone.utc)
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=timezone.utc)
    timestamp = timestamp.astimezone(timezone.utc)
    return {
        "format_version": SUPPORT_BUNDLE_FORMAT_VERSION,
        "generated_at": timestamp.isoformat().replace("+00:00", "Z"),
        "diagnostics": collect_diagnostics(runtime, now=now),
        "privacy": {
            "database_credentials_included": False,
            "database_host_included": False,
            "profile_paths_included": False,
            "source_uris_included": False,
            "current_scan_path_included": False,
            "kodi_log_included": False,
        },
    }


def write_support_bundle(
    runtime,
    *,
    output_dir: Optional[str] = None,
    now: Optional[float] = None,
    generated_at: Optional[datetime] = None,
) -> str:
    """Write a privacy-safe support ZIP and return its absolute local path.

    The default destination is a ``support-bundles`` directory inside the
    add-on profile. A temporary file is replaced atomically so interrupted
    writes do not leave a bundle that looks complete.
    """

    timestamp = generated_at or datetime.now(timezone.utc)
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=timezone.utc)
    timestamp = timestamp.astimezone(timezone.utc)
    payload = build_support_bundle_payload(
        runtime,
        now=now,
        generated_at=timestamp,
    )

    target_dir = output_dir or os.path.join(
        str(runtime.kodi.profile_path), SUPPORT_BUNDLE_DIRNAME
    )
    os.makedirs(target_dir, exist_ok=True)
    stamp = timestamp.strftime("%Y%m%d-%H%M%SZ")
    filename = "mypicsdb3-support-%s-v%s.zip" % (stamp, VERSION)
    final_path = os.path.join(target_dir, filename)
    temporary_path = final_path + ".part"

    diagnostics_json = json.dumps(
        payload,
        ensure_ascii=False,
        indent=2,
        sort_keys=True,
        default=str,
    ) + "\n"
    try:
        with zipfile.ZipFile(
            temporary_path,
            mode="w",
            compression=zipfile.ZIP_DEFLATED,
        ) as archive:
            archive.writestr("diagnostics.json", diagnostics_json)
            archive.writestr("README.txt", SUPPORT_BUNDLE_README)
        os.replace(temporary_path, final_path)
    except Exception:
        try:
            if os.path.exists(temporary_path):
                os.remove(temporary_path)
        except OSError:
            pass
        raise
    return final_path
