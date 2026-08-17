from __future__ import annotations

import json
import os
import socket
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence

from .db.locks import METADATA_REFRESH_LOCK_NAME
from .geocoding import (
    load_cached_reverse_geocoding,
    load_location_enrichment,
    merge_location,
    save_location_enrichment,
)
from .metadata import extract_metadata
from .metadata_mapping import MetadataMappingRule, metadata_index_signature
from .models import MetadataResult
from .utils import local_datetime_from_timestamp


REFRESH_LOCK_TTL_SECONDS = 1800
REFRESH_LOCK_REFRESH_SECONDS = 60
ALL_REFRESH_CHECKPOINT_FILENAME = "metadata-refresh-all-v1.json"
ALL_REFRESH_CHECKPOINT_VERSION = 1


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


@dataclass
class MetadataRefreshAllStats(MetadataRefreshStats):
    processed: int = 0
    completed: bool = False
    resumed: bool = False
    last_picture_id: int = 0


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

    def _checkpoint_path(self) -> str:
        profile_path = str(getattr(self.settings, "profile_path", "") or "").strip()
        if not profile_path:
            return ""
        return os.path.join(profile_path, ALL_REFRESH_CHECKPOINT_FILENAME)

    def _checkpoint_identity(self) -> Dict[str, Any]:
        backend = str(getattr(self.settings, "database_backend", "sqlite") or "sqlite")
        identity: Dict[str, Any] = {"backend": backend}
        if backend == "mysql":
            identity.update(
                {
                    "host": str(getattr(self.settings, "mysql_host", "") or ""),
                    "port": int(getattr(self.settings, "mysql_port", 3306) or 3306),
                    "database": str(getattr(self.settings, "mysql_database", "") or ""),
                }
            )
        return identity

    def _read_all_checkpoint(self) -> Optional[Dict[str, Any]]:
        path = self._checkpoint_path()
        if not path or not os.path.isfile(path):
            return None
        try:
            with open(path, "r", encoding="utf-8") as handle:
                payload = json.load(handle)
        except Exception as exc:
            if self.logger:
                self.logger.warning("Could not read metadata refresh checkpoint: %s", exc)
            return None
        if not isinstance(payload, dict):
            return None
        if int(payload.get("version") or 0) != ALL_REFRESH_CHECKPOINT_VERSION:
            return None
        if payload.get("catalogue") != self._checkpoint_identity():
            return None
        if str(payload.get("metadata_index_hash") or "") != self._metadata_index_hash:
            return None
        if int(payload.get("max_picture_id") or 0) <= 0:
            return None
        return payload

    def _write_all_checkpoint(self, payload: Dict[str, Any]) -> None:
        path = self._checkpoint_path()
        if not path:
            return
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            temporary = path + ".tmp"
            with open(temporary, "w", encoding="utf-8") as handle:
                json.dump(
                    payload,
                    handle,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                )
            os.replace(temporary, path)
        except Exception as exc:
            if self.logger:
                self.logger.warning("Could not save metadata refresh checkpoint: %s", exc)

    def discard_all_refresh_checkpoint(self) -> None:
        path = self._checkpoint_path()
        if not path:
            return
        try:
            os.remove(path)
        except FileNotFoundError:
            pass
        except Exception as exc:
            if self.logger:
                self.logger.warning("Could not remove metadata refresh checkpoint: %s", exc)

    def all_refresh_checkpoint(self) -> Optional[Dict[str, Any]]:
        self._prepare()
        payload = self._read_all_checkpoint()
        return dict(payload) if payload else None

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
        enrichment = load_location_enrichment(self.catalog, uri)
        if (
            enrichment is None
            and metadata.gps_latitude is not None
            and metadata.gps_longitude is not None
        ):
            enrichment = load_cached_reverse_geocoding(
                self.catalog,
                str(
                    getattr(
                        self.settings,
                        "reverse_geocoding_endpoint",
                        "https://nominatim.openstreetmap.org",
                    )
                    or "https://nominatim.openstreetmap.org"
                ),
                float(metadata.gps_latitude),
                float(metadata.gps_longitude),
            )
            if enrichment is not None:
                # This is cache reuse only; no network request occurs here.
                save_location_enrichment(self.catalog, uri, enrichment)
        location = merge_location(metadata.location or {}, enrichment)
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

    def refresh_all(
        self,
        cancelled: Optional[Callable[[], bool]] = None,
        progress: Optional[Callable[[int, int, str], None]] = None,
        *,
        restart: bool = False,
    ) -> MetadataRefreshAllStats:
        """Re-read every indexed still picture serially with local resume state.

        The ID horizon is fixed when a run starts. New pictures added after a
        paused run are deliberately left for the next run/normal scanner.
        Reverse-geocoding cache entries may be reused locally, but this method
        never performs online reverse geocoding.
        """

        self._acquire()
        try:
            if restart:
                self.discard_all_refresh_checkpoint()
            checkpoint = self._read_all_checkpoint()
            resumed = checkpoint is not None
            if checkpoint is None:
                total, max_picture_id = self.catalog.metadata_refresh_picture_horizon()
                state: Dict[str, Any] = {
                    "version": ALL_REFRESH_CHECKPOINT_VERSION,
                    "catalogue": self._checkpoint_identity(),
                    "metadata_index_hash": self._metadata_index_hash,
                    "max_picture_id": int(max_picture_id),
                    "total": int(total),
                    "last_picture_id": 0,
                    "processed": 0,
                    "refreshed": 0,
                    "failed": 0,
                }
            else:
                state = dict(checkpoint)
                max_picture_id = int(state.get("max_picture_id") or 0)
                total, _ignored = self.catalog.metadata_refresh_picture_horizon(
                    max_picture_id
                )
                total = max(int(total), int(state.get("processed") or 0))
                state["total"] = int(total)

            stats = MetadataRefreshAllStats(
                requested=int(total),
                processed=int(state.get("processed") or 0),
                refreshed=int(state.get("refreshed") or 0),
                failed=int(state.get("failed") or 0),
                resumed=resumed,
                last_picture_id=int(state.get("last_picture_id") or 0),
            )
            if stats.requested <= 0 or max_picture_id <= 0:
                stats.completed = True
                self.discard_all_refresh_checkpoint()
                return stats

            batch_size = max(
                10,
                min(500, int(getattr(self.settings, "batch_size", 100) or 100)),
            )
            while True:
                picture_ids = self.catalog.picture_ids_for_metadata_refresh(
                    stats.last_picture_id, max_picture_id, batch_size
                )
                if not picture_ids:
                    stats.completed = True
                    self.discard_all_refresh_checkpoint()
                    return stats

                touched_folders = set()
                for picture_id in picture_ids:
                    if cancelled and cancelled():
                        for folder_id in sorted(touched_folders):
                            self.catalog.refresh_folder_summary(folder_id)
                        state.update(
                            {
                                "last_picture_id": stats.last_picture_id,
                                "processed": stats.processed,
                                "refreshed": stats.refreshed,
                                "failed": stats.failed,
                            }
                        )
                        self._write_all_checkpoint(state)
                        return stats
                    filename = ""
                    try:
                        inspection = self._refresh_one(int(picture_id))
                        stats.refreshed += 1
                        filename = str(inspection.row.get("filename") or "")
                        touched_folders.add(int(inspection.row["folder_id"]))
                    except MetadataRefreshNotFound as exc:
                        stats.failed += 1
                        stats.errors.append(str(exc))
                    except Exception as exc:
                        stats.failed += 1
                        stats.errors.append(
                            "%s: %s" % (exc.__class__.__name__, str(exc))
                        )
                        if self.logger:
                            self.logger.warning(
                                "Whole-library metadata refresh failed for picture id %s: %s",
                                picture_id,
                                exc,
                            )
                    stats.processed += 1
                    stats.last_picture_id = int(picture_id)
                    if len(stats.errors) > 50:
                        del stats.errors[:-50]
                    if progress:
                        progress(stats.processed, stats.requested, filename)
                for folder_id in sorted(touched_folders):
                    self.catalog.refresh_folder_summary(folder_id)
                state.update(
                    {
                        "last_picture_id": stats.last_picture_id,
                        "processed": stats.processed,
                        "refreshed": stats.refreshed,
                        "failed": stats.failed,
                    }
                )
                self._write_all_checkpoint(state)
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
