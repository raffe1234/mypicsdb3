from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence

from .utils import basename_uri, join_uri, normalize_uri


EXPORT_MANIFEST_NAME = "mypicsdb3-export-manifest.json"
EXPORT_MANIFEST_VERSION = 1
EXPORT_FETCH_BATCH_SIZE = 500
MAX_EXPORT_NAME_LENGTH = 120
_WINDOWS_RESERVED_NAMES = frozenset(
    {"CON", "PRN", "AUX", "NUL"}
    | {"COM%d" % value for value in range(1, 10)}
    | {"LPT%d" % value for value in range(1, 10)}
)


class ExportError(RuntimeError):
    """Raised when a safe export cannot be started or completed safely."""


@dataclass(frozen=True)
class ExportResult:
    export_uri: str
    manifest_uri: str
    selected: int
    processed: int
    copied: int
    missing: int
    failed: int
    collisions: int
    cancelled: bool


def _portable_name(value: Any, fallback: str) -> str:
    name = basename_uri(str(value or "").strip())
    name = re.sub(r"[\x00-\x1f<>:\"/\\|?*]", "_", name)
    name = re.sub(r"\s+", " ", name).strip().rstrip(". ")
    if not name or name in {".", ".."}:
        name = fallback
    stem = name.split(".", 1)[0].upper()
    if stem in _WINDOWS_RESERVED_NAMES:
        name = "_" + name
    if len(name) > MAX_EXPORT_NAME_LENGTH:
        if "." in name:
            stem, extension = name.rsplit(".", 1)
            suffix = "." + extension[:20]
            name = stem[: max(1, MAX_EXPORT_NAME_LENGTH - len(suffix))] + suffix
        else:
            name = name[:MAX_EXPORT_NAME_LENGTH]
    return name


def normalize_export_name(value: Any) -> str:
    return _portable_name(value, "MyPicsDB3 Export")


def _collision_name(filename: str, number: int) -> str:
    if "." in filename and not filename.startswith("."):
        stem, extension = filename.rsplit(".", 1)
        return "%s (%d).%s" % (stem, number, extension)
    return "%s (%d)" % (filename, number)


def _utc_timestamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _manifest_uri(value: Any) -> str:
    """Return a provenance URI safe to persist in an export manifest.

    Kodi VFS URIs may contain ``user:password@host``. The exporter still uses
    the original URI for the copy operation, but credentials are removed before
    any source or destination URI is written to the user-visible manifest.
    """

    uri = str(value or "").strip()
    if "://" not in uri:
        return uri
    from urllib.parse import urlsplit, urlunsplit

    parts = urlsplit(uri)
    netloc = parts.netloc.rsplit("@", 1)[-1]
    # Query strings and fragments are not needed for human-readable provenance
    # and may themselves contain bearer tokens or signed URL parameters.
    return urlunsplit((parts.scheme, netloc, parts.path, "", ""))


class SafeExporter:
    """COPY-only media exporter with collision handling and a JSON manifest.

    The caller freezes the ordered catalogue IDs before invoking the exporter.
    Only destination files are created. Source media are never moved, renamed,
    edited or deleted.
    """

    def __init__(self, catalog, filesystem, addon_version: str, logger=None):
        self.catalog = catalog
        self.filesystem = filesystem
        self.addon_version = str(addon_version or "")
        self.logger = logger

    def _inside_catalog_source(self, candidate_uri: str) -> bool:
        # Fail closed if the catalogue cannot enumerate its configured sources.
        # Export safety must not silently weaken just because the database read
        # failed.
        sources = self.catalog.get_sources()
        candidate = normalize_uri(
            _manifest_uri(candidate_uri), directory=True
        ).casefold()
        for source in sources:
            source_uri = normalize_uri(
                _manifest_uri(getattr(source, "uri", "")), directory=True
            ).casefold()
            if source_uri and candidate.startswith(source_uri):
                return True
        return False

    def _unique_export_directory(self, parent_uri: str, requested_name: str) -> str:
        parent = str(parent_uri or "").strip()
        if not parent:
            raise ExportError("Export destination is empty")
        base_name = normalize_export_name(requested_name)
        for number in range(1, 10000):
            folder_name = base_name if number == 1 else "%s (%d)" % (base_name, number)
            candidate = join_uri(parent, folder_name, directory=True)
            if self._inside_catalog_source(candidate):
                raise ExportError(
                    "Export destination must be outside configured picture sources"
                )
            try:
                exists = self.filesystem.exists(candidate)
            except Exception as exc:
                raise ExportError(
                    "Could not check the export destination (%s)"
                    % type(exc).__name__
                ) from exc
            if not exists:
                try:
                    created = self.filesystem.makedirs(candidate)
                except Exception as exc:
                    raise ExportError(
                        "Could not create export folder (%s)"
                        % type(exc).__name__
                    ) from exc
                if not created:
                    raise ExportError("Could not create export folder")
                return candidate
        raise ExportError("Could not allocate a unique export folder")

    def _unique_destination(self, export_uri: str, filename: str) -> tuple[str, str, bool]:
        safe_name = _portable_name(filename, "media")
        for number in range(1, 10000):
            candidate_name = safe_name if number == 1 else _collision_name(safe_name, number)
            candidate = join_uri(export_uri, candidate_name)
            try:
                exists = self.filesystem.exists(candidate)
            except Exception as exc:
                raise ExportError(
                    "Could not check an export filename (%s)"
                    % type(exc).__name__
                ) from exc
            if not exists:
                return candidate, candidate_name, number > 1
        raise ExportError("Could not allocate a unique destination filename")

    def _manifest_payload(
        self,
        *,
        export_uri: str,
        selection_label: str,
        selected: int,
        entries: Sequence[Mapping[str, Any]],
        started_at: str,
        status: str,
    ) -> Dict[str, Any]:
        copied = sum(1 for entry in entries if entry.get("status") == "copied")
        missing = sum(1 for entry in entries if entry.get("status") == "missing")
        failed = sum(1 for entry in entries if entry.get("status") == "failed")
        collisions = sum(1 for entry in entries if entry.get("renamed_for_collision"))
        return {
            "format": "mypicsdb3-export-manifest",
            "manifest_version": EXPORT_MANIFEST_VERSION,
            "mypicsdb3_version": self.addon_version,
            "status": status,
            "started_at_utc": started_at,
            "finished_at_utc": _utc_timestamp() if status != "running" else None,
            "selection": {
                "label": str(selection_label or ""),
                "selected": int(selected),
            },
            "summary": {
                "processed": len(entries),
                "copied": copied,
                "missing": missing,
                "failed": failed,
                "renamed_for_collision": collisions,
            },
            "destination": _manifest_uri(export_uri),
            "items": list(entries),
        }

    def export_ids(
        self,
        picture_ids: Sequence[int],
        destination_parent: str,
        export_name: str,
        selection_label: str,
        *,
        cancelled: Optional[Callable[[], bool]] = None,
        progress: Optional[Callable[[int, int, str], None]] = None,
    ) -> ExportResult:
        ids = [int(value) for value in picture_ids]
        if not ids:
            raise ExportError("The current selection does not contain any media")
        if any(value <= 0 for value in ids):
            raise ExportError("Export selection contains an invalid media ID")
        if len(ids) != len(set(ids)):
            raise ExportError("Export selection contains duplicate media IDs")

        export_uri = self._unique_export_directory(destination_parent, export_name)
        manifest_uri = join_uri(export_uri, EXPORT_MANIFEST_NAME)
        entries: List[Dict[str, Any]] = []
        started_at = _utc_timestamp()

        # Preflight manifest writing before copying media. If the selected VFS
        # target cannot create ordinary files, fail without producing a partial
        # media export.
        running_manifest = self._manifest_payload(
            export_uri=export_uri,
            selection_label=selection_label,
            selected=len(ids),
            entries=entries,
            started_at=started_at,
            status="running",
        )
        try:
            self.filesystem.write_text(
                manifest_uri,
                json.dumps(running_manifest, ensure_ascii=False, indent=2) + "\n",
            )
        except Exception as exc:
            raise ExportError(
                "Could not write the export manifest (%s)" % type(exc).__name__
            ) from exc

        was_cancelled = False
        for start in range(0, len(ids), EXPORT_FETCH_BATCH_SIZE):
            if cancelled is not None and cancelled():
                was_cancelled = True
                break
            batch_ids = ids[start : start + EXPORT_FETCH_BATCH_SIZE]
            rows = self.catalog.media_for_export(batch_ids)
            rows_by_id = {int(row["id"]): row for row in rows}
            for picture_id in batch_ids:
                if cancelled is not None and cancelled():
                    was_cancelled = True
                    break
                row = rows_by_id.get(picture_id)
                if row is None:
                    entries.append(
                        {
                            "id": picture_id,
                            "status": "missing",
                            "source_uri": "",
                            "exported_file": None,
                            "media_type": "",
                            "error": "Catalogue item is no longer available",
                        }
                    )
                else:
                    source_uri = str(row.get("uri") or "").strip()
                    filename = str(row.get("filename") or basename_uri(source_uri))
                    entry: Dict[str, Any] = {
                        "id": picture_id,
                        "status": "failed",
                        "source_uri": _manifest_uri(source_uri),
                        "exported_file": None,
                        "media_type": str(row.get("media_type") or "picture"),
                        "file_size": row.get("file_size"),
                        "file_mtime": row.get("file_mtime"),
                        "source_label": str(row.get("source_label") or ""),
                        "renamed_for_collision": False,
                        "error": None,
                    }
                    try:
                        if not source_uri or not self.filesystem.exists(source_uri):
                            entry["status"] = "missing"
                            entry["error"] = "Source file is not available"
                        else:
                            destination_uri, destination_name, collision = (
                                self._unique_destination(export_uri, filename)
                            )
                            entry["exported_file"] = destination_name
                            entry["renamed_for_collision"] = collision
                            if self.filesystem.copy(source_uri, destination_uri):
                                entry["status"] = "copied"
                            else:
                                entry["error"] = "Kodi VFS copy returned false"
                    except Exception as exc:
                        # Exceptions from VFS implementations can echo the full
                        # URI, including embedded credentials. Keep the manifest
                        # and log useful without persisting exception text.
                        entry["status"] = "failed"
                        entry["error"] = "Copy failed (%s)" % type(exc).__name__
                        if self.logger is not None:
                            try:
                                self.logger.warning(
                                    "Export failed for media id %s (%s)",
                                    picture_id,
                                    type(exc).__name__,
                                )
                            except Exception:
                                pass
                    entries.append(entry)
                if progress is not None:
                    current_name = str(
                        (rows_by_id.get(picture_id) or {}).get("filename") or picture_id
                    )
                    progress(len(entries), len(ids), current_name)
            if was_cancelled:
                break

        status = "cancelled" if was_cancelled else "completed"
        final_manifest = self._manifest_payload(
            export_uri=export_uri,
            selection_label=selection_label,
            selected=len(ids),
            entries=entries,
            started_at=started_at,
            status=status,
        )
        try:
            self.filesystem.write_text(
                manifest_uri,
                json.dumps(final_manifest, ensure_ascii=False, indent=2) + "\n",
            )
        except Exception as exc:
            raise ExportError(
                "Media export finished but the final manifest could not be written (%s)"
                % type(exc).__name__
            ) from exc

        summary = final_manifest["summary"]
        return ExportResult(
            export_uri=export_uri,
            manifest_uri=manifest_uri,
            selected=len(ids),
            processed=int(summary["processed"]),
            copied=int(summary["copied"]),
            missing=int(summary["missing"]),
            failed=int(summary["failed"]),
            collisions=int(summary["renamed_for_collision"]),
            cancelled=was_cancelled,
        )
