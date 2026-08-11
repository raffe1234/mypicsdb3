from __future__ import annotations

import mimetypes
import os
import socket
import time
import uuid
from typing import Callable, Dict, Iterable, List, Optional, Sequence, Tuple

from .config import Settings
from .db.catalog import Catalog
from .db.locks import SCAN_LOCK_NAME
from .filesystem import CancellationAwareFilesystem, Filesystem
from .metadata import extract_metadata
from .metadata_mapping import metadata_index_signature
from .models import MetadataResult, ScanStats, Source
from .scan_checkpoint import ScanCheckpointStore
from .source_scan_policy import SourceScanPolicy, source_scan_policy_from_settings
from .utils import basename_uri, extension_of, join_uri, local_datetime_from_timestamp, normalize_uri, utc_now


class ScanCancelled(Exception):
    pass


class ScanAlreadyRunning(RuntimeError):
    pass


class ScanLockLost(RuntimeError):
    pass


SCAN_LOCK_TTL_SECONDS = 1800
SCAN_LOCK_REFRESH_SECONDS = 60


SLOW_IO_WARNING_SECONDS = 5.0


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
        started: Optional[Callable[[ScanStats], None]] = None,
        checkpoint_store: Optional[ScanCheckpointStore] = None,
    ):
        self.catalog = catalog
        self.settings = settings
        self.logger = logger
        self.metadata_reader = metadata_reader
        self._uses_default_metadata_reader = metadata_reader is extract_metadata
        self.cancelled = cancelled or (lambda: False)
        self.progress = progress
        self.started = started
        self.checkpoints = checkpoint_store or ScanCheckpointStore(settings, logger)
        self.owner = "%s:%s:%s" % (socket.gethostname(), os.getpid(), uuid.uuid4().hex[:12])
        self._scan_lock_active = False
        self._scan_lock_refreshed_at = 0.0
        self._scan_connection = None
        self._source_policies: Dict[int, SourceScanPolicy] = {}
        self._metadata_mapping_overrides = ()
        self._metadata_index_hash = metadata_index_signature(self.settings, ())
        self.filesystem = CancellationAwareFilesystem(filesystem, self._check_cancelled)

    def _effective_source_policy(self, source: Source) -> SourceScanPolicy:
        explicit = self.catalog.get_source_scan_policy(source.id)
        return explicit if explicit is not None else source_scan_policy_from_settings(self.settings)

    def _is_excluded(self, path: str, name: str, policy: SourceScanPolicy) -> bool:
        if policy.exclude_hidden and name.startswith("."):
            return True
        lower = path.casefold()
        return any(fragment in lower for fragment in policy.exclude_fragments)

    @staticmethod
    def _is_synology_metadata_directory(path: str, name: str) -> bool:
        """Always ignore Synology @eaDir metadata trees.

        This is deliberately independent of the user-editable exclusion list.
        Existing profiles may have an empty or older saved value, while these
        directories never contain original library media.
        """
        candidates = (name, basename_uri(path))
        return any(
            candidate.rstrip("/\\").casefold().endswith("@eadir")
            for candidate in candidates
        )

    def _is_excluded_directory(self, path: str, name: str, policy: SourceScanPolicy) -> bool:
        return self._is_synology_metadata_directory(path, name) or self._is_excluded(path, name, policy)

    def _check_cancelled(self) -> None:
        if self.cancelled():
            raise ScanCancelled()
        self._refresh_scan_lock()

    def _refresh_scan_lock(self, force: bool = False) -> None:
        if not self._scan_lock_active:
            return
        now = time.monotonic()
        if not force and now - self._scan_lock_refreshed_at < SCAN_LOCK_REFRESH_SECONDS:
            return
        try:
            refreshed = self.catalog.refresh_lock(
                SCAN_LOCK_NAME,
                self.owner,
                SCAN_LOCK_TTL_SECONDS,
                connection=self._scan_connection,
            )
        except Exception as exc:
            raise ScanLockLost("The catalogue scan lock could not be refreshed") from exc
        if not refreshed:
            raise ScanLockLost("The catalogue scan lock expired or was taken over")
        if self._scan_connection is not None:
            self._scan_connection.commit()
        self._scan_lock_refreshed_at = now

    def scan_sources(self, source_ids: Optional[Sequence[int]] = None) -> ScanStats:
        overall = ScanStats(started_at=utc_now())
        started_monotonic = time.monotonic()
        self._check_cancelled()
        sources = self.catalog.get_sources(enabled_only=True)
        if source_ids is not None:
            wanted = {int(value) for value in source_ids}
            sources = [source for source in sources if source.id in wanted]
        if not sources:
            overall.finished_at = utc_now()
            overall.duration_seconds = time.monotonic() - started_monotonic
            return overall
        if not self.catalog.acquire_lock(SCAN_LOCK_NAME, self.owner, SCAN_LOCK_TTL_SECONDS):
            raise ScanAlreadyRunning("Another scan is already running")
        self._scan_lock_active = True
        self._scan_lock_refreshed_at = time.monotonic()
        scan_completed = False
        try:
            self._source_policies = {
                int(source.id): self._effective_source_policy(source) for source in sources
            }
            mapping_getter = getattr(self.catalog, "list_metadata_mapping_overrides", None)
            overrides = mapping_getter() if callable(mapping_getter) else ()
            self._metadata_mapping_overrides = tuple(overrides)
            self._metadata_index_hash = metadata_index_signature(self.settings, overrides)
            overall = self.checkpoints.prepare(
                sources,
                overall,
                self._source_policies,
                self._metadata_index_hash,
            )
            completed_sources = self.checkpoints.completed_source_ids()
            if self.started:
                self.started(overall)
            self._check_cancelled()
            for source in sources:
                if int(source.id) in completed_sources:
                    continue
                self._check_cancelled()
                source_stats = self.scan_source(
                    source, self._source_policies[int(source.id)]
                )
                overall.merge(source_stats)
                self.checkpoints.complete_source(source.id, overall)
                completed_sources.add(int(source.id))
            scan_completed = True
        except ScanCancelled:
            partial = self.checkpoints.current_stats()
            if partial is not None:
                overall.merge(partial)
            overall.cancelled = True
        finally:
            if scan_completed:
                self.checkpoints.finish()
            try:
                self.catalog.release_lock(SCAN_LOCK_NAME, self.owner)
            finally:
                self._scan_lock_active = False
        overall.finished_at = utc_now()
        overall.duration_seconds = time.monotonic() - started_monotonic
        return overall

    def scan_source(
        self, source: Source, policy: Optional[SourceScanPolicy] = None
    ) -> ScanStats:
        started_monotonic = time.monotonic()
        scan_id = self.catalog.begin_scan_run(source.id)
        policy = policy or self._effective_source_policy(source)
        if not self._scan_lock_active:
            mapping_getter = getattr(self.catalog, "list_metadata_mapping_overrides", None)
            overrides = mapping_getter() if callable(mapping_getter) else ()
            self._metadata_mapping_overrides = tuple(overrides)
            self._metadata_index_hash = metadata_index_signature(self.settings, overrides)
        root = normalize_uri(source.uri, directory=True)
        restored = self.checkpoints.restore_source(source)
        if restored is None:
            scan_started_at = utc_now()
            stats = ScanStats(sources_total=1, started_at=scan_started_at)
            stack: List[Tuple[str, str, str]] = [(root, "", source.label)]
            traversal_complete = True
        else:
            scan_started_at, stack, stats, traversal_complete = restored
            stats.sources_total = max(1, int(stats.sources_total or 0))
            if self.logger:
                self.logger.info(
                    "Resuming source scan for %s with %d folders pending",
                    source.label,
                    len(stack),
                )
        stats.scan_id = scan_id
        if not self.filesystem.exists(root):
            stats.sources_unavailable = 1
            stats.errors += 1
            message = "Source unavailable: %s" % root
            stats.error_messages.append(message)
            self.catalog.set_source_scan_state(source.id, False, "unavailable", message)
            self.catalog.finish_scan_run(scan_id, "unavailable", stats, message)
            stats.finished_at = utc_now()
            stats.duration_seconds = time.monotonic() - started_monotonic
            return stats

        connection = self.catalog.open_scan_connection()
        self._scan_connection = connection
        changed_since_commit = 0
        try:
            if restored is None:
                self.checkpoints.begin_source(
                    source,
                    scan_started_at,
                    stack,
                    stats,
                    traversal_complete,
                )
            visited = set()

            def save_folder_checkpoint() -> None:
                nonlocal changed_since_commit
                connection.commit()
                changed_since_commit = 0
                self.checkpoints.update_source(
                    source,
                    scan_started_at,
                    stack,
                    stats,
                    traversal_complete,
                )

            while stack:
                self._check_cancelled()
                folder_uri, parent_uri, folder_name = stack.pop()
                folder_uri = normalize_uri(folder_uri, directory=True)
                if folder_uri in visited:
                    save_folder_checkpoint()
                    continue
                visited.add(folder_uri)
                if self._is_excluded_directory(folder_uri, folder_name, policy):
                    save_folder_checkpoint()
                    continue
                folder_id = self.catalog.upsert_folder(connection, source.id, folder_uri, parent_uri, folder_name, scan_started_at)
                stats.folders_seen += 1
                changed_since_commit += 1
                try:
                    list_started = time.monotonic()
                    directories, files = self.filesystem.listdir(folder_uri)
                    list_duration = time.monotonic() - list_started
                    if self.logger and list_duration >= SLOW_IO_WARNING_SECONDS:
                        self.logger.warning(
                            "Slow directory listing: %.1fs for %s",
                            list_duration,
                            folder_uri,
                        )
                except Exception as exc:
                    traversal_complete = False
                    stats.errors += 1
                    stats.error_messages.append("Cannot list %s: %s" % (folder_uri, exc))
                    if self.logger:
                        self.logger.warning("Cannot list %s: %s", folder_uri, exc)
                    save_folder_checkpoint()
                    continue

                if policy.recursive:
                    for directory in sorted(directories, reverse=True):
                        child_uri = join_uri(folder_uri, directory, directory=True)
                        if not self._is_excluded_directory(child_uri, directory, policy):
                            stack.append((child_uri, folder_uri, directory))

                for filename in sorted(files):
                    self._check_cancelled()
                    picture_uri = join_uri(folder_uri, filename)
                    if self._is_excluded(picture_uri, filename, policy):
                        continue
                    extension = extension_of(filename)
                    if extension in policy.picture_extensions:
                        media_type = "picture"
                    elif policy.include_videos and extension in policy.video_extensions:
                        media_type = "video"
                    else:
                        continue
                    stats.pictures_seen += 1
                    if self.progress:
                        self.progress(source, picture_uri, stats)
                    existing = self.catalog.find_picture(connection, picture_uri)
                    try:
                        file_stat = self.filesystem.stat(picture_uri)
                        if (
                            existing
                            and str(existing.get("media_type") or "picture") == media_type
                            and int(existing["file_size"]) == file_stat.size
                            and abs(float(existing["file_mtime"]) - file_stat.mtime) < 0.001
                            and str(existing.get("metadata_index_hash") or "")
                            == self._metadata_index_hash
                        ):
                            self.catalog.touch_picture(connection, int(existing["id"]), folder_id, source.id, scan_started_at)
                            stats.pictures_unchanged += 1
                        else:
                            if media_type == "picture":
                                metadata_started = time.monotonic()
                                if self._uses_default_metadata_reader:
                                    metadata = extract_metadata(
                                        picture_uri,
                                        self.filesystem,
                                        self.settings,
                                        file_stat.size,
                                        mapping_rules=self._metadata_mapping_overrides,
                                    )
                                else:
                                    metadata = self.metadata_reader(
                                        picture_uri,
                                        self.filesystem,
                                        self.settings,
                                        file_stat.size,
                                    )
                                metadata_duration = time.monotonic() - metadata_started
                                if self.logger and metadata_duration >= SLOW_IO_WARNING_SECONDS:
                                    self.logger.warning(
                                        "Slow media inspection: %.1fs for %s",
                                        metadata_duration,
                                        picture_uri,
                                    )
                                self._check_cancelled()
                            else:
                                metadata = MetadataResult(
                                    mime_type=mimetypes.guess_type(filename)[0]
                                    or "video/%s" % extension,
                                )
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
                                "media_type": media_type,
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
                                "metadata_index_hash": self._metadata_index_hash,
                                # Still pictures use their original URI. Videos leave the
                                # artwork field empty so the browser can request Kodi's
                                # native ``image://video@...`` generated-frame loader.
                                "thumb_uri": picture_uri if media_type == "picture" else None,
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
                    except (ScanCancelled, ScanLockLost):
                        raise
                    except Exception as exc:
                        # The directory entry proves an existing catalogue row is
                        # still present even when stat or metadata access fails.
                        # Touch it so a transient SMB/VFS error cannot turn it
                        # into a missing record at the end of this scan.
                        if existing:
                            self.catalog.touch_picture(
                                connection,
                                int(existing["id"]),
                                folder_id,
                                source.id,
                                scan_started_at,
                            )
                            changed_since_commit += 1
                        stats.errors += 1
                        message = "%s: %s" % (picture_uri, exc)
                        stats.error_messages.append(message)
                        if self.logger:
                            self.logger.warning("Media scan error for %s: %s", picture_uri, exc)

                # A checkpoint is only advanced after every catalogue change
                # for this folder has been committed. If Kodi stops during the
                # next folder, the saved stack still contains that folder and
                # it is safely processed again on the next matching scan.
                save_folder_checkpoint()

            self._check_cancelled()
            if traversal_complete:
                stats.missing_marked = self.catalog.mark_missing_after_scan(
                    connection, source.id, scan_started_at
                )
                status = "completed" if stats.errors == 0 else "completed_with_errors"
            else:
                # Missing detection is source-wide and must only run after a
                # complete traversal. One unreadable folder may hide an entire
                # subtree, so preserving all previously indexed rows is safer
                # than guessing which unseen paths were actually deleted.
                status = "partial"
                safety_message = (
                    "Incomplete source traversal; missing-record marking was skipped"
                )
                stats.error_messages.append(safety_message)
                if self.logger:
                    self.logger.warning("%s: %s", root, safety_message)
            self.catalog.update_folder_summaries(connection, source.id)
            connection.commit()
            stats.sources_scanned = 1
            message = "\n".join(stats.error_messages[-5:]) or None
            self.catalog.set_source_scan_state(source.id, True, status, message)
            self.catalog.finish_scan_run(scan_id, status, stats, message)
        except ScanCancelled:
            connection.commit()
            stats.cancelled = True
            self.catalog.set_source_scan_state(source.id, True, "cancelled")
            self.catalog.finish_scan_run(scan_id, "cancelled", stats)
            raise
        except ScanLockLost as exc:
            connection.rollback()
            stats.errors += 1
            stats.error_messages.append(str(exc))
            self.catalog.set_source_scan_state(source.id, True, "failed", str(exc))
            self.catalog.finish_scan_run(scan_id, "failed", stats, str(exc))
            if self.logger:
                self.logger.error("Source scan lost its lock for %s: %s", root, exc)
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
            self._scan_connection = None
            connection.close()
            stats.finished_at = utc_now()
            stats.duration_seconds = time.monotonic() - started_monotonic
        return stats
