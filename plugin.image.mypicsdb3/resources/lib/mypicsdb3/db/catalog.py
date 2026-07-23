from __future__ import annotations

import random
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from ..models import Source
from ..utils import (
    NON_INDEXABLE_PICTURE_SOURCE_URIS,
    is_indexable_picture_source_uri,
    normalize_uri,
    sha256_text,
    utc_now,
)
from .engine import DatabaseEngine
from .locks import acquire_lock as acquire_catalog_lock
from .locks import refresh_lock as refresh_catalog_lock
from .locks import release_lock as release_catalog_lock
from .migrations import MigrationRunner


PICTURE_COLUMNS = """
p.id, p.source_id, p.folder_id, p.uri, p.filename, p.extension, p.file_size,
p.file_mtime, p.discovered_at, p.last_seen_at, p.taken_at, p.taken_source,
p.taken_year, p.taken_month, p.taken_day, p.width, p.height, p.orientation,
p.mime_type, p.camera_make, p.camera_model, p.rating, p.gps_latitude,
p.gps_longitude, p.city, p.state, p.country, p.sublocation, p.caption,
p.thumb_uri, p.favorite, f.name AS folder_name, f.uri AS folder_uri,
s.label AS source_label
"""


class Catalog:
    def __init__(self, engine: DatabaseEngine, logger=None):
        self.engine = engine
        self.logger = logger

    def initialize(self):
        return MigrationRunner(self.engine, logger=self.logger).initialize()

    def test_connection(self) -> None:
        self.engine.test_connection()

    def sync_sources(self, kodi_sources: Sequence[Dict[str, str]]) -> List[Source]:
        now = utc_now()
        hashes = []
        with self.engine.transaction() as connection:
            ignored_hashes = tuple(sha256_text(uri) for uri in NON_INDEXABLE_PICTURE_SOURCE_URIS)
            if ignored_hashes:
                placeholders = ",".join("?" for _ in ignored_hashes)
                cursor = self.engine.execute(
                    connection,
                    "DELETE FROM sources WHERE uri_hash IN (%s)" % placeholders,
                    ignored_hashes,
                )
                try:
                    removed_ignored_sources = int(cursor.rowcount or 0) > 0
                finally:
                    cursor.close()
                if removed_ignored_sources:
                    self.engine.execute(
                        connection,
                        "DELETE FROM tags WHERE NOT EXISTS (SELECT 1 FROM picture_tags WHERE picture_tags.tag_id=tags.id)",
                    ).close()
            for source in kodi_sources:
                uri = normalize_uri(source["uri"], directory=True)
                if not is_indexable_picture_source_uri(uri):
                    continue
                uri_hash = sha256_text(uri)
                hashes.append(uri_hash)
                existing = self.engine.fetchone(connection, "SELECT id FROM sources WHERE uri_hash=?", (uri_hash,))
                if existing:
                    self.engine.execute(
                        connection,
                        "UPDATE sources SET label=?, uri=?, available=1, updated_at=? WHERE id=?",
                        (source.get("label") or uri, uri, now, existing["id"]),
                    ).close()
                else:
                    self.engine.execute(
                        connection,
                        "INSERT INTO sources (label, uri, uri_hash, enabled, available, created_at, updated_at) VALUES (?, ?, ?, 0, 1, ?, ?)",
                        (source.get("label") or uri, uri, uri_hash, now, now),
                    ).close()
            if hashes:
                placeholders = ",".join("?" for _ in hashes)
                self.engine.execute(connection, "UPDATE sources SET available=0, updated_at=? WHERE uri_hash NOT IN (%s)" % placeholders, (now, *hashes)).close()
            else:
                self.engine.execute(connection, "UPDATE sources SET available=0, updated_at=?", (now,)).close()
        return self.get_sources()

    def get_sources(self, enabled_only: bool = False) -> List[Source]:
        query = "SELECT id, label, uri, enabled, available, last_scan_at, last_scan_status FROM sources"
        params: Tuple[Any, ...] = ()
        if enabled_only:
            query += " WHERE enabled=1"
        query += " ORDER BY label COLLATE NOCASE" if self.engine.backend == "sqlite" else " ORDER BY label"
        with self.engine.transaction() as connection:
            rows = self.engine.fetchall(connection, query, params)
        return [Source(
            id=int(row["id"]), label=row["label"], uri=row["uri"],
            enabled=bool(row["enabled"]), available=bool(row["available"]),
            last_scan_at=str(row["last_scan_at"]) if row.get("last_scan_at") else None,
            last_scan_status=row.get("last_scan_status"),
        ) for row in rows]

    def get_source(self, source_id: int) -> Optional[Source]:
        with self.engine.transaction() as connection:
            row = self.engine.fetchone(connection, "SELECT id, label, uri, enabled, available, last_scan_at, last_scan_status FROM sources WHERE id=?", (source_id,))
        if not row:
            return None
        return Source(int(row["id"]), row["label"], row["uri"], bool(row["enabled"]), bool(row["available"]), row.get("last_scan_at"), row.get("last_scan_status"))

    def set_source_enabled(self, source_id: int, enabled: bool) -> None:
        with self.engine.transaction() as connection:
            self.engine.execute(connection, "UPDATE sources SET enabled=?, updated_at=? WHERE id=?", (1 if enabled else 0, utc_now(), source_id)).close()

    def delete_source(self, source_id: int) -> bool:
        """Delete a source and the catalogue rows that belong to it.

        Folder and picture rows are removed by the database's foreign-key
        cascades. Orphaned tags are then cleaned up explicitly because tags can
        be shared by pictures from several sources.
        """
        with self.engine.transaction() as connection:
            cursor = self.engine.execute(connection, "DELETE FROM sources WHERE id=?", (source_id,))
            try:
                deleted = int(cursor.rowcount or 0) > 0
            finally:
                cursor.close()
            if deleted:
                self.engine.execute(
                    connection,
                    "DELETE FROM tags WHERE NOT EXISTS (SELECT 1 FROM picture_tags WHERE picture_tags.tag_id=tags.id)",
                ).close()
        return deleted

    def set_source_scan_state(self, source_id: int, available: bool, status: str, error: Optional[str] = None) -> None:
        with self.engine.transaction() as connection:
            self.engine.execute(
                connection,
                "UPDATE sources SET available=?, last_scan_at=?, last_scan_status=?, last_error=?, updated_at=? WHERE id=?",
                (1 if available else 0, utc_now(), status, error, utc_now(), source_id),
            ).close()

    def acquire_lock(self, name: str, owner: str, ttl_seconds: int = 1800) -> bool:
        return acquire_catalog_lock(self.engine, name, owner, ttl_seconds)

    def refresh_lock(self, name: str, owner: str, ttl_seconds: int = 1800, connection=None) -> bool:
        return refresh_catalog_lock(
            self.engine,
            name,
            owner,
            ttl_seconds,
            connection=connection,
        )

    def release_lock(self, name: str, owner: str) -> None:
        release_catalog_lock(self.engine, name, owner)

    def begin_scan_run(self, source_id: Optional[int]) -> int:
        with self.engine.transaction() as connection:
            cursor = self.engine.execute(connection, "INSERT INTO scan_runs (source_id, started_at, status) VALUES (?, ?, 'running')", (source_id, utc_now()))
            try:
                return int(cursor.lastrowid)
            finally:
                cursor.close()

    def finish_scan_run(self, scan_id: int, status: str, stats, message: Optional[str] = None) -> None:
        with self.engine.transaction() as connection:
            self.engine.execute(
                connection,
                "UPDATE scan_runs SET finished_at=?, status=?, pictures_seen=?, pictures_added=?, pictures_updated=?, pictures_unchanged=?, errors=?, message=? WHERE id=?",
                (utc_now(), status, stats.pictures_seen, stats.pictures_added, stats.pictures_updated, stats.pictures_unchanged, stats.errors, message, scan_id),
            ).close()

    def latest_scan(self) -> Optional[Dict[str, Any]]:
        with self.engine.transaction() as connection:
            return self.engine.fetchone(connection, "SELECT r.*, s.label AS source_label FROM scan_runs r LEFT JOIN sources s ON s.id=r.source_id ORDER BY r.id DESC LIMIT 1")

    def overview(self) -> Dict[str, Any]:
        with self.engine.transaction() as connection:
            pictures = self.engine.fetchone(connection, "SELECT COUNT(*) AS total, SUM(CASE WHEN is_missing=1 THEN 1 ELSE 0 END) AS missing FROM pictures") or {}
            folders = self.engine.fetchone(connection, "SELECT COUNT(*) AS total FROM folders WHERE is_missing=0") or {}
            sources = self.engine.fetchone(connection, "SELECT COUNT(*) AS total, SUM(CASE WHEN enabled=1 THEN 1 ELSE 0 END) AS enabled FROM sources") or {}
        return {
            "pictures": int(pictures.get("total") or 0),
            "missing": int(pictures.get("missing") or 0),
            "folders": int(folders.get("total") or 0),
            "sources": int(sources.get("total") or 0),
            "enabled_sources": int(sources.get("enabled") or 0),
            "backend": self.engine.backend,
        }

    # Scanner-facing methods -------------------------------------------------

    def open_scan_connection(self):
        return self.engine.connect()

    def upsert_folder(self, connection, source_id: int, uri: str, parent_uri: str, name: str, seen_at: str) -> int:
        uri_hash = sha256_text(uri)
        row = self.engine.fetchone(connection, "SELECT id FROM folders WHERE uri_hash=?", (uri_hash,))
        if row:
            self.engine.execute(connection, "UPDATE folders SET source_id=?, parent_uri=?, uri=?, name=?, last_seen_at=?, is_missing=0, missing_since=NULL WHERE id=?", (source_id, parent_uri, uri, name, seen_at, row["id"])).close()
            return int(row["id"])
        cursor = self.engine.execute(
            connection,
            "INSERT INTO folders (source_id, parent_uri, uri, uri_hash, name, discovered_at, last_seen_at, random_key, is_missing) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0)",
            (source_id, parent_uri, uri, uri_hash, name, seen_at, seen_at, random.random()),
        )
        try:
            return int(cursor.lastrowid)
        finally:
            cursor.close()

    def find_picture(self, connection, uri: str) -> Optional[Dict[str, Any]]:
        return self.engine.fetchone(connection, "SELECT id, file_size, file_mtime, metadata_hash, favorite, discovered_at FROM pictures WHERE uri_hash=?", (sha256_text(uri),))

    def touch_picture(self, connection, picture_id: int, folder_id: int, source_id: int, seen_at: str) -> None:
        self.engine.execute(connection, "UPDATE pictures SET folder_id=?, source_id=?, last_seen_at=?, is_missing=0, missing_since=NULL WHERE id=?", (folder_id, source_id, seen_at, picture_id)).close()

    @staticmethod
    def _date_parts(taken_at: Optional[str]) -> Tuple[Optional[int], Optional[int], Optional[int]]:
        if not taken_at or len(taken_at) < 10:
            return None, None, None
        try:
            return int(taken_at[0:4]), int(taken_at[5:7]), int(taken_at[8:10])
        except ValueError:
            return None, None, None

    def insert_picture(self, connection, record: Dict[str, Any], keywords: Iterable[str]) -> int:
        year, month, day = self._date_parts(record.get("taken_at"))
        fields = (
            record["source_id"], record["folder_id"], record["uri"], sha256_text(record["uri"]), record["filename"],
            record["extension"], record["file_size"], record["file_mtime"], record["discovered_at"], record["last_seen_at"],
            record.get("taken_at"), record.get("taken_source"), year, month, day, record.get("width"), record.get("height"),
            record.get("orientation"), record.get("mime_type"), record.get("camera_make"), record.get("camera_model"),
            record.get("rating"), record.get("gps_latitude"), record.get("gps_longitude"), record.get("city"), record.get("state"),
            record.get("country"), record.get("sublocation"), record.get("caption"), record.get("metadata_hash"), record.get("thumb_uri"),
            random.random(),
        )
        cursor = self.engine.execute(connection, """INSERT INTO pictures (
            source_id, folder_id, uri, uri_hash, filename, extension, file_size, file_mtime,
            discovered_at, last_seen_at, taken_at, taken_source, taken_year, taken_month, taken_day,
            width, height, orientation, mime_type, camera_make, camera_model, rating,
            gps_latitude, gps_longitude, city, state, country, sublocation, caption,
            metadata_hash, thumb_uri, random_key, favorite, is_missing
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, 0)""", fields)
        try:
            picture_id = int(cursor.lastrowid)
        finally:
            cursor.close()
        self.replace_tags(connection, picture_id, keywords)
        return picture_id

    def update_picture(self, connection, picture_id: int, record: Dict[str, Any], keywords: Iterable[str]) -> None:
        year, month, day = self._date_parts(record.get("taken_at"))
        self.engine.execute(connection, """UPDATE pictures SET
            source_id=?, folder_id=?, uri=?, filename=?, extension=?, file_size=?, file_mtime=?, last_seen_at=?,
            taken_at=?, taken_source=?, taken_year=?, taken_month=?, taken_day=?, width=?, height=?, orientation=?,
            mime_type=?, camera_make=?, camera_model=?, rating=?, gps_latitude=?, gps_longitude=?, city=?, state=?,
            country=?, sublocation=?, caption=?, metadata_hash=?, thumb_uri=?, is_missing=0, missing_since=NULL
            WHERE id=?""", (
                record["source_id"], record["folder_id"], record["uri"], record["filename"], record["extension"],
                record["file_size"], record["file_mtime"], record["last_seen_at"], record.get("taken_at"),
                record.get("taken_source"), year, month, day, record.get("width"), record.get("height"),
                record.get("orientation"), record.get("mime_type"), record.get("camera_make"), record.get("camera_model"),
                record.get("rating"), record.get("gps_latitude"), record.get("gps_longitude"), record.get("city"),
                record.get("state"), record.get("country"), record.get("sublocation"), record.get("caption"),
                record.get("metadata_hash"), record.get("thumb_uri"), picture_id,
            )).close()
        self.replace_tags(connection, picture_id, keywords)

    def replace_tags(self, connection, picture_id: int, keywords: Iterable[str]) -> None:
        self.engine.execute(connection, "DELETE FROM picture_tags WHERE picture_id=?", (picture_id,)).close()
        for keyword in keywords:
            name = str(keyword).strip()[:191]
            normalized = name.casefold()
            if not name or not normalized:
                continue
            row = self.engine.fetchone(connection, "SELECT id FROM tags WHERE normalized_name=?", (normalized,))
            if row:
                tag_id = int(row["id"])
            else:
                try:
                    cursor = self.engine.execute(connection, "INSERT INTO tags (name, normalized_name) VALUES (?, ?)", (name, normalized))
                    tag_id = int(cursor.lastrowid)
                    cursor.close()
                except self.engine.integrity_errors:
                    row = self.engine.fetchone(connection, "SELECT id FROM tags WHERE normalized_name=?", (normalized,))
                    if not row:
                        continue
                    tag_id = int(row["id"])
            try:
                self.engine.execute(connection, "INSERT INTO picture_tags (picture_id, tag_id) VALUES (?, ?)", (picture_id, tag_id)).close()
            except self.engine.integrity_errors:
                pass

    def mark_missing_after_scan(self, connection, source_id: int, scan_started_at: str) -> int:
        now = utc_now()
        cursor = self.engine.execute(connection, "UPDATE pictures SET is_missing=1, missing_since=COALESCE(missing_since, ?) WHERE source_id=? AND last_seen_at<? AND is_missing=0", (now, source_id, scan_started_at))
        changed = int(cursor.rowcount or 0)
        cursor.close()
        self.engine.execute(connection, "UPDATE folders SET is_missing=1, missing_since=COALESCE(missing_since, ?) WHERE source_id=? AND last_seen_at<? AND is_missing=0", (now, source_id, scan_started_at)).close()
        return changed

    def update_folder_summaries(self, connection, source_id: int) -> None:
        folders = self.engine.fetchall(connection, "SELECT id FROM folders WHERE source_id=? AND is_missing=0", (source_id,))
        for folder in folders:
            recent = self.engine.fetchone(connection, "SELECT id, taken_at, discovered_at FROM pictures WHERE folder_id=? AND is_missing=0 ORDER BY COALESCE(taken_at, discovered_at) DESC, id DESC LIMIT 1", (folder["id"],))
            if recent:
                self.engine.execute(connection, "UPDATE folders SET representative_picture_id=?, latest_taken_at=?, latest_discovered_at=? WHERE id=?", (recent["id"], recent.get("taken_at"), recent.get("discovered_at"), folder["id"])).close()
            else:
                self.engine.execute(connection, "UPDATE folders SET representative_picture_id=NULL, latest_taken_at=NULL, latest_discovered_at=NULL WHERE id=?", (folder["id"],)).close()

    # Browser and widget queries --------------------------------------------

    def _pictures(self, where: str, params: Sequence[Any], order: str, limit: int, offset: int = 0) -> List[Dict[str, Any]]:
        query = "SELECT %s FROM pictures p JOIN folders f ON f.id=p.folder_id JOIN sources s ON s.id=p.source_id WHERE p.is_missing=0" % PICTURE_COLUMNS
        if where:
            query += " AND " + where
        query += " ORDER BY " + order + " LIMIT ? OFFSET ?"
        with self.engine.transaction() as connection:
            return self.engine.fetchall(connection, query, (*params, limit, offset))

    def recent_taken(self, limit: int, offset: int = 0) -> List[Dict[str, Any]]:
        return self._pictures("p.taken_at IS NOT NULL", (), "p.taken_at DESC, p.id DESC", limit, offset)

    def recent_added(self, limit: int, offset: int = 0) -> List[Dict[str, Any]]:
        return self._pictures("", (), "p.discovered_at DESC, p.id DESC", limit, offset)

    def favorites(self, limit: int, offset: int = 0) -> List[Dict[str, Any]]:
        return self._pictures("p.favorite=1", (), "COALESCE(p.taken_at, p.discovered_at) DESC", limit, offset)

    def rated(self, limit: int, offset: int = 0) -> List[Dict[str, Any]]:
        return self._pictures("p.rating IS NOT NULL AND p.rating>0", (), "p.rating DESC, COALESCE(p.taken_at, p.discovered_at) DESC", limit, offset)

    def geotagged(self, limit: int, offset: int = 0) -> List[Dict[str, Any]]:
        return self._pictures("p.gps_latitude IS NOT NULL AND p.gps_longitude IS NOT NULL", (), "COALESCE(p.taken_at, p.discovered_at) DESC", limit, offset)

    def on_this_day(self, month: int, day: int, current_year: int, limit: int, offset: int = 0) -> List[Dict[str, Any]]:
        return self._pictures("p.taken_month=? AND p.taken_day=? AND p.taken_year<?", (month, day, current_year), "p.taken_year DESC, p.taken_at DESC", limit, offset)

    def pictures_for_year(self, year: int, limit: int, offset: int = 0) -> List[Dict[str, Any]]:
        return self._pictures("p.taken_year=?", (year,), "p.taken_at DESC", limit, offset)

    def pictures_for_camera(self, camera_make: str, camera_model: str, limit: int, offset: int = 0) -> List[Dict[str, Any]]:
        return self._pictures("COALESCE(p.camera_make,'')=? AND COALESCE(p.camera_model,'')=?", (camera_make, camera_model), "COALESCE(p.taken_at, p.discovered_at) DESC", limit, offset)

    def pictures_for_tag(self, tag_id: int, limit: int, offset: int = 0) -> List[Dict[str, Any]]:
        where = "EXISTS (SELECT 1 FROM picture_tags pt WHERE pt.picture_id=p.id AND pt.tag_id=?)"
        return self._pictures(where, (tag_id,), "COALESCE(p.taken_at, p.discovered_at) DESC", limit, offset)

    def pictures_in_folder(self, folder_id: int, limit: int, offset: int = 0) -> List[Dict[str, Any]]:
        return self._pictures("p.folder_id=?", (folder_id,), "COALESCE(p.taken_at, p.discovered_at) DESC, p.filename", limit, offset)

    def random_pictures(self, limit: int) -> List[Dict[str, Any]]:
        seed = random.random()
        first = self._pictures("p.random_key>=?", (seed,), "p.random_key", limit, 0)
        if len(first) < limit:
            second = self._pictures("p.random_key<?", (seed,), "p.random_key", limit - len(first), 0)
            first.extend(second)
        return first

    def _folder_rows(self, where: str, params: Sequence[Any], order: str, limit: int, offset: int = 0) -> List[Dict[str, Any]]:
        query = """SELECT f.*, p.uri AS representative_uri, p.thumb_uri AS representative_thumb,
                   (SELECT COUNT(*) FROM pictures pc WHERE pc.folder_id=f.id AND pc.is_missing=0) AS picture_count,
                   s.label AS source_label
                   FROM folders f
                   JOIN sources s ON s.id=f.source_id
                   LEFT JOIN pictures p ON p.id=f.representative_picture_id
                   WHERE f.is_missing=0"""
        if where:
            query += " AND " + where
        query += " ORDER BY " + order + " LIMIT ? OFFSET ?"
        with self.engine.transaction() as connection:
            return self.engine.fetchall(connection, query, (*params, limit, offset))

    def recent_folders(self, limit: int, offset: int = 0) -> List[Dict[str, Any]]:
        return self._folder_rows("f.representative_picture_id IS NOT NULL", (), "f.latest_discovered_at DESC, f.id DESC", limit, offset)

    def random_folders(self, limit: int) -> List[Dict[str, Any]]:
        seed = random.random()
        first = self._folder_rows("f.representative_picture_id IS NOT NULL AND f.random_key>=?", (seed,), "f.random_key", limit)
        if len(first) < limit:
            first.extend(self._folder_rows("f.representative_picture_id IS NOT NULL AND f.random_key<?", (seed,), "f.random_key", limit - len(first)))
        return first

    def source_root_folders(self, source_id: int) -> List[Dict[str, Any]]:
        return self._folder_rows("f.source_id=? AND f.parent_uri=''", (source_id,), "f.name", 1000)

    def child_folders(self, source_id: int, parent_uri: str, limit: int = 1000) -> List[Dict[str, Any]]:
        return self._folder_rows("f.source_id=? AND f.parent_uri=?", (source_id, parent_uri), "f.name", limit)

    def get_folder(self, folder_id: int) -> Optional[Dict[str, Any]]:
        with self.engine.transaction() as connection:
            return self.engine.fetchone(connection, "SELECT f.*, s.label AS source_label FROM folders f JOIN sources s ON s.id=f.source_id WHERE f.id=?", (folder_id,))

    def years(self) -> List[Dict[str, Any]]:
        with self.engine.transaction() as connection:
            groups = self.engine.fetchall(connection, "SELECT taken_year AS year, COUNT(*) AS picture_count FROM pictures WHERE is_missing=0 AND taken_year IS NOT NULL GROUP BY taken_year ORDER BY taken_year DESC")
            for group in groups:
                rep = self.engine.fetchone(connection, "SELECT uri, thumb_uri FROM pictures WHERE is_missing=0 AND taken_year=? ORDER BY taken_at DESC LIMIT 1", (group["year"],))
                group.update(rep or {})
            return groups

    def cameras(self) -> List[Dict[str, Any]]:
        with self.engine.transaction() as connection:
            groups = self.engine.fetchall(connection, """SELECT COALESCE(camera_make,'') AS camera_make, COALESCE(camera_model,'') AS camera_model, COUNT(*) AS picture_count
                FROM pictures WHERE is_missing=0 AND (camera_make IS NOT NULL OR camera_model IS NOT NULL)
                GROUP BY COALESCE(camera_make,''), COALESCE(camera_model,'') ORDER BY picture_count DESC, camera_make, camera_model""")
            for group in groups:
                rep = self.engine.fetchone(connection, "SELECT uri, thumb_uri FROM pictures WHERE is_missing=0 AND COALESCE(camera_make,'')=? AND COALESCE(camera_model,'')=? ORDER BY COALESCE(taken_at, discovered_at) DESC LIMIT 1", (group["camera_make"], group["camera_model"]))
                group.update(rep or {})
            return groups

    def tags(self) -> List[Dict[str, Any]]:
        with self.engine.transaction() as connection:
            groups = self.engine.fetchall(connection, """SELECT t.id, t.name, COUNT(*) AS picture_count
                FROM tags t JOIN picture_tags pt ON pt.tag_id=t.id JOIN pictures p ON p.id=pt.picture_id
                WHERE p.is_missing=0 GROUP BY t.id, t.name ORDER BY picture_count DESC, t.name""")
            for group in groups:
                rep = self.engine.fetchone(connection, """SELECT p.uri, p.thumb_uri FROM pictures p JOIN picture_tags pt ON pt.picture_id=p.id
                    WHERE p.is_missing=0 AND pt.tag_id=? ORDER BY COALESCE(p.taken_at, p.discovered_at) DESC LIMIT 1""", (group["id"],))
                group.update(rep or {})
            return groups

    def toggle_favorite(self, picture_id: int) -> bool:
        with self.engine.transaction() as connection:
            row = self.engine.fetchone(connection, "SELECT favorite FROM pictures WHERE id=?", (picture_id,))
            if not row:
                return False
            value = 0 if row["favorite"] else 1
            self.engine.execute(connection, "UPDATE pictures SET favorite=? WHERE id=?", (value, picture_id)).close()
            return bool(value)

    def cleanup_missing(self, retention_days: int) -> int:
        cutoff = (datetime.now(timezone.utc) - timedelta(days=retention_days)).strftime("%Y-%m-%d %H:%M:%S.%f")
        with self.engine.transaction() as connection:
            cursor = self.engine.execute(connection, "DELETE FROM pictures WHERE is_missing=1 AND missing_since IS NOT NULL AND missing_since<=?", (cutoff,))
            count = int(cursor.rowcount or 0)
            cursor.close()
            self.engine.execute(connection, "DELETE FROM folders WHERE is_missing=1 AND missing_since IS NOT NULL AND missing_since<=? AND id NOT IN (SELECT DISTINCT folder_id FROM pictures)", (cutoff,)).close()
            self.engine.execute(connection, "DELETE FROM tags WHERE id NOT IN (SELECT DISTINCT tag_id FROM picture_tags)").close()
            return count
