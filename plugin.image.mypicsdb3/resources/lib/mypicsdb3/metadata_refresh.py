from __future__ import annotations

import os
import socket
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence

from .db.locks import METADATA_REFRESH_LOCK_NAME
from .geocoding import load_location_enrichment, merge_location
from .metadata import extract_metadata
from .metadata_mapping import MetadataMappingRule, metadata_index_signature
from .models import MetadataResult
from .utils import local_datetime_from_timestamp


REFRESH_LOCK_TTL_SECONDS = 1800
REFRESH_LOCK_REFRESH_SECONDS = 60


class MetadataRefreshBusy(RuntimeError):
    pass


class MetadataRefreshNotFound(RuntimeError):
    pass


@dataclass
class MetadataInspection:
    row: Dict[str, Any]
    fresh: MetadataResult
    source_details: Dict[str, Any] = field(default_factory=dict)


@dataclass
class MetadataRefreshStats:
    requested: int = 0
    refreshed: int = 0
    failed: int = 0
    errors: List[str] = field(default_factory=list)


class MetadataRefresher:
    """Explicit, serial metadata re-read for already indexed still pictures.

    The refresher never traverses source trees and never mutates source media. It
    coordinates with the catalogue scan/migration locks so the same picture row
    is not being rewritten by a scanner at the same time.
    """

    def __init__(self, catalog, filesystem, settings, logger=None):
        self.catalog = catalog
        self.filesystem = filesystem
        self.settings = settings
        self.logger = logger
        self.owner = "%s:%s:%s" % (
            socket.gethostname(),
            os.getpid(),
            uuid.uuid4().hex[:12],
        )
        self._lock_active = False
        self._lock_refreshed_at = 0.0
        self._mapping_overrides: Sequence[MetadataMappingRule] = ()
        self._metadata_index_hash = ""

    def _prepare(self) -> None:
        self._mapping_overrides = tuple(self.catalog.list_metadata_mapping_overrides())
        self._metadata_index_hash = metadata_index_signature(
            self.settings, self._mapping_overrides
        )

    def _acquire(self) -> None:
        recovered_owner = self.catalog.recover_stale_local_lock(
            METADATA_REFRESH_LOCK_NAME, self.owner
        )
        if recovered_owner and self.logger:
            self.logger.warning(
                "Recovered stale SQLite metadata refresh lock left by previous Kodi process: %s",
                recovered_owner,
            )
        if not self.catalog.acquire_lock(
            METADATA_REFRESH_LOCK_NAME,
            self.owner,
            REFRESH_LOCK_TTL_SECONDS,
        ):
            raise MetadataRefreshBusy(
                "A catalogue scan, schema migration or metadata refresh is already running"
            )
        self._lock_active = True
        self._lock_refreshed_at = time.monotonic()
        self._prepare()

    def _refresh_lock_if_due(self) -> None:
        if not self._lock_active:
            return
        now = time.monotonic()
        if now - self._lock_refreshed_at < REFRESH_LOCK_REFRESH_SECONDS:
            return
        if not self.catalog.refresh_lock(
            METADATA_REFRESH_LOCK_NAME,
            self.owner,
            REFRESH_LOCK_TTL_SECONDS,
        ):
            raise MetadataRefreshBusy("The metadata refresh lock was lost")
        self._lock_refreshed_at = now

    def _release(self) -> None:
        if not self._lock_active:
            return
        try:
            self.catalog.release_lock(METADATA_REFRESH_LOCK_NAME, self.owner)
        finally:
            self._lock_active = False

    def inspect_picture(self, picture_id: int) -> MetadataInspection:
        """Read current metadata without changing the catalogue."""
        row = self.catalog.picture_by_id(int(picture_id))
        if not row or str(row.get("media_type") or "picture") != "picture":
            raise MetadataRefreshNotFound("Picture was not found")
        self._prepare()
        uri = str(row.get("uri") or "")
        file_stat = self.filesystem.stat(uri)
        source_details: Dict[str, Any] = {}
        fresh = extract_metadata(
            uri,
            self.filesystem,
            self.settings,
            file_stat.size,
            mapping_rules=self._mapping_overrides,
            diagnostics=source_details,
        )
        return MetadataInspection(dict(row), fresh, source_details)

    def _refresh_one(self, picture_id: int) -> MetadataInspection:
        self._refresh_lock_if_due()
        row = self.catalog.picture_by_id(int(picture_id))
        if not row or str(row.get("media_type") or "picture") != "picture":
            raise MetadataRefreshNotFound("Picture was not found")

        uri = str(row.get("uri") or "")
        file_stat = self.filesystem.stat(uri)
        source_details: Dict[str, Any] = {}
        metadata = extract_metadata(
            uri,
            self.filesystem,
            self.settings,
            file_stat.size,
            mapping_rules=self._mapping_overrides,
            diagnostics=source_details,
        )
        if not metadata.taken_at:
            metadata.taken_at = local_datetime_from_timestamp(file_stat.mtime)
            metadata.taken_source = "File mtime fallback"
        location = merge_location(
            metadata.location or {},
            load_location_enrichment(self.catalog, uri),
        )
        record: Dict[str, Any] = {
            "source_id": int(row["source_id"]),
            "folder_id": int(row["folder_id"]),
            "uri": uri,
            "filename": str(row.get("filename") or ""),
            "extension": str(row.get("extension") or ""),
            "media_type": "picture",
            "file_size": int(file_stat.size),
            "file_mtime": float(file_stat.mtime),
            "discovered_at": row.get("discovered_at"),
            # Refresh is not a source traversal; preserve scan-seen semantics.
            "last_seen_at": row.get("last_seen_at"),
            "taken_at": metadata.taken_at,
            "taken_source": metadata.taken_source,
            "width": metadata.width,
            "height": metadata.height,
            "orientation": metadata.orientation,
            "mime_type": metadata.mime_type,
            "camera_make": metadata.camera_make,
            "camera_model": metadata.camera_model,
            "rating": metadata.rating,
            "gps_latitude": metadata.gps_latitude,
            "gps_longitude": metadata.gps_longitude,
            "city": location.get("city"),
            "state": location.get("state"),
            "country": location.get("country"),
            "sublocation": location.get("sublocation"),
            "caption": metadata.caption,
            "metadata_hash": metadata.metadata_hash,
            "metadata_index_hash": self._metadata_index_hash,
            "thumb_uri": row.get("thumb_uri") or uri,
        }
        if not self.catalog.refresh_picture_record(
            int(row["id"]), record, metadata.keywords
        ):
            raise MetadataRefreshNotFound("Picture was not found")
        return MetadataInspection(dict(row), metadata, source_details)

    def refresh_picture(self, picture_id: int) -> MetadataInspection:
        self._acquire()
        try:
            inspection = self._refresh_one(int(picture_id))
            self.catalog.refresh_folder_summary(int(inspection.row["folder_id"]))
            return inspection
        finally:
            self._release()

    def refresh_folder(
        self,
        folder_id: int,
        cancelled: Optional[Callable[[], bool]] = None,
        progress: Optional[Callable[[int, int, str], None]] = None,
    ) -> MetadataRefreshStats:
        picture_ids = self.catalog.picture_ids_in_folder(int(folder_id))
        stats = MetadataRefreshStats(requested=len(picture_ids))
        self._acquire()
        try:
            total = len(picture_ids)
            for index, picture_id in enumerate(picture_ids, 1):
                if cancelled and cancelled():
                    break
                try:
                    inspection = self._refresh_one(int(picture_id))
                    stats.refreshed += 1
                    filename = str(inspection.row.get("filename") or "")
                except MetadataRefreshNotFound as exc:
                    stats.failed += 1
                    filename = ""
                    stats.errors.append(str(exc))
                except Exception as exc:
                    stats.failed += 1
                    filename = ""
                    stats.errors.append("%s: %s" % (exc.__class__.__name__, str(exc)))
                    if self.logger:
                        self.logger.warning(
                            "Metadata refresh failed for picture id %s: %s",
                            picture_id,
                            exc,
                        )
                if progress:
                    progress(index, total, filename)
            if stats.refreshed:
                self.catalog.refresh_folder_summary(int(folder_id))
            return stats
        finally:
            self._release()
