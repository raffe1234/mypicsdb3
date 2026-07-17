from __future__ import annotations

import os
import socket
import time
import uuid
from typing import Callable, Dict, Iterable, List, Optional, Sequence, Tuple

from .config import Settings
from .db.catalog import Catalog
from .filesystem import Filesystem
from .metadata import extract_metadata
from .models import MetadataResult, ScanStats, Source
from .utils import basename_uri, extension_of, join_uri, local_datetime_from_timestamp, normalize_uri, utc_now


class ScanCancelled(Exception):
    pass


class Scanner:
    def __init__(
        self,
        catalog: Catalog,
        filesystem: Filesystem,
        settings: Settings,
        logger=None,
        metadata_reader: Callable[[str, Filesystem, Settings, int], MetadataResult] = extract_metadata,
        cancelled: Optional[Callable[[], bool]] = None,
        progress: Optional[Callable[[Source, str, ScanStats], None]] = None,
    ):
        self.catalog = catalog
        self.filesystem = filesystem
        self.settings = settings
        self.logger = logger
        self.metadata_reader = metadata_reader
        self.cancelled = cancelled or (lambda: False)
        self.progress = progress
        self.owner = "%s:%s:%s" % (socket.gethostname(), os.getpid(), uuid.uuid4().hex[:12])

    def _is_excluded(self, path: str, name: str) -> bool:
        if self.settings.exclude_hidden and name.startswith("."):
            return True
        lower = path.casefold()
        return any(fragment in lower for fragment in self.settings.exclude_fragments)

    def _check_cancelled(self) -> None:
        if self.cancelled():
            raise ScanCancelled()

    def scan_sources(self, source_ids: Optional[Sequence[int]] = None) -> ScanStats:
        overall = ScanStats(started_at=utc_now())
        started_monotonic = time.monotonic()
        sources = self.catalog.get_sources(enabled_only=True)
        if source_ids is not None:
            wanted = {int(value) for value in source_ids}
            sources = [source for source in sources if source.id in wanted]
        if not sources:
            overall.finished_at = utc_now()
            overall.duration_seconds = time.monotonic() - started_monotonic
            return overall
        if not self.catalog.acquire_lock("catalogue-scan", self.owner):
            raise RuntimeError("Another scan is already running")
        try:
            for source in sources:
                self._check_cancelled()
                source_stats = self.scan_source(source)
                overall.merge(source_stats)
        except ScanCancelled:
            overall.cancelled = True
        finally:
            self.catalog.release_lock("catalogue-scan", self.owner)
        overall.finished_at = utc_now()
        overall.duration_seconds = time.monotonic() - started_monotonic
        return overall

    def scan_source(self, source: Source) -> ScanStats:
        stats = ScanStats(sources_total=1, started_at=utc_now())
        started_monotonic = time.monotonic()
        scan_id = self.catalog.begin_scan_run(source.id)
        stats.scan_id = scan_id
        root = normalize_uri(source.uri, directory=True)
        if not self.filesystem.exists(root):
            stats.sources_unavailable = 1
            stats.errors = 1
            message = "Source unavailable: %s" % root
            stats.error_messages.append(message)
            self.catalog.set_source_scan_state(source.id, False, "unavailable", message)
            self.catalog.finish_scan_run(scan_id, "unavailable", stats, message)
            stats.finished_at = utc_now()
            stats.duration_seconds = time.monotonic() - started_monotonic
            return stats

        connection = self.catalog.open_scan_connection()
        scan_started_at = utc_now()
        changed_since_commit = 0
        try:
            stack: List[Tuple[str, str, str]] = [(root, "", source.label)]
            visited = set()
            while stack:
                self._check_cancelled()
                folder_uri, parent_uri, folder_name = stack.pop()
                folder_uri = normalize_uri(folder_uri, directory=True)
                if folder_uri in visited:
                    continue
                visited.add(folder_uri)
                if self._is_excluded(folder_uri, folder_name):
                    continue
                folder_id = self.catalog.upsert_folder(connection, source.id, folder_uri, parent_uri, folder_name, scan_started_at)
                stats.folders_seen += 1
                changed_since_commit += 1
                try:
                    directories, files = self.filesystem.listdir(folder_uri)
                except Exception as exc:
                    stats.errors += 1
                    stats.error_messages.append("Cannot list %s: %s" % (folder_uri, exc))
                    if self.logger:
                        self.logger.warning("Cannot list %s: %s", folder_uri, exc)
                    continue

                for directory in sorted(directories, reverse=True):
                    child_uri = join_uri(folder_uri, directory, directory=True)
                    if not self._is_excluded(child_uri, directory):
                        stack.append((child_uri, folder_uri, directory))

                for filename in sorted(files):
                    self._check_cancelled()
                    picture_uri = join_uri(folder_uri, filename)
                    if self._is_excluded(picture_uri, filename):
                        continue
                    extension = extension_of(filename)
                    if extension not in self.settings.extensions:
                        continue
                    stats.pictures_seen += 1
                    if self.progress:
                        self.progress(source, picture_uri, stats)
                    try:
                        file_stat = self.filesystem.stat(picture_uri)
                        existing = self.catalog.find_picture(connection, picture_uri)
                        if existing and int(existing["file_size"]) == file_stat.size and abs(float(existing["file_mtime"]) - file_stat.mtime) < 0.001:
                            self.catalog.touch_picture(connection, int(existing["id"]), folder_id, source.id, scan_started_at)
                            stats.pictures_unchanged += 1
                        else:
                            metadata = self.metadata_reader(picture_uri, self.filesystem, self.settings, file_stat.size)
                            if not metadata.taken_at:
                                metadata.taken_at = local_datetime_from_timestamp(file_stat.mtime)
                                metadata.taken_source = "File mtime fallback"
                            location = metadata.location or {}
                            record: Dict[str, object] = {
                                "source_id": source.id,
                                "folder_id": folder_id,
                                "uri": picture_uri,
                                "filename": filename,
                                "extension": extension,
                                "file_size": file_stat.size,
                                "file_mtime": file_stat.mtime,
                                "discovered_at": existing.get("discovered_at") if existing else scan_started_at,
                                "last_seen_at": scan_started_at,
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
                                # The original URI is intentionally used. Kodi creates a device-local texture cache lazily.
                                "thumb_uri": picture_uri,
                            }
                            if existing:
                                self.catalog.update_picture(connection, int(existing["id"]), record, metadata.keywords)
                                stats.pictures_updated += 1
                            else:
                                self.catalog.insert_picture(connection, record, metadata.keywords)
                                stats.pictures_added += 1
                        changed_since_commit += 1
                        if changed_since_commit >= self.settings.batch_size:
                            connection.commit()
                            changed_since_commit = 0
                    except ScanCancelled:
                        raise
                    except Exception as exc:
                        stats.errors += 1
                        message = "%s: %s" % (picture_uri, exc)
                        stats.error_messages.append(message)
                        if self.logger:
                            self.logger.warning("Picture scan error for %s: %s", picture_uri, exc)

            self._check_cancelled()
            stats.missing_marked = self.catalog.mark_missing_after_scan(connection, source.id, scan_started_at)
            self.catalog.update_folder_summaries(connection, source.id)
            connection.commit()
            stats.sources_scanned = 1
            self.catalog.set_source_scan_state(source.id, True, "completed" if stats.errors == 0 else "completed_with_errors", "\n".join(stats.error_messages[-5:]) or None)
            self.catalog.finish_scan_run(scan_id, "completed" if stats.errors == 0 else "completed_with_errors", stats, "\n".join(stats.error_messages[-5:]) or None)
        except ScanCancelled:
            connection.commit()
            stats.cancelled = True
            self.catalog.set_source_scan_state(source.id, True, "cancelled")
            self.catalog.finish_scan_run(scan_id, "cancelled", stats)
            raise
        except Exception as exc:
            connection.rollback()
            stats.errors += 1
            stats.error_messages.append(str(exc))
            self.catalog.set_source_scan_state(source.id, True, "failed", str(exc))
            self.catalog.finish_scan_run(scan_id, "failed", stats, str(exc))
            if self.logger:
                self.logger.error("Source scan failed for %s: %s", root, exc)
        finally:
            connection.close()
            stats.finished_at = utc_now()
            stats.duration_seconds = time.monotonic() - started_monotonic
        return stats
