from __future__ import annotations

import random
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from ..models import Source
from ..metadata_mapping import (
    MetadataMappingRule,
    normalize_mapping_rule,
    normalize_source_tag,
    normalize_source_type,
)
from ..source_scan_policy import (
    SourceScanPolicy,
    decode_policy_list,
    encode_policy_list,
    normalize_source_scan_policy,
)
from ..query_model import (
    canonical_picture_query_json,
    compile_picture_query,
    parse_picture_query,
    picture_query_to_dict,
)
from ..music_playlists import (
    MUSIC_TARGET_MANUAL,
    MUSIC_TARGET_SMART,
    MusicPlaylistValidationError,
    normalize_music_playlist_uri,
    normalize_music_target_type,
)
from ..rating_policy import RATING_POLICY_ALL, normalize_rating_policy, rating_sql_predicate
from ..saved_searches import (
    SavedSearch,
    SavedSearchValidationError,
    normalize_saved_search_name,
    parse_stored_saved_search,
)
from ..static_collections import (
    CollectionValidationError,
    StaticCollection,
    normalize_collection_name,
    parse_stored_collection,
)
from ..search_index import build_picture_search_document
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
p.id, p.source_id, p.folder_id, p.uri, p.filename, p.extension, p.media_type, p.file_size,
p.file_mtime, p.discovered_at, p.last_seen_at, p.taken_at, p.taken_source,
p.taken_year, p.taken_month, p.taken_day, p.width, p.height, p.orientation,
p.mime_type, p.camera_make, p.camera_model, p.rating, p.gps_latitude,
p.gps_longitude, p.city, p.state, p.country, p.sublocation, p.caption,
p.thumb_uri, p.favorite, f.name AS folder_name, f.uri AS folder_uri,
s.label AS source_label
"""


QUERY_FACET_EXPRESSIONS = {
    "extension": "NULLIF(LOWER(TRIM(p.extension)),'')",
    "mime_type": "NULLIF(LOWER(TRIM(p.mime_type)),'')",
    "camera_make": "NULLIF(TRIM(p.camera_make),'')",
    "camera_model": "NULLIF(TRIM(p.camera_model),'')",
    "country": "NULLIF(TRIM(p.country),'')",
    "state": "NULLIF(TRIM(p.state),'')",
    "city": "NULLIF(TRIM(p.city),'')",
    "sublocation": "NULLIF(TRIM(p.sublocation),'')",
    "taken_year": "p.taken_year",
    "rating": "p.rating",
    "aspect": (
        "CASE "
        "WHEN p.width IS NULL OR p.height IS NULL OR p.width<=0 OR p.height<=0 THEN NULL "
        "WHEN (CASE WHEN p.orientation IN (5,6,7,8) THEN p.height ELSE p.width END) "
        "> (CASE WHEN p.orientation IN (5,6,7,8) THEN p.width ELSE p.height END) THEN 'landscape' "
        "WHEN (CASE WHEN p.orientation IN (5,6,7,8) THEN p.height ELSE p.width END) "
        "< (CASE WHEN p.orientation IN (5,6,7,8) THEN p.width ELSE p.height END) THEN 'portrait' "
        "ELSE 'square' END"
    ),
}


class Catalog:
    def __init__(self, engine: DatabaseEngine, logger=None, rating_policy: str = RATING_POLICY_ALL):
        self.engine = engine
        self.logger = logger
        self.rating_policy = normalize_rating_policy(rating_policy)

    def set_rating_policy(self, rating_policy: str) -> None:
        self.rating_policy = normalize_rating_policy(rating_policy)

    def _rating_predicate(
        self,
        column: str = "p.rating",
        media_type_column: Optional[str] = None,
    ) -> Tuple[str, Sequence[Any]]:
        predicate, params = rating_sql_predicate(self.rating_policy, column)
        if predicate and media_type_column:
            predicate = "(%s='video' OR %s)" % (media_type_column, predicate)
        return predicate, params

    def _apply_rating_policy(
        self,
        where: str,
        params: Sequence[Any],
        column: str = "p.rating",
    ) -> Tuple[str, Tuple[Any, ...]]:
        predicate, policy_params = self._rating_predicate(column, "p.media_type")
        if predicate:
            where = "(%s) AND %s" % (where, predicate) if where else predicate
        return where, (*params, *policy_params)

    def initialize(self):
        return MigrationRunner(self.engine, logger=self.logger).initialize()

    def test_connection(self) -> None:
        self.engine.test_connection()

    def list_saved_searches(self) -> List[Dict[str, Any]]:
        order = (
            "ss.name COLLATE NOCASE, ss.id"
            if self.engine.backend == "sqlite"
            else "ss.name, ss.id"
        )
        with self.engine.transaction() as connection:
            rows = self.engine.fetchall(
                connection,
                "SELECT ss.id, ss.name, ss.query_version, ss.created_at, "
                "ss.updated_at, cmp.playlist_uri AS music_playlist_uri "
                "FROM saved_searches ss LEFT JOIN collection_music_playlists cmp "
                "ON cmp.collection_type='smart' AND cmp.collection_id=ss.id "
                "ORDER BY %s" % order,
            )
        for row in rows:
            if not row.get("music_playlist_uri"):
                row.pop("music_playlist_uri", None)
        return rows

    def get_saved_search(self, saved_search_id: int) -> Optional[SavedSearch]:
        with self.engine.transaction() as connection:
            row = self.engine.fetchone(
                connection,
                "SELECT id, name, query_version, query_json, created_at, updated_at "
                "FROM saved_searches WHERE id=?",
                (saved_search_id,),
            )
        return parse_stored_saved_search(row) if row is not None else None

    def get_saved_search_summary(self, saved_search_id: int) -> Optional[Dict[str, Any]]:
        with self.engine.transaction() as connection:
            return self.engine.fetchone(
                connection,
                "SELECT ss.id, ss.name, ss.query_version, ss.created_at, "
                "ss.updated_at, cmp.playlist_uri AS music_playlist_uri "
                "FROM saved_searches ss LEFT JOIN collection_music_playlists cmp "
                "ON cmp.collection_type='smart' AND cmp.collection_id=ss.id "
                "WHERE ss.id=?",
                (saved_search_id,),
            )

    def create_saved_search(self, name: str, query_model: Any) -> int:
        normalized_name = normalize_saved_search_name(name)
        query = parse_picture_query(picture_query_to_dict(query_model))
        query_json = canonical_picture_query_json(query)
        now = utc_now()
        with self.engine.transaction(immediate=True) as connection:
            existing = self.engine.fetchone(
                connection,
                "SELECT id FROM saved_searches WHERE name=?",
                (normalized_name,),
            )
            if existing is not None:
                raise SavedSearchValidationError(
                    "A saved search with this name already exists"
                )
            try:
                cursor = self.engine.execute(
                    connection,
                    "INSERT INTO saved_searches "
                    "(name, query_version, query_json, created_at, updated_at) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (normalized_name, query.version, query_json, now, now),
                )
            except self.engine.integrity_errors as exc:
                raise SavedSearchValidationError(
                    "A saved search with this name already exists"
                ) from exc
            try:
                return int(cursor.lastrowid)
            finally:
                cursor.close()

    def rename_saved_search(self, saved_search_id: int, name: str) -> bool:
        normalized_name = normalize_saved_search_name(name)
        with self.engine.transaction(immediate=True) as connection:
            existing = self.engine.fetchone(
                connection,
                "SELECT id FROM saved_searches WHERE name=? AND id<>?",
                (normalized_name, saved_search_id),
            )
            if existing is not None:
                raise SavedSearchValidationError(
                    "A saved search with this name already exists"
                )
            try:
                cursor = self.engine.execute(
                    connection,
                    "UPDATE saved_searches SET name=?, updated_at=? WHERE id=?",
                    (normalized_name, utc_now(), saved_search_id),
                )
            except self.engine.integrity_errors as exc:
                raise SavedSearchValidationError(
                    "A saved search with this name already exists"
                ) from exc
            try:
                return int(cursor.rowcount or 0) > 0
            finally:
                cursor.close()

    def delete_saved_search(self, saved_search_id: int) -> bool:
        with self.engine.transaction(immediate=True) as connection:
            self.engine.execute(
                connection,
                "DELETE FROM collection_music_playlists "
                "WHERE collection_type=? AND collection_id=?",
                (MUSIC_TARGET_SMART, saved_search_id),
            ).close()
            cursor = self.engine.execute(
                connection,
                "DELETE FROM saved_searches WHERE id=?",
                (saved_search_id,),
            )
            try:
                return int(cursor.rowcount or 0) > 0
            finally:
                cursor.close()

    def _music_target_exists(
        self,
        connection,
        collection_type: str,
        collection_id: int,
        lock: bool = False,
    ) -> bool:
        table = (
            "saved_searches"
            if collection_type == MUSIC_TARGET_SMART
            else "collections"
        )
        lock_sql = " FOR UPDATE" if lock and self.engine.backend == "mysql" else ""
        return self.engine.fetchone(
            connection,
            "SELECT id FROM %s WHERE id=?%s" % (table, lock_sql),
            (collection_id,),
        ) is not None

    def get_music_playlist(
        self, collection_type: str, collection_id: int
    ) -> str:
        target_type = normalize_music_target_type(collection_type)
        target_id = int(collection_id)
        if target_id <= 0:
            raise MusicPlaylistValidationError("Collection ID is invalid")
        with self.engine.transaction() as connection:
            if not self._music_target_exists(connection, target_type, target_id):
                return ""
            row = self.engine.fetchone(
                connection,
                "SELECT playlist_uri FROM collection_music_playlists "
                "WHERE collection_type=? AND collection_id=?",
                (target_type, target_id),
            )
        return str((row or {}).get("playlist_uri") or "")

    def set_music_playlist(
        self, collection_type: str, collection_id: int, playlist_uri: str
    ) -> bool:
        target_type = normalize_music_target_type(collection_type)
        target_id = int(collection_id)
        uri = normalize_music_playlist_uri(playlist_uri)
        if target_id <= 0:
            raise MusicPlaylistValidationError("Collection ID is invalid")
        now = utc_now()
        with self.engine.transaction(immediate=True) as connection:
            if not self._music_target_exists(
                connection, target_type, target_id, lock=True
            ):
                return False
            cursor = self.engine.execute(
                connection,
                "UPDATE collection_music_playlists "
                "SET playlist_uri=?, updated_at=? "
                "WHERE collection_type=? AND collection_id=?",
                (uri, now, target_type, target_id),
            )
            try:
                updated = int(cursor.rowcount or 0) > 0
            finally:
                cursor.close()
            if not updated:
                try:
                    self.engine.execute(
                        connection,
                        "INSERT INTO collection_music_playlists "
                        "(collection_type, collection_id, playlist_uri, updated_at) "
                        "VALUES (?, ?, ?, ?)",
                        (target_type, target_id, uri, now),
                    ).close()
                except self.engine.integrity_errors:
                    # A second Kodi device may assign the same shared target
                    # after our UPDATE but before our INSERT. Last writer wins.
                    self.engine.execute(
                        connection,
                        "UPDATE collection_music_playlists "
                        "SET playlist_uri=?, updated_at=? "
                        "WHERE collection_type=? AND collection_id=?",
                        (uri, now, target_type, target_id),
                    ).close()
        return True

    def clear_music_playlist(
        self, collection_type: str, collection_id: int
    ) -> bool:
        target_type = normalize_music_target_type(collection_type)
        target_id = int(collection_id)
        if target_id <= 0:
            raise MusicPlaylistValidationError("Collection ID is invalid")
        with self.engine.transaction(immediate=True) as connection:
            cursor = self.engine.execute(
                connection,
                "DELETE FROM collection_music_playlists "
                "WHERE collection_type=? AND collection_id=?",
                (target_type, target_id),
            )
            try:
                return int(cursor.rowcount or 0) > 0
            finally:
                cursor.close()

    def list_collections(self) -> List[Dict[str, Any]]:
        order = (
            "c.name COLLATE NOCASE, c.id"
            if self.engine.backend == "sqlite"
            else "c.name, c.id"
        )
        predicate, policy_params = self._rating_predicate("p.rating", "p.media_type")
        policy_sql = " AND " + predicate if predicate else ""
        with self.engine.transaction() as connection:
            rows = self.engine.fetchall(
                connection,
                "SELECT c.id, c.name, c.created_at, c.updated_at, "
                "cmp.playlist_uri AS music_playlist_uri FROM collections c "
                "LEFT JOIN collection_music_playlists cmp "
                "ON cmp.collection_type='manual' AND cmp.collection_id=c.id "
                "ORDER BY %s" % order,
            )
            for row in rows:
                if not row.get("music_playlist_uri"):
                    row.pop("music_playlist_uri", None)
                total = self.engine.fetchone(
                    connection,
                    "SELECT COUNT(*) AS total FROM collection_items WHERE collection_id=?",
                    (row["id"],),
                )
                available = self.engine.fetchone(
                    connection,
                    "SELECT COUNT(*) AS total FROM collection_items ci "
                    "JOIN pictures p ON p.id=ci.picture_id "
                    "WHERE ci.collection_id=? AND p.is_missing=0%s" % policy_sql,
                    (row["id"], *policy_params),
                )
                representative = self.engine.fetchone(
                    connection,
                    "SELECT p.uri, p.thumb_uri, p.media_type FROM collection_items ci "
                    "JOIN pictures p ON p.id=ci.picture_id "
                    "WHERE ci.collection_id=? AND p.is_missing=0%s "
                    "ORDER BY ci.position, ci.picture_id LIMIT 1" % policy_sql,
                    (row["id"], *policy_params),
                )
                row["item_count"] = int((total or {}).get("total") or 0)
                row["available_count"] = int((available or {}).get("total") or 0)
                row.update(representative or {})
        return rows

    def get_collection(self, collection_id: int) -> Optional[StaticCollection]:
        with self.engine.transaction() as connection:
            row = self.engine.fetchone(
                connection,
                "SELECT id, name, created_at, updated_at FROM collections WHERE id=?",
                (collection_id,),
            )
        return parse_stored_collection(row) if row is not None else None

    def create_collection(self, name: str) -> int:
        normalized_name = normalize_collection_name(name)
        now = utc_now()
        with self.engine.transaction(immediate=True) as connection:
            existing = self.engine.fetchone(
                connection,
                "SELECT id FROM collections WHERE name=?",
                (normalized_name,),
            )
            if existing is not None:
                raise CollectionValidationError(
                    "A collection with this name already exists"
                )
            try:
                cursor = self.engine.execute(
                    connection,
                    "INSERT INTO collections (name, created_at, updated_at) "
                    "VALUES (?, ?, ?)",
                    (normalized_name, now, now),
                )
            except self.engine.integrity_errors as exc:
                raise CollectionValidationError(
                    "A collection with this name already exists"
                ) from exc
            try:
                return int(cursor.lastrowid)
            finally:
                cursor.close()

    def rename_collection(self, collection_id: int, name: str) -> bool:
        normalized_name = normalize_collection_name(name)
        with self.engine.transaction(immediate=True) as connection:
            existing = self.engine.fetchone(
                connection,
                "SELECT id FROM collections WHERE name=? AND id<>?",
                (normalized_name, collection_id),
            )
            if existing is not None:
                raise CollectionValidationError(
                    "A collection with this name already exists"
                )
            try:
                cursor = self.engine.execute(
                    connection,
                    "UPDATE collections SET name=?, updated_at=? WHERE id=?",
                    (normalized_name, utc_now(), collection_id),
                )
            except self.engine.integrity_errors as exc:
                raise CollectionValidationError(
                    "A collection with this name already exists"
                ) from exc
            try:
                return int(cursor.rowcount or 0) > 0
            finally:
                cursor.close()

    def delete_collection(self, collection_id: int) -> bool:
        with self.engine.transaction(immediate=True) as connection:
            self.engine.execute(
                connection,
                "DELETE FROM collection_music_playlists "
                "WHERE collection_type=? AND collection_id=?",
                (MUSIC_TARGET_MANUAL, collection_id),
            ).close()
            cursor = self.engine.execute(
                connection,
                "DELETE FROM collections WHERE id=?",
                (collection_id,),
            )
            try:
                return int(cursor.rowcount or 0) > 0
            finally:
                cursor.close()

    def add_picture_to_collection(self, collection_id: int, picture_id: int) -> bool:
        """Append one indexed media item, returning False for duplicates/missing rows."""
        with self.engine.transaction(immediate=True) as connection:
            collection_sql = "SELECT id FROM collections WHERE id=?"
            if self.engine.backend == "mysql":
                collection_sql += " FOR UPDATE"
            collection = self.engine.fetchone(
                connection,
                collection_sql,
                (collection_id,),
            )
            picture = self.engine.fetchone(
                connection,
                "SELECT id FROM pictures WHERE id=? AND is_missing=0",
                (picture_id,),
            )
            if collection is None or picture is None:
                return False
            existing = self.engine.fetchone(
                connection,
                "SELECT position FROM collection_items "
                "WHERE collection_id=? AND picture_id=?",
                (collection_id, picture_id),
            )
            if existing is not None:
                return False
            last = self.engine.fetchone(
                connection,
                "SELECT MAX(position) AS position FROM collection_items "
                "WHERE collection_id=?",
                (collection_id,),
            )
            position = int((last or {}).get("position") or 0) + 1
            now = utc_now()
            try:
                self.engine.execute(
                    connection,
                    "INSERT INTO collection_items "
                    "(collection_id, picture_id, position, added_at) "
                    "VALUES (?, ?, ?, ?)",
                    (collection_id, picture_id, position, now),
                ).close()
            except self.engine.integrity_errors:
                return False
            self.engine.execute(
                connection,
                "UPDATE collections SET updated_at=? WHERE id=?",
                (now, collection_id),
            ).close()
            return True

    def _collection_item_ids(self, connection, collection_id: int) -> List[int]:
        rows = self.engine.fetchall(
            connection,
            "SELECT picture_id FROM collection_items WHERE collection_id=? "
            "ORDER BY position, picture_id",
            (collection_id,),
        )
        return [int(row["picture_id"]) for row in rows]

    def _rewrite_collection_positions(
        self, connection, collection_id: int, picture_ids: Sequence[int]
    ) -> None:
        """Rewrite a compact 1-based order without signed-column assumptions."""

        stored = self.engine.fetchall(
            connection,
            "SELECT picture_id, added_at FROM collection_items "
            "WHERE collection_id=?",
            (collection_id,),
        )
        added_at = {int(row["picture_id"]): row["added_at"] for row in stored}
        ordered_ids = [int(picture_id) for picture_id in picture_ids]
        if len(ordered_ids) != len(set(ordered_ids)) or set(ordered_ids) != set(added_at):
            raise CollectionValidationError("Collection membership changed while reordering")

        self.engine.execute(
            connection,
            "DELETE FROM collection_items WHERE collection_id=?",
            (collection_id,),
        ).close()
        if ordered_ids:
            cursor = self.engine.executemany(
                connection,
                "INSERT INTO collection_items "
                "(collection_id, picture_id, position, added_at) "
                "VALUES (?, ?, ?, ?)",
                [
                    (collection_id, picture_id, position, added_at[picture_id])
                    for position, picture_id in enumerate(ordered_ids, start=1)
                ],
            )
            cursor.close()

    def remove_picture_from_collection(self, collection_id: int, picture_id: int) -> bool:
        with self.engine.transaction(immediate=True) as connection:
            collection_sql = "SELECT id FROM collections WHERE id=?"
            if self.engine.backend == "mysql":
                collection_sql += " FOR UPDATE"
            if self.engine.fetchone(connection, collection_sql, (collection_id,)) is None:
                return False
            cursor = self.engine.execute(
                connection,
                "DELETE FROM collection_items WHERE collection_id=? AND picture_id=?",
                (collection_id, picture_id),
            )
            try:
                removed = int(cursor.rowcount or 0) > 0
            finally:
                cursor.close()
            if removed:
                self._rewrite_collection_positions(
                    connection,
                    collection_id,
                    self._collection_item_ids(connection, collection_id),
                )
                self.engine.execute(
                    connection,
                    "UPDATE collections SET updated_at=? WHERE id=?",
                    (utc_now(), collection_id),
                ).close()
            return removed

    def move_picture_in_collection(
        self, collection_id: int, picture_id: int, direction: str
    ) -> bool:
        """Move one item up/down/to an edge while preserving mixed-media order."""

        if direction not in {"up", "down", "top", "bottom"}:
            raise ValueError("Unknown collection move direction")
        with self.engine.transaction(immediate=True) as connection:
            collection_sql = "SELECT id FROM collections WHERE id=?"
            if self.engine.backend == "mysql":
                collection_sql += " FOR UPDATE"
            if self.engine.fetchone(connection, collection_sql, (collection_id,)) is None:
                return False
            picture_ids = self._collection_item_ids(connection, collection_id)
            try:
                index = picture_ids.index(int(picture_id))
            except ValueError:
                return False
            if direction == "up":
                target = index - 1
            elif direction == "down":
                target = index + 1
            elif direction == "top":
                target = 0
            else:
                target = len(picture_ids) - 1
            if target < 0 or target >= len(picture_ids) or target == index:
                return False
            item = picture_ids.pop(index)
            picture_ids.insert(target, item)
            self._rewrite_collection_positions(connection, collection_id, picture_ids)
            self.engine.execute(
                connection,
                "UPDATE collections SET updated_at=? WHERE id=?",
                (utc_now(), collection_id),
            ).close()
            return True

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

    def get_source_scan_policy(self, source_id: int) -> Optional[SourceScanPolicy]:
        with self.engine.transaction() as connection:
            row = self.engine.fetchone(
                connection,
                "SELECT `recursive`, include_videos, picture_extensions, video_extensions, "
                "exclude_fragments, exclude_hidden FROM source_scan_policies WHERE source_id=?",
                (source_id,),
            )
        if row is None:
            return None
        return normalize_source_scan_policy(
            SourceScanPolicy(
                recursive=bool(row["recursive"]),
                include_videos=bool(row["include_videos"]),
                picture_extensions=decode_policy_list(row["picture_extensions"]),
                video_extensions=decode_policy_list(row["video_extensions"]),
                exclude_fragments=decode_policy_list(row["exclude_fragments"]),
                exclude_hidden=bool(row["exclude_hidden"]),
            )
        )

    def set_source_scan_policy(self, source_id: int, policy: SourceScanPolicy) -> None:
        normalized = normalize_source_scan_policy(policy)
        now = utc_now()
        with self.engine.transaction() as connection:
            source = self.engine.fetchone(connection, "SELECT id FROM sources WHERE id=?", (source_id,))
            if source is None:
                raise ValueError("Source was not found")
            existing = self.engine.fetchone(
                connection,
                "SELECT source_id FROM source_scan_policies WHERE source_id=?",
                (source_id,),
            )
            values = (
                1 if normalized.recursive else 0,
                1 if normalized.include_videos else 0,
                encode_policy_list(normalized.picture_extensions),
                encode_policy_list(normalized.video_extensions),
                encode_policy_list(normalized.exclude_fragments),
                1 if normalized.exclude_hidden else 0,
                now,
            )
            if existing is None:
                self.engine.execute(
                    connection,
                    "INSERT INTO source_scan_policies "
                    "(source_id, `recursive`, include_videos, picture_extensions, video_extensions, "
                    "exclude_fragments, exclude_hidden, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (source_id, *values),
                ).close()
            else:
                self.engine.execute(
                    connection,
                    "UPDATE source_scan_policies SET `recursive`=?, include_videos=?, "
                    "picture_extensions=?, video_extensions=?, exclude_fragments=?, "
                    "exclude_hidden=?, updated_at=? WHERE source_id=?",
                    (*values, source_id),
                ).close()

    def clear_source_scan_policy(self, source_id: int) -> bool:
        with self.engine.transaction() as connection:
            cursor = self.engine.execute(
                connection,
                "DELETE FROM source_scan_policies WHERE source_id=?",
                (source_id,),
            )
            try:
                return int(cursor.rowcount or 0) > 0
            finally:
                cursor.close()

    def list_metadata_mapping_overrides(self) -> List[MetadataMappingRule]:
        with self.engine.transaction() as connection:
            rows = self.engine.fetchall(
                connection,
                "SELECT source_type, source_tag, target_field, rule_priority "
                "FROM metadata_mapping_rules ORDER BY source_type, rule_priority, source_tag",
            )
        return [
            normalize_mapping_rule(
                MetadataMappingRule(
                    source_type=str(row["source_type"]),
                    source_tag=str(row["source_tag"]),
                    target_field=row.get("target_field"),
                    priority=int(row["rule_priority"]),
                )
            )
            for row in rows
        ]

    def set_metadata_mapping_rule(self, rule: MetadataMappingRule) -> None:
        normalized = normalize_mapping_rule(rule)
        normalized_tag = normalized.source_tag.casefold()
        now = utc_now()
        with self.engine.transaction() as connection:
            existing = self.engine.fetchone(
                connection,
                "SELECT id FROM metadata_mapping_rules "
                "WHERE source_type=? AND normalized_tag=?",
                (normalized.source_type, normalized_tag),
            )
            values = (
                normalized.source_tag,
                normalized.target_field,
                int(normalized.priority),
                now,
            )
            if existing is None:
                self.engine.execute(
                    connection,
                    "INSERT INTO metadata_mapping_rules "
                    "(source_type, source_tag, normalized_tag, target_field, rule_priority, created_at, updated_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (
                        normalized.source_type,
                        normalized.source_tag,
                        normalized_tag,
                        normalized.target_field,
                        int(normalized.priority),
                        now,
                        now,
                    ),
                ).close()
            else:
                self.engine.execute(
                    connection,
                    "UPDATE metadata_mapping_rules SET source_tag=?, target_field=?, "
                    "rule_priority=?, updated_at=? WHERE id=?",
                    (*values, int(existing["id"])),
                ).close()

    def clear_metadata_mapping_rule(self, source_type: str, source_tag: str) -> bool:
        source_type = normalize_source_type(source_type)
        source_tag = normalize_source_tag(source_type, source_tag)
        with self.engine.transaction() as connection:
            cursor = self.engine.execute(
                connection,
                "DELETE FROM metadata_mapping_rules WHERE source_type=? AND normalized_tag=?",
                (source_type, source_tag.casefold()),
            )
            try:
                return int(cursor.rowcount or 0) > 0
            finally:
                cursor.close()

    def clear_metadata_mapping_rules(self) -> int:
        with self.engine.transaction() as connection:
            cursor = self.engine.execute(connection, "DELETE FROM metadata_mapping_rules")
            try:
                return max(0, int(cursor.rowcount or 0))
            finally:
                cursor.close()

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
            pictures = self.engine.fetchone(
                connection,
                "SELECT COUNT(*) AS total, "
                "SUM(CASE WHEN is_missing=1 THEN 1 ELSE 0 END) AS missing, "
                "SUM(CASE WHEN media_type='video' AND is_missing=0 THEN 1 ELSE 0 END) AS videos "
                "FROM pictures",
            ) or {}
            folders = self.engine.fetchone(connection, "SELECT COUNT(*) AS total FROM folders WHERE is_missing=0") or {}
            sources = self.engine.fetchone(connection, "SELECT COUNT(*) AS total, SUM(CASE WHEN enabled=1 THEN 1 ELSE 0 END) AS enabled FROM sources") or {}
        return {
            "pictures": int(pictures.get("total") or 0),
            "missing": int(pictures.get("missing") or 0),
            "videos": int(pictures.get("videos") or 0),
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
        return self.engine.fetchone(connection, "SELECT id, file_size, file_mtime, media_type, metadata_hash, metadata_index_hash, favorite, discovered_at FROM pictures WHERE uri_hash=?", (sha256_text(uri),))

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
        keyword_values = tuple(keywords)
        year, month, day = self._date_parts(record.get("taken_at"))
        fields = (
            record["source_id"], record["folder_id"], record["uri"], sha256_text(record["uri"]), record["filename"],
            record["extension"], record.get("media_type", "picture"), record["file_size"], record["file_mtime"], record["discovered_at"], record["last_seen_at"],
            record.get("taken_at"), record.get("taken_source"), year, month, day, record.get("width"), record.get("height"),
            record.get("orientation"), record.get("mime_type"), record.get("camera_make"), record.get("camera_model"),
            record.get("rating"), record.get("gps_latitude"), record.get("gps_longitude"), record.get("city"), record.get("state"),
            record.get("country"), record.get("sublocation"), record.get("caption"), record.get("metadata_hash"), record.get("metadata_index_hash"), record.get("thumb_uri"),
            random.random(),
        )
        cursor = self.engine.execute(connection, """INSERT INTO pictures (
            source_id, folder_id, uri, uri_hash, filename, extension, media_type, file_size, file_mtime,
            discovered_at, last_seen_at, taken_at, taken_source, taken_year, taken_month, taken_day,
            width, height, orientation, mime_type, camera_make, camera_model, rating,
            gps_latitude, gps_longitude, city, state, country, sublocation, caption,
            metadata_hash, metadata_index_hash, thumb_uri, random_key, favorite, is_missing
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, 0)""", fields)
        try:
            picture_id = int(cursor.lastrowid)
        finally:
            cursor.close()
        self.replace_tags(connection, picture_id, keyword_values)
        self.replace_search_document(connection, picture_id, record, keyword_values)
        return picture_id

    def update_picture(self, connection, picture_id: int, record: Dict[str, Any], keywords: Iterable[str]) -> None:
        keyword_values = tuple(keywords)
        year, month, day = self._date_parts(record.get("taken_at"))
        self.engine.execute(connection, """UPDATE pictures SET
            source_id=?, folder_id=?, uri=?, filename=?, extension=?, media_type=?, file_size=?, file_mtime=?, last_seen_at=?,
            taken_at=?, taken_source=?, taken_year=?, taken_month=?, taken_day=?, width=?, height=?, orientation=?,
            mime_type=?, camera_make=?, camera_model=?, rating=?, gps_latitude=?, gps_longitude=?, city=?, state=?,
            country=?, sublocation=?, caption=?, metadata_hash=?, metadata_index_hash=?, thumb_uri=?, is_missing=0, missing_since=NULL
            WHERE id=?""", (
                record["source_id"], record["folder_id"], record["uri"], record["filename"], record["extension"],
                record.get("media_type", "picture"), record["file_size"], record["file_mtime"], record["last_seen_at"], record.get("taken_at"),
                record.get("taken_source"), year, month, day, record.get("width"), record.get("height"),
                record.get("orientation"), record.get("mime_type"), record.get("camera_make"), record.get("camera_model"),
                record.get("rating"), record.get("gps_latitude"), record.get("gps_longitude"), record.get("city"),
                record.get("state"), record.get("country"), record.get("sublocation"), record.get("caption"),
                record.get("metadata_hash"), record.get("metadata_index_hash"), record.get("thumb_uri"), picture_id,
            )).close()
        self.replace_tags(connection, picture_id, keyword_values)
        self.replace_search_document(connection, picture_id, record, keyword_values)

    def replace_search_document(
        self,
        connection,
        picture_id: int,
        record: Dict[str, Any],
        keywords: Iterable[str],
    ) -> None:
        document = build_picture_search_document(record, keywords)
        self.engine.execute(
            connection,
            "DELETE FROM picture_search_documents WHERE picture_id=?",
            (picture_id,),
        ).close()
        self.engine.execute(
            connection,
            "INSERT INTO picture_search_documents (picture_id, document) VALUES (?, ?)",
            (picture_id, document),
        ).close()

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
            latest = self.engine.fetchone(
                connection,
                "SELECT id, taken_at, discovered_at FROM pictures "
                "WHERE folder_id=? AND is_missing=0 "
                "ORDER BY COALESCE(taken_at, discovered_at) DESC, id DESC LIMIT 1",
                (folder["id"],),
            )
            if latest:
                representative = self.engine.fetchone(
                    connection,
                    "SELECT id FROM pictures WHERE folder_id=? AND is_missing=0 "
                    "ORDER BY CASE WHEN media_type='picture' THEN 0 ELSE 1 END, "
                    "COALESCE(taken_at, discovered_at) DESC, id DESC LIMIT 1",
                    (folder["id"],),
                )
                representative_id = representative["id"] if representative else latest["id"]
                self.engine.execute(
                    connection,
                    "UPDATE folders SET representative_picture_id=?, latest_taken_at=?, latest_discovered_at=? WHERE id=?",
                    (representative_id, latest.get("taken_at"), latest.get("discovered_at"), folder["id"]),
                ).close()
            else:
                self.engine.execute(connection, "UPDATE folders SET representative_picture_id=NULL, latest_taken_at=NULL, latest_discovered_at=NULL WHERE id=?", (folder["id"],)).close()

    # Browser and widget queries --------------------------------------------

    def _pictures(self, where: str, params: Sequence[Any], order: str, limit: int, offset: int = 0) -> List[Dict[str, Any]]:
        where, params = self._apply_rating_policy(where, params)
        query = "SELECT %s FROM pictures p JOIN folders f ON f.id=p.folder_id JOIN sources s ON s.id=p.source_id WHERE p.is_missing=0" % PICTURE_COLUMNS
        if where:
            query += " AND " + where
        query += " ORDER BY " + order + " LIMIT ? OFFSET ?"
        with self.engine.transaction() as connection:
            return self.engine.fetchall(connection, query, (*params, limit, offset))

    def query_pictures(self, query_model: Any, limit: int, offset: int = 0) -> List[Dict[str, Any]]:
        """Run a validated versioned query model without exposing raw SQL."""
        if type(limit) is not int:
            raise ValueError("Query-model page limit must be an integer")
        if type(offset) is not int:
            raise ValueError("Query-model page offset must be an integer")
        if limit < 1 or limit > 1000:
            raise ValueError("Query-model page limit must be between 1 and 1000")
        if offset < 0:
            raise ValueError("Query-model page offset must not be negative")
        compiled = compile_picture_query(query_model, self.rating_policy)
        sql = (
            "SELECT %s FROM pictures p "
            "JOIN folders f ON f.id=p.folder_id "
            "JOIN sources s ON s.id=p.source_id "
            "WHERE %s ORDER BY %s LIMIT ? OFFSET ?"
            % (PICTURE_COLUMNS, compiled.where_sql, compiled.order_by_sql)
        )
        with self.engine.transaction() as connection:
            return self.engine.fetchall(
                connection,
                sql,
                (*compiled.params, limit, offset),
            )

    def count_query_pictures(self, query_model: Any) -> int:
        """Count the same result set used by :meth:`query_pictures`."""
        compiled = compile_picture_query(query_model, self.rating_policy)
        with self.engine.transaction() as connection:
            row = self.engine.fetchone(
                connection,
                "SELECT COUNT(*) AS total FROM pictures p WHERE %s" % compiled.where_sql,
                compiled.params,
            )
        return int((row or {}).get("total") or 0)

    def query_facet_counts(
        self, query_model: Any, field: str, limit: int = 100, offset: int = 0
    ) -> List[Dict[str, Any]]:
        """Return bounded facet counts for the same validated query selection.

        The field name is resolved through a fixed allowlist; callers never supply
        SQL identifiers or expressions. Scalar empty values are omitted and the
        keyword facet uses the normalized tag relation.
        """
        if field != "keyword" and field not in QUERY_FACET_EXPRESSIONS:
            raise ValueError("Unsupported query facet field %r" % field)
        if type(limit) is not int:
            raise ValueError("Query facet limit must be an integer")
        if limit < 1 or limit > 500:
            raise ValueError("Query facet limit must be between 1 and 500")
        if type(offset) is not int or offset < 0:
            raise ValueError("Query facet offset must be a non-negative integer")
        compiled = compile_picture_query(query_model, self.rating_policy)
        if field == "keyword":
            sql = (
                "SELECT t.name AS facet_value, COUNT(*) AS picture_count "
                "FROM pictures p "
                "JOIN picture_tags pt ON pt.picture_id=p.id "
                "JOIN tags t ON t.id=pt.tag_id "
                "WHERE %s "
                "GROUP BY t.id, t.name "
                "ORDER BY picture_count DESC, facet_value ASC LIMIT ? OFFSET ?"
                % compiled.where_sql
            )
            params = (*compiled.params, limit, offset)
        else:
            expression = QUERY_FACET_EXPRESSIONS[field]
            sql = (
                "SELECT %s AS facet_value, COUNT(*) AS picture_count FROM pictures p "
                "WHERE %s AND %s IS NOT NULL "
                "GROUP BY %s ORDER BY picture_count DESC, facet_value ASC LIMIT ? OFFSET ?"
                % (expression, compiled.where_sql, expression, expression)
            )
            params = (*compiled.params, limit, offset)
        with self.engine.transaction() as connection:
            rows = self.engine.fetchall(connection, sql, params)
        return [
            {
                "value": row.get("facet_value"),
                "picture_count": int(row.get("picture_count") or 0),
            }
            for row in rows
        ]

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

    def videos(self, limit: int, offset: int = 0) -> List[Dict[str, Any]]:
        return self._pictures("p.media_type='video'", (), "COALESCE(p.taken_at, p.discovered_at) DESC, p.id DESC", limit, offset)

    def on_this_day(self, month: int, day: int, current_year: int, limit: int, offset: int = 0) -> List[Dict[str, Any]]:
        return self._pictures("p.taken_month=? AND p.taken_day=? AND p.taken_year<?", (month, day, current_year), "p.taken_year DESC, p.taken_at DESC", limit, offset)

    @staticmethod
    def _random_pivot(seed: Optional[float] = None) -> float:
        if seed is None:
            return random.random()
        try:
            return float(seed) % 1.0
        except (TypeError, ValueError):
            return 0.0

    def random_on_this_day(
        self,
        month: int,
        day: int,
        current_year: int,
        limit: int,
        seed: Optional[float] = None,
    ) -> List[Dict[str, Any]]:
        pivot = self._random_pivot(seed)
        where = "p.taken_month=? AND p.taken_day=? AND p.taken_year<?"
        first = self._pictures(
            where + " AND p.random_key>=?",
            (month, day, current_year, pivot),
            "p.random_key",
            limit,
            0,
        )
        if len(first) < limit:
            second = self._pictures(
                where + " AND p.random_key<?",
                (month, day, current_year, pivot),
                "p.random_key",
                limit - len(first),
                0,
            )
            first.extend(second)
        if seed is None:
            random.shuffle(first)
        else:
            random.Random(pivot).shuffle(first)
        return first

    def media_type_for_uri(self, uri: str) -> Optional[str]:
        normalized = normalize_uri(uri)
        if not normalized:
            return None
        with self.engine.transaction() as connection:
            row = self.engine.fetchone(
                connection,
                "SELECT media_type FROM pictures WHERE uri_hash=? AND is_missing=0",
                (sha256_text(normalized),),
            )
        return str(row["media_type"]) if row and row.get("media_type") else None

    def pictures_for_year(self, year: int, limit: int, offset: int = 0) -> List[Dict[str, Any]]:
        return self._pictures("p.taken_year=?", (year,), "p.taken_at DESC, p.id DESC", limit, offset)

    def pictures_for_day(
        self,
        year: int,
        month: int,
        day: int,
        limit: int,
        offset: int = 0,
    ) -> List[Dict[str, Any]]:
        return self._pictures(
            "p.taken_year=? AND p.taken_month=? AND p.taken_day=?",
            (year, month, day),
            "p.taken_at DESC, p.id DESC",
            limit,
            offset,
        )

    def pictures_without_date(self, limit: int, offset: int = 0) -> List[Dict[str, Any]]:
        return self._pictures(
            "p.taken_at IS NULL",
            (),
            "p.discovered_at DESC, p.id DESC",
            limit,
            offset,
        )

    def pictures_for_camera(self, camera_make: str, camera_model: str, limit: int, offset: int = 0) -> List[Dict[str, Any]]:
        return self._pictures("COALESCE(p.camera_make,'')=? AND COALESCE(p.camera_model,'')=?", (camera_make, camera_model), "COALESCE(p.taken_at, p.discovered_at) DESC", limit, offset)

    def pictures_for_tag(self, tag_id: int, limit: int, offset: int = 0) -> List[Dict[str, Any]]:
        where = "EXISTS (SELECT 1 FROM picture_tags pt WHERE pt.picture_id=p.id AND pt.tag_id=?)"
        return self._pictures(where, (tag_id,), "COALESCE(p.taken_at, p.discovered_at) DESC", limit, offset)

    def pictures_in_folder(self, folder_id: int, limit: int, offset: int = 0) -> List[Dict[str, Any]]:
        return self._pictures("p.folder_id=?", (folder_id,), "COALESCE(p.taken_at, p.discovered_at) DESC, p.filename", limit, offset)

    def collection_available_count(self, collection_id: int) -> int:
        where, params = self._apply_rating_policy(
            "ci.collection_id=?", (collection_id,)
        )
        with self.engine.transaction() as connection:
            row = self.engine.fetchone(
                connection,
                "SELECT COUNT(*) AS total FROM collection_items ci "
                "JOIN pictures p ON p.id=ci.picture_id "
                "WHERE p.is_missing=0 AND %s" % where,
                params,
            )
        return int((row or {}).get("total") or 0)

    def pictures_in_collection(
        self, collection_id: int, limit: int, offset: int = 0
    ) -> List[Dict[str, Any]]:
        if type(limit) is not int or type(offset) is not int:
            raise ValueError("Collection page bounds must be integers")
        if limit < 1 or limit > 5000:
            raise ValueError("Collection page limit must be between 1 and 5000")
        if offset < 0:
            raise ValueError("Collection page offset must not be negative")
        where, params = self._apply_rating_policy(
            "ci.collection_id=?", (collection_id,)
        )
        query = (
            "SELECT %s, ci.position AS collection_position "
            "FROM collection_items ci "
            "JOIN pictures p ON p.id=ci.picture_id "
            "JOIN folders f ON f.id=p.folder_id "
            "JOIN sources s ON s.id=p.source_id "
            "WHERE p.is_missing=0 AND %s "
            "ORDER BY ci.position, ci.picture_id LIMIT ? OFFSET ?"
            % (PICTURE_COLUMNS, where)
        )
        with self.engine.transaction() as connection:
            return self.engine.fetchall(
                connection, query, (*params, limit, offset)
            )

    @staticmethod
    def _escape_like(value: str) -> str:
        return value.replace("!", "!!").replace("%", "!%").replace("_", "!_")

    def media_in_folder_tree(self, folder_id: int, limit: int) -> List[Dict[str, Any]]:
        folder = self.get_folder(folder_id)
        if not folder:
            return []
        prefix = self._escape_like(str(folder["uri"])) + "%"
        return self._pictures(
            "p.source_id=? AND p.uri LIKE ? ESCAPE '!'",
            (int(folder["source_id"]), prefix),
            "COALESCE(p.taken_at, p.discovered_at) DESC, p.filename",
            limit,
            0,
        )

    def random_pictures(
        self, limit: int, seed: Optional[float] = None
    ) -> List[Dict[str, Any]]:
        pivot = self._random_pivot(seed)
        first = self._pictures("p.random_key>=?", (pivot,), "p.random_key", limit, 0)
        if len(first) < limit:
            second = self._pictures(
                "p.random_key<?", (pivot,), "p.random_key", limit - len(first), 0
            )
            first.extend(second)
        return first

    def _folder_rows(self, where: str, params: Sequence[Any], order: str, limit: int, offset: int = 0) -> List[Dict[str, Any]]:
        count_predicate, count_params = self._rating_predicate("pc.rating", "pc.media_type")
        representative_predicate, representative_params = self._rating_predicate("pr.rating", "pr.media_type")
        count_filter = " AND " + count_predicate if count_predicate else ""
        representative_filter = " AND " + representative_predicate if representative_predicate else ""
        query = """SELECT f.*, p.uri AS representative_uri, p.thumb_uri AS representative_thumb,
                   p.media_type AS representative_media_type,
                   p.extension AS representative_extension,
                   (SELECT COUNT(*) FROM pictures pc WHERE pc.folder_id=f.id AND pc.is_missing=0%s) AS picture_count,
                   s.label AS source_label
                   FROM folders f
                   JOIN sources s ON s.id=f.source_id
                   LEFT JOIN pictures p ON p.id=(
                       SELECT pr.id FROM pictures pr
                       WHERE pr.folder_id=f.id AND pr.is_missing=0%s
                       ORDER BY CASE
                                  WHEN pr.media_type='picture' AND LOWER(COALESCE(pr.extension,'')) IN
                                       ('jpg','jpeg','png','webp','bmp','gif','tif','tiff') THEN 0
                                  WHEN pr.media_type='picture' THEN 1
                                  ELSE 2
                                END,
                                COALESCE(pr.taken_at, pr.discovered_at) DESC, pr.id DESC LIMIT 1
                   )
                   WHERE f.is_missing=0""" % (count_filter, representative_filter)
        if where:
            query += " AND " + where
        query += " ORDER BY " + order + " LIMIT ? OFFSET ?"
        with self.engine.transaction() as connection:
            return self.engine.fetchall(
                connection,
                query,
                (*count_params, *representative_params, *params, limit, offset),
            )

    def recent_folders(self, limit: int, offset: int = 0) -> List[Dict[str, Any]]:
        return self._folder_rows("p.id IS NOT NULL", (), "f.latest_discovered_at DESC, f.id DESC", limit, offset)

    def random_folders(
        self, limit: int, seed: Optional[float] = None
    ) -> List[Dict[str, Any]]:
        pivot = self._random_pivot(seed)
        first = self._folder_rows(
            "p.id IS NOT NULL AND f.random_key>=?",
            (pivot,),
            "f.random_key",
            limit,
        )
        if len(first) < limit:
            first.extend(
                self._folder_rows(
                    "p.id IS NOT NULL AND f.random_key<?",
                    (pivot,),
                    "f.random_key",
                    limit - len(first),
                )
            )
        return first

    def source_root_folders(self, source_id: int) -> List[Dict[str, Any]]:
        return self._folder_rows("f.source_id=? AND f.parent_uri=''", (source_id,), "f.name", 1000)

    def child_folders(self, source_id: int, parent_uri: str, limit: int = 1000) -> List[Dict[str, Any]]:
        return self._folder_rows("f.source_id=? AND f.parent_uri=?", (source_id, parent_uri), "f.name", limit)

    def get_folder(self, folder_id: int) -> Optional[Dict[str, Any]]:
        with self.engine.transaction() as connection:
            return self.engine.fetchone(connection, "SELECT f.*, s.label AS source_label FROM folders f JOIN sources s ON s.id=f.source_id WHERE f.id=?", (folder_id,))

    def years(self) -> List[Dict[str, Any]]:
        predicate, policy_params = self._rating_predicate("rating", "media_type")
        policy_sql = " AND " + predicate if predicate else ""
        with self.engine.transaction() as connection:
            groups = self.engine.fetchall(
                connection,
                (
                    "SELECT taken_year AS year, COUNT(*) AS picture_count "
                    "FROM pictures WHERE is_missing=0 AND taken_year IS NOT NULL%s "
                    "GROUP BY taken_year ORDER BY taken_year DESC"
                ) % policy_sql,
                policy_params,
            )
            for group in groups:
                rep = self.engine.fetchone(
                    connection,
                    "SELECT uri, thumb_uri, media_type FROM pictures "
                    "WHERE is_missing=0 AND taken_year=?%s "
                    "ORDER BY taken_at DESC, id DESC LIMIT 1" % policy_sql,
                    (group["year"], *policy_params),
                )
                group.update(rep or {})
            return groups

    def months_for_year(self, year: int) -> List[Dict[str, Any]]:
        predicate, policy_params = self._rating_predicate("rating", "media_type")
        policy_sql = " AND " + predicate if predicate else ""
        with self.engine.transaction() as connection:
            groups = self.engine.fetchall(
                connection,
                "SELECT taken_month AS date_value, COUNT(*) AS picture_count "
                "FROM pictures WHERE is_missing=0 AND taken_year=? "
                "AND taken_month IS NOT NULL%s "
                "GROUP BY taken_month ORDER BY taken_month" % policy_sql,
                (year, *policy_params),
            )
            result = []
            for group in groups:
                month = int(group["date_value"])
                rep = self.engine.fetchone(
                    connection,
                    "SELECT uri, thumb_uri, media_type FROM pictures "
                    "WHERE is_missing=0 AND taken_year=? AND taken_month=?%s "
                    "ORDER BY taken_at DESC, id DESC LIMIT 1" % policy_sql,
                    (year, month, *policy_params),
                )
                row = {"month": month, "picture_count": int(group["picture_count"])}
                row.update(rep or {})
                result.append(row)
            return result

    def days_for_month(self, year: int, month: int) -> List[Dict[str, Any]]:
        predicate, policy_params = self._rating_predicate("rating", "media_type")
        policy_sql = " AND " + predicate if predicate else ""
        with self.engine.transaction() as connection:
            groups = self.engine.fetchall(
                connection,
                "SELECT taken_day AS date_value, COUNT(*) AS picture_count "
                "FROM pictures WHERE is_missing=0 AND taken_year=? AND taken_month=? "
                "AND taken_day IS NOT NULL%s "
                "GROUP BY taken_day ORDER BY taken_day" % policy_sql,
                (year, month, *policy_params),
            )
            result = []
            for group in groups:
                day = int(group["date_value"])
                rep = self.engine.fetchone(
                    connection,
                    "SELECT uri, thumb_uri, media_type FROM pictures "
                    "WHERE is_missing=0 AND taken_year=? AND taken_month=? AND taken_day=?%s "
                    "ORDER BY taken_at DESC, id DESC LIMIT 1" % policy_sql,
                    (year, month, day, *policy_params),
                )
                row = {"day": day, "picture_count": int(group["picture_count"])}
                row.update(rep or {})
                result.append(row)
            return result

    def undated_summary(self) -> Optional[Dict[str, Any]]:
        predicate, policy_params = self._rating_predicate("rating", "media_type")
        policy_sql = " AND " + predicate if predicate else ""
        with self.engine.transaction() as connection:
            count = self.engine.fetchone(
                connection,
                "SELECT COUNT(*) AS picture_count FROM pictures "
                "WHERE is_missing=0 AND taken_at IS NULL%s" % policy_sql,
                policy_params,
            )
            total = int((count or {}).get("picture_count") or 0)
            if total == 0:
                return None
            rep = self.engine.fetchone(
                connection,
                "SELECT uri, thumb_uri, media_type FROM pictures "
                "WHERE is_missing=0 AND taken_at IS NULL%s "
                "ORDER BY discovered_at DESC, id DESC LIMIT 1" % policy_sql,
                policy_params,
            )
            row: Dict[str, Any] = {"picture_count": total}
            row.update(rep or {})
            return row

    def cameras(self) -> List[Dict[str, Any]]:
        predicate, policy_params = self._rating_predicate("rating", "media_type")
        policy_sql = " AND " + predicate if predicate else ""
        with self.engine.transaction() as connection:
            groups = self.engine.fetchall(connection, """SELECT COALESCE(camera_make,'') AS camera_make, COALESCE(camera_model,'') AS camera_model, COUNT(*) AS picture_count
                FROM pictures WHERE is_missing=0 AND media_type='picture' AND (camera_make IS NOT NULL OR camera_model IS NOT NULL)
                %s GROUP BY COALESCE(camera_make,''), COALESCE(camera_model,'') ORDER BY picture_count DESC, camera_make, camera_model""" % policy_sql, policy_params)
            for group in groups:
                rep = self.engine.fetchone(connection, "SELECT uri, thumb_uri, media_type FROM pictures WHERE is_missing=0 AND media_type='picture' AND COALESCE(camera_make,'')=? AND COALESCE(camera_model,'')=?%s ORDER BY COALESCE(taken_at, discovered_at) DESC LIMIT 1" % policy_sql, (group["camera_make"], group["camera_model"], *policy_params))
                group.update(rep or {})
            return groups

    def tags(self) -> List[Dict[str, Any]]:
        predicate, policy_params = self._rating_predicate("p.rating")
        policy_sql = " AND " + predicate if predicate else ""
        with self.engine.transaction() as connection:
            groups = self.engine.fetchall(connection, """SELECT t.id, t.name, COUNT(*) AS picture_count
                FROM tags t JOIN picture_tags pt ON pt.tag_id=t.id JOIN pictures p ON p.id=pt.picture_id
                WHERE p.is_missing=0 AND p.media_type='picture'%s GROUP BY t.id, t.name ORDER BY picture_count DESC, t.name""" % policy_sql, policy_params)
            for group in groups:
                rep = self.engine.fetchone(connection, """SELECT p.uri, p.thumb_uri, p.media_type FROM pictures p JOIN picture_tags pt ON pt.picture_id=p.id
                    WHERE p.is_missing=0 AND p.media_type='picture' AND pt.tag_id=?%s ORDER BY COALESCE(p.taken_at, p.discovered_at) DESC LIMIT 1""" % policy_sql, (group["id"], *policy_params))
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
