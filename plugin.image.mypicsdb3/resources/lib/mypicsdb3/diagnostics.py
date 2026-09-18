from __future__ import annotations

import json
import os
import time
import zipfile
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from . import SCHEMA_VERSION, VERSION
from .query_model import QUERY_MODEL_VERSION
from .utils import duration_seconds, join_uri


SCREENSAVER_ADDON_ID = "screensaver.mypicsdb3"
REPOSITORY_ADDON_ID = "repository.mypicsdb3"


MYPICSDB3_LOG_MARKER = "[MyPicsDB 3]"
KODI_LOG_EXPORT_SOURCES = (
    ("kodi.old.log", "special://logpath/kodi.old.log"),
    ("kodi.log", "special://logpath/kodi.log"),
)
LOG_EXPORT_MAX_BYTES_PER_FILE = 16 * 1024 * 1024


def _mypicsdb3_log_lines(
    filesystem, path: str, *, max_bytes: int = LOG_EXPORT_MAX_BYTES_PER_FILE
) -> Tuple[List[str], bool]:
    """Return MyPicsDB 3 lines from the tail of one Kodi session log."""

    if not filesystem.exists(path):
        return [], False

    start = 0
    try:
        size = max(0, int(filesystem.stat(path).size))
        start = max(0, size - max(1, int(max_bytes)))
    except Exception:
        # Reading the complete file is still useful when a compatibility VFS
        # cannot provide a reliable stat result.
        start = 0

    with filesystem.open_binary(path) as stream:
        if start:
            stream.seek(start, 0)
        data = stream.read()

    if isinstance(data, bytes):
        text = data.decode("utf-8", "replace")
    else:
        text = str(data or "")

    truncated = bool(start)
    if truncated:
        # The bounded tail can start in the middle of a log line. Do not export
        # that incomplete fragment as though it were a complete diagnostic.
        newline = text.find("\n")
        text = text[newline + 1 :] if newline >= 0 else ""

    return [line for line in text.splitlines() if MYPICSDB3_LOG_MARKER in line], truncated


def write_mypicsdb3_log_export(
    runtime,
    output_dir: str,
    *,
    generated_at: Optional[datetime] = None,
) -> Tuple[str, int]:
    """Export filtered MyPicsDB 3 rows from current and previous Kodi logs."""

    timestamp = generated_at or datetime.now(timezone.utc)
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=timezone.utc)
    timestamp = timestamp.astimezone(timezone.utc)

    sections = []
    unreadable = []
    total_lines = 0
    for label, source_path in KODI_LOG_EXPORT_SOURCES:
        try:
            lines, truncated = _mypicsdb3_log_lines(runtime.filesystem, source_path)
        except Exception:
            unreadable.append(label)
            continue
        if not lines:
            continue
        total_lines += len(lines)
        heading = "--- %s%s ---" % (
            label,
            " (last 16 MiB only)" if truncated else "",
        )
        sections.append("%s\n%s" % (heading, "\n".join(lines)))

    generated = timestamp.isoformat().replace("+00:00", "Z")
    header = [
        "MyPicsDB 3 filtered Kodi log",
        "Generated: %s" % generated,
        "Only lines containing %s are included." % MYPICSDB3_LOG_MARKER,
        "Review this file before sharing; add-on log messages may contain filenames or source information.",
    ]
    if unreadable:
        header.append("Could not read: %s" % ", ".join(unreadable))
    if not sections:
        sections.append("No MyPicsDB 3 log entries were found.")

    content = "\n".join(header) + "\n\n" + "\n\n".join(sections) + "\n"
    filename = "mypicsdb3-log-%s.txt" % timestamp.strftime("%Y%m%d-%H%M%SZ")
    destination = join_uri(str(output_dir or ""), filename)
    runtime.filesystem.write_text(destination, content)
    return destination, total_lines


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


def _home_generations(kodi) -> Dict[str, int]:
    getter = getattr(kodi, "home_widget_generations", None)
    if not callable(getter):
        return {"content": 0, "random": 0}
    try:
        values = getter()
    except Exception:
        values = {}
    if not isinstance(values, dict):
        values = {}

    def generation(key: str) -> int:
        try:
            return max(0, int(values.get(key) or 0))
        except (TypeError, ValueError):
            return 0

    return {"content": generation("content"), "random": generation("random")}


def _picture_playlist_compatibility(kodi) -> str:
    getter = getattr(kodi, "picture_playlist_compatibility", None)
    if not callable(getter):
        return "unknown"
    try:
        compatible = getter()
    except Exception:
        return "unknown"
    if compatible is True:
        return "compatible"
    if compatible is False:
        return "incompatible"
    return "unknown"


def _music_session_status(kodi) -> Dict[str, bool]:
    getter = getattr(kodi, "music_slideshow_session", None)
    if not callable(getter):
        return {"active": False, "playlist_fingerprint_present": False}
    try:
        session = getter()
    except Exception:
        session = {}
    if not isinstance(session, dict):
        session = {}
    return {
        "active": bool(str(session.get("token") or "")),
        "playlist_fingerprint_present": bool(
            str(session.get("playlist_fingerprint") or "")
        ),
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
        "home_generations": _home_generations(runtime.kodi),
        "picture_playlist_compatibility": _picture_playlist_compatibility(
            runtime.kodi
        ),
        "music_slideshow_session": _music_session_status(runtime.kodi),
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
