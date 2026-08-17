from __future__ import annotations

import hashlib
import sqlite3
from pathlib import Path

import pytest

from mypicsdb3.config import Settings
from mypicsdb3.db.catalog import Catalog
from mypicsdb3.db.engine import DatabaseEngine
from mypicsdb3.db.locks import (
    METADATA_REFRESH_LOCK_NAME,
    MIGRATION_LOCK_NAME,
    SCAN_LOCK_NAME,
    acquire_lock,
    release_lock,
)
from mypicsdb3.db.migration_steps.v0002_date_browsing import (
    MIGRATION as DATE_BROWSING_MIGRATION,
)
from mypicsdb3.db.migrations import (
    MigrationChecksumError,
    MigrationError,
    MigrationLockError,
    MigrationRunner,
    MigrationStep,
    SchemaTooNewError,
)
from mypicsdb3.db.schema import create_schema


def make_engine(tmp_path: Path) -> DatabaseEngine:
    return DatabaseEngine(Settings(profile_path=str(tmp_path), database_backend="sqlite"))


def create_schema_one_without_history(engine: DatabaseEngine) -> None:
    with engine.transaction(immediate=True) as connection:
        create_schema(engine, connection)
        engine.execute(connection, "DROP TABLE IF EXISTS metadata_mapping_rules").close()
        engine.execute(connection, "DROP TABLE IF EXISTS source_scan_policies").close()
        engine.execute(connection, "DROP TABLE IF EXISTS collection_music_playlists").close()
        engine.execute(connection, "DROP TABLE IF EXISTS collection_items").close()
        engine.execute(connection, "DROP TABLE IF EXISTS collections").close()
        engine.execute(connection, "DROP TABLE IF EXISTS saved_searches").close()
        engine.execute(connection, "DROP TABLE IF EXISTS picture_search_documents").close()
        engine.execute(connection, "DROP INDEX IF EXISTS idx_pictures_date_browse").close()
        engine.execute(
            connection,
            "INSERT INTO meta (key, value) VALUES (?, ?)",
            ("schema_version", "1"),
        ).close()


def migration_two() -> MigrationStep:
    def apply(engine, connection) -> None:
        engine.execute(
            connection,
            "CREATE TABLE future_feature (id INTEGER PRIMARY KEY, value TEXT NOT NULL)",
        ).close()

    return MigrationStep(
        version=2,
        name="future feature fixture",
        checksum=hashlib.sha256(b"test:migration:2:future-feature").hexdigest(),
        apply=apply,
    )


def test_new_database_records_current_schema_without_backup(tmp_path: Path) -> None:
    engine = make_engine(tmp_path)
    result = MigrationRunner(engine).initialize()

    assert result.created_database is True
    assert result.current_version == 9
    assert result.backup_path is None
    assert not (tmp_path / "backups").exists()
    with engine.transaction() as connection:
        rows = engine.fetchall(
            connection,
            "SELECT version, name, checksum FROM schema_migrations ORDER BY version",
        )
        index = engine.fetchone(
            connection,
            "SELECT name FROM sqlite_master WHERE type='index' "
            "AND name='idx_pictures_date_browse'",
        )
        search_table = engine.fetchone(
            connection,
            "SELECT name FROM sqlite_master WHERE type='table' "
            "AND name='picture_search_documents'",
        )
        saved_searches_table = engine.fetchone(
            connection,
            "SELECT name FROM sqlite_master WHERE type='table' "
            "AND name='saved_searches'",
        )
        collections_table = engine.fetchone(
            connection,
            "SELECT name FROM sqlite_master WHERE type='table' "
            "AND name='collections'",
        )
        collection_items_table = engine.fetchone(
            connection,
            "SELECT name FROM sqlite_master WHERE type='table' "
            "AND name='collection_items'",
        )
        music_table = engine.fetchone(
            connection,
            "SELECT name FROM sqlite_master WHERE type='table' "
            "AND name='collection_music_playlists'",
        )
        source_policy_table = engine.fetchone(
            connection,
            "SELECT name FROM sqlite_master WHERE type='table' "
            "AND name='source_scan_policies'",
        )
        mapping_table = engine.fetchone(
            connection,
            "SELECT name FROM sqlite_master WHERE type='table' "
            "AND name='metadata_mapping_rules'",
        )
    assert [row["version"] for row in rows] == [1, 2, 3, 4, 5, 6, 7, 8, 9]
    assert rows[0]["name"] == "initial catalogue schema"
    assert rows[1]["name"] == "year-first date browsing index"
    assert rows[2]["name"] == "normalized global search documents"
    assert rows[3]["name"] == "mixed picture and video media type"
    assert rows[4]["name"] == "saved picture searches"
    assert rows[5]["name"] == "manual media collections"
    assert rows[6]["name"] == "collection music playlists"
    assert rows[7]["name"] == "per-source scan policies"
    assert rows[8]["name"] == "metadata mapping overrides"
    assert all(len(row["checksum"]) == 64 for row in rows)
    assert index is not None
    assert search_table is not None
    assert saved_searches_table is not None
    assert collections_table is not None
    assert collection_items_table is not None
    assert music_table is not None
    assert source_policy_table is not None
    assert mapping_table is not None
    with engine.transaction() as connection:
        columns = engine.fetchall(connection, "PRAGMA table_info(pictures)")
    assert any(row["name"] == "media_type" for row in columns)
    assert any(row["name"] == "metadata_index_hash" for row in columns)
    with engine.transaction() as connection:
        plan = engine.fetchall(
            connection,
            "EXPLAIN QUERY PLAN SELECT id FROM pictures "
            "WHERE is_missing=0 AND taken_year=? AND taken_month=? AND taken_day=? "
            "ORDER BY taken_at DESC",
            (2020, 7, 17),
        )
    assert any(
        "idx_pictures_date_browse" in str(row.get("detail", ""))
        for row in plan
    )


def test_existing_schema_five_adds_manual_collections(tmp_path: Path) -> None:
    engine = make_engine(tmp_path)
    MigrationRunner(engine).initialize()
    with engine.transaction(immediate=True) as connection:
        engine.execute(connection, "DROP TABLE metadata_mapping_rules").close()
        engine.execute(connection, "DROP TABLE source_scan_policies").close()
        engine.execute(connection, "DROP TABLE collection_music_playlists").close()
        engine.execute(connection, "DROP TABLE collection_items").close()
        engine.execute(connection, "DROP TABLE collections").close()
        engine.execute(
            connection,
            "DELETE FROM schema_migrations WHERE version IN (?, ?, ?, ?)",
            (6, 7, 8, 9),
        ).close()
        engine.execute(
            connection,
            "UPDATE meta SET value=? WHERE key=?",
            ("5", "schema_version"),
        ).close()

    result = MigrationRunner(engine).initialize()

    assert result.previous_version == 5
    assert result.current_version == 9
    assert result.applied_versions == (6, 7, 8, 9)
    assert result.backup_path is not None
    with engine.transaction() as connection:
        assert engine.table_exists(connection, "collections")
        assert engine.table_exists(connection, "collection_items")
        assert engine.table_exists(connection, "collection_music_playlists")
        assert engine.table_exists(connection, "source_scan_policies")
        row = engine.fetchone(
            connection,
            "SELECT name FROM schema_migrations WHERE version=?",
            (7,),
        )
    assert row == {"name": "collection music playlists"}


def test_existing_schema_four_adds_saved_searches_and_collections(tmp_path: Path) -> None:
    engine = make_engine(tmp_path)
    MigrationRunner(engine).initialize()
    with engine.transaction(immediate=True) as connection:
        engine.execute(connection, "DROP TABLE metadata_mapping_rules").close()
        engine.execute(connection, "DROP TABLE source_scan_policies").close()
        engine.execute(connection, "DROP TABLE collection_music_playlists").close()
        engine.execute(connection, "DROP TABLE collection_items").close()
        engine.execute(connection, "DROP TABLE collections").close()
        engine.execute(connection, "DROP TABLE saved_searches").close()
        engine.execute(
            connection,
            "DELETE FROM schema_migrations WHERE version IN (?, ?, ?, ?, ?)",
            (5, 6, 7, 8, 9),
        ).close()
        engine.execute(
            connection,
            "UPDATE meta SET value=? WHERE key=?",
            ("4", "schema_version"),
        ).close()

    result = MigrationRunner(engine).initialize()

    assert result.previous_version == 4
    assert result.current_version == 9
    assert result.applied_versions == (5, 6, 7, 8, 9)
    assert result.backup_path is not None
    with engine.transaction() as connection:
        assert engine.table_exists(connection, "saved_searches")
        assert engine.table_exists(connection, "collections")
        assert engine.table_exists(connection, "collection_items")
        assert engine.table_exists(connection, "collection_music_playlists")
        assert engine.table_exists(connection, "source_scan_policies")
        row = engine.fetchone(
            connection,
            "SELECT name FROM schema_migrations WHERE version=?",
            (5,),
        )
    assert row == {"name": "saved picture searches"}


def test_existing_schema_one_is_backed_up_and_registered(tmp_path: Path) -> None:
    engine = make_engine(tmp_path)
    create_schema_one_without_history(engine)
    with engine.transaction() as connection:
        engine.execute(
            connection,
            "INSERT INTO sources (label, uri, uri_hash, enabled, available, created_at, updated_at) "
            "VALUES (?, ?, ?, 0, 1, ?, ?)",
            ("Photos", "/photos/", "hash", "2026-07-23", "2026-07-23"),
        ).close()

    result = MigrationRunner(engine).initialize()

    assert result.bootstrapped_history is True
    assert result.current_version == 9
    assert result.applied_versions == (2, 3, 4, 5, 6, 7, 8, 9)
    assert result.backup_path is not None
    backup_path = Path(result.backup_path)
    assert backup_path.is_file()
    with sqlite3.connect(str(backup_path)) as backup:
        assert backup.execute("PRAGMA quick_check").fetchone()[0] == "ok"
        assert backup.execute("SELECT COUNT(*) FROM sources").fetchone()[0] == 1
        assert backup.execute(
            "SELECT COUNT(*) FROM locks WHERE name=?", (MIGRATION_LOCK_NAME,)
        ).fetchone()[0] == 0
        assert backup.execute(
            "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name='schema_migrations'"
        ).fetchone()[0] == 0
        assert backup.execute(
            "SELECT COUNT(*) FROM sqlite_master WHERE type='index' "
            "AND name='idx_pictures_date_browse'"
        ).fetchone()[0] == 0
    with engine.transaction() as connection:
        assert engine.fetchone(
            connection, "SELECT value FROM meta WHERE key='schema_version'"
        )["value"] == "9"
        assert engine.fetchone(
            connection,
            "SELECT COUNT(*) AS total FROM schema_migrations",
        )["total"] == 9
        assert engine.fetchone(
            connection,
            "SELECT name FROM sqlite_master WHERE type='index' "
            "AND name='idx_pictures_date_browse'",
        ) is not None
        assert engine.table_exists(connection, "picture_search_documents")


def test_existing_schema_two_backfills_normalized_search_documents(tmp_path: Path) -> None:
    engine = make_engine(tmp_path)
    MigrationRunner(
        engine,
        target_version=2,
        migrations=(DATE_BROWSING_MIGRATION,),
    ).initialize()
    with engine.transaction(immediate=True) as connection:
        engine.execute(connection, "DROP TABLE picture_search_documents").close()
        source = engine.execute(
            connection,
            "INSERT INTO sources "
            "(label, uri, uri_hash, enabled, available, created_at, updated_at) "
            "VALUES (?, ?, ?, 1, 1, ?, ?)",
            ("Photos", "/srv/photos/", "search-source", "2026-07-24", "2026-07-24"),
        )
        source_id = int(source.lastrowid)
        source.close()
        folder = engine.execute(
            connection,
            "INSERT INTO folders "
            "(source_id, parent_uri, uri, uri_hash, name, discovered_at, last_seen_at, random_key, is_missing) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0)",
            (source_id, "", "/srv/photos/Åland/", "search-folder", "Åland", "2026-07-24", "2026-07-24", 0.5),
        )
        folder_id = int(folder.lastrowid)
        folder.close()
        picture = engine.execute(
            connection,
            "INSERT INTO pictures "
            "(source_id, folder_id, uri, uri_hash, filename, extension, file_size, file_mtime, "
            "discovered_at, last_seen_at, caption, camera_make, camera_model, city, country, "
            "random_key, favorite, is_missing) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, 0)",
            (
                source_id,
                folder_id,
                "/srv/photos/Åland/Sommar.jpg",
                "search-picture",
                "Sommar.jpg",
                "jpg",
                100,
                1.0,
                "2026-07-24",
                "2026-07-24",
                "Blå båt",
                "Fujifilm",
                "X-T5",
                "Göteborg",
                "Sverige",
                0.25,
            ),
        )
        picture_id = int(picture.lastrowid)
        picture.close()
        tag = engine.execute(
            connection,
            "INSERT INTO tags (name, normalized_name) VALUES (?, ?)",
            ("Familj", "familj"),
        )
        tag_id = int(tag.lastrowid)
        tag.close()
        engine.execute(
            connection,
            "INSERT INTO picture_tags (picture_id, tag_id) VALUES (?, ?)",
            (picture_id, tag_id),
        ).close()

    result = MigrationRunner(engine).initialize()

    assert result.previous_version == 2
    assert result.current_version == 9
    assert result.applied_versions == (3, 4, 5, 6, 7, 8, 9)
    assert result.backup_path is not None
    with engine.transaction() as connection:
        row = engine.fetchone(
            connection,
            "SELECT document FROM picture_search_documents WHERE picture_id=?",
            (picture_id,),
        )
        history = engine.fetchall(
            connection,
            "SELECT version FROM schema_migrations ORDER BY version",
        )
        media = engine.fetchone(
            connection,
            "SELECT media_type FROM pictures WHERE id=?",
            (picture_id,),
        )
    assert row is not None
    assert " åland " in row["document"]
    assert " sommar " in row["document"]
    assert " blå " in row["document"]
    assert " familj " in row["document"]
    assert " göteborg " in row["document"]
    assert media == {"media_type": "picture"}
    assert [item["version"] for item in history] == [1, 2, 3, 4, 5, 6, 7, 8, 9]


def test_schema_marker_reconciles_already_recorded_later_migration(tmp_path: Path) -> None:
    engine = make_engine(tmp_path)
    MigrationRunner(engine).initialize()
    with engine.transaction(immediate=True) as connection:
        engine.execute(connection, "DROP TABLE picture_search_documents").close()
        engine.execute(
            connection,
            "DELETE FROM schema_migrations WHERE version=?",
            (3,),
        ).close()
        engine.execute(
            connection,
            "UPDATE meta SET value=? WHERE key=?",
            ("2", "schema_version"),
        ).close()

    result = MigrationRunner(engine).initialize()

    assert result.previous_version == 2
    assert result.current_version == 9
    assert result.applied_versions == (3,)
    with engine.transaction() as connection:
        history = engine.fetchall(
            connection,
            "SELECT version FROM schema_migrations ORDER BY version",
        )
        schema_version = engine.fetchone(
            connection,
            "SELECT value FROM meta WHERE key=?",
            ("schema_version",),
        )
    assert [item["version"] for item in history] == [1, 2, 3, 4, 5, 6, 7, 8, 9]
    assert schema_version == {"value": "9"}


def test_newer_schema_is_rejected_before_any_schema_write(tmp_path: Path) -> None:
    database = tmp_path / "mypicsdb3.sqlite"
    with sqlite3.connect(str(database)) as connection:
        connection.execute("PRAGMA journal_mode=DELETE")
        connection.execute("CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
        connection.execute("INSERT INTO meta (key, value) VALUES ('schema_version', '99')")
        connection.execute("CREATE TABLE future_data (id INTEGER PRIMARY KEY)")

    with pytest.raises(SchemaTooNewError):
        MigrationRunner(make_engine(tmp_path)).initialize()

    with sqlite3.connect(str(database)) as connection:
        assert connection.execute("PRAGMA journal_mode").fetchone()[0].lower() == "delete"
        assert connection.execute(
            "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name='schema_migrations'"
        ).fetchone()[0] == 0
        assert connection.execute(
            "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name='future_data'"
        ).fetchone()[0] == 1


def test_registered_migration_runs_once_and_keeps_history(tmp_path: Path) -> None:
    engine = make_engine(tmp_path)
    create_schema_one_without_history(engine)
    step = migration_two()

    first = MigrationRunner(engine, target_version=2, migrations=(step,)).initialize()
    second = MigrationRunner(engine, target_version=2, migrations=(step,)).initialize()

    assert first.applied_versions == (2,)
    assert first.backup_path is not None
    assert second.applied_versions == ()
    assert second.backup_path is None
    assert len(list((tmp_path / "backups").glob("*.sqlite"))) == 1
    with engine.transaction() as connection:
        assert engine.fetchone(
            connection, "SELECT value FROM meta WHERE key='schema_version'"
        )["value"] == "2"
        assert engine.fetchone(
            connection, "SELECT COUNT(*) AS total FROM schema_migrations"
        )["total"] == 2
        assert engine.table_exists(connection, "future_feature")


def test_checksum_mismatch_stops_startup(tmp_path: Path) -> None:
    engine = make_engine(tmp_path)
    create_schema_one_without_history(engine)
    step = migration_two()
    MigrationRunner(engine, target_version=2, migrations=(step,)).initialize()
    with engine.transaction() as connection:
        engine.execute(
            connection,
            "UPDATE schema_migrations SET checksum=? WHERE version=2",
            ("0" * 64,),
        ).close()

    with pytest.raises(MigrationChecksumError):
        MigrationRunner(engine, target_version=2, migrations=(step,)).initialize()


def test_failed_sqlite_migration_rolls_back_schema_and_version(tmp_path: Path) -> None:
    engine = make_engine(tmp_path)
    create_schema_one_without_history(engine)

    def apply(engine, connection) -> None:
        engine.execute(connection, "CREATE TABLE should_rollback (id INTEGER PRIMARY KEY)").close()
        raise RuntimeError("simulated failure")

    step = MigrationStep(
        version=2,
        name="failing fixture",
        checksum=hashlib.sha256(b"test:migration:2:failing").hexdigest(),
        apply=apply,
    )
    with pytest.raises(RuntimeError, match="simulated failure"):
        MigrationRunner(engine, target_version=2, migrations=(step,)).initialize()

    with engine.transaction() as connection:
        assert not engine.table_exists(connection, "should_rollback")
        assert engine.fetchone(
            connection, "SELECT value FROM meta WHERE key='schema_version'"
        )["value"] == "1"
        assert engine.fetchone(
            connection, "SELECT COUNT(*) AS total FROM schema_migrations WHERE version=2"
        )["total"] == 0


def test_missing_migration_is_rejected_without_backup_or_history_write(tmp_path: Path) -> None:
    engine = make_engine(tmp_path)
    create_schema_one_without_history(engine)

    with pytest.raises(MigrationError, match="No migration is registered"):
        MigrationRunner(engine, target_version=2, migrations=()).initialize()

    assert not (tmp_path / "backups").exists()
    with engine.transaction() as connection:
        assert not engine.table_exists(connection, "schema_migrations")


def test_scan_and_migration_locks_block_each_other(tmp_path: Path) -> None:
    engine = make_engine(tmp_path)
    catalog = Catalog(engine)
    catalog.initialize()

    assert acquire_lock(engine, MIGRATION_LOCK_NAME, "migration", 60)
    try:
        assert not catalog.acquire_lock(SCAN_LOCK_NAME, "scan", 60)
    finally:
        release_lock(engine, MIGRATION_LOCK_NAME, "migration")

    with engine.transaction(immediate=True) as connection:
        engine.execute(connection, "DROP TABLE schema_migrations").close()
    assert catalog.acquire_lock(SCAN_LOCK_NAME, "scan", 60)
    try:
        with pytest.raises(MigrationLockError):
            MigrationRunner(engine).initialize()
    finally:
        catalog.release_lock(SCAN_LOCK_NAME, "scan")
    assert not (tmp_path / "backups").exists()


def test_metadata_refresh_lock_blocks_scans_and_migrations(tmp_path: Path) -> None:
    engine = make_engine(tmp_path)
    catalog = Catalog(engine)
    catalog.initialize()

    assert catalog.acquire_lock(METADATA_REFRESH_LOCK_NAME, "refresh", 60)
    try:
        assert not catalog.acquire_lock(SCAN_LOCK_NAME, "scan", 60)
        assert not acquire_lock(engine, MIGRATION_LOCK_NAME, "migration", 60)
    finally:
        catalog.release_lock(METADATA_REFRESH_LOCK_NAME, "refresh")


def test_existing_schema_six_adds_collection_music_playlists(tmp_path: Path) -> None:
    engine = make_engine(tmp_path)
    MigrationRunner(engine).initialize()
    with engine.transaction(immediate=True) as connection:
        engine.execute(connection, "DROP TABLE metadata_mapping_rules").close()
        engine.execute(connection, "DROP TABLE source_scan_policies").close()
        engine.execute(connection, "DROP TABLE collection_music_playlists").close()
        engine.execute(
            connection,
            "DELETE FROM schema_migrations WHERE version IN (?, ?, ?)",
            (7, 8, 9),
        ).close()
        engine.execute(
            connection,
            "UPDATE meta SET value=? WHERE key=?",
            ("6", "schema_version"),
        ).close()

    result = MigrationRunner(engine).initialize()

    assert result.previous_version == 6
    assert result.current_version == 9
    assert result.applied_versions == (7, 8, 9)
    assert result.backup_path is not None
    with engine.transaction() as connection:
        assert engine.table_exists(connection, "collection_music_playlists")
        assert engine.table_exists(connection, "source_scan_policies")
        row = engine.fetchone(
            connection,
            "SELECT name FROM schema_migrations WHERE version=?",
            (7,),
        )
    assert row == {"name": "collection music playlists"}


def test_existing_schema_seven_adds_source_scan_policies(tmp_path: Path) -> None:
    engine = make_engine(tmp_path)
    MigrationRunner(engine).initialize()
    with engine.transaction(immediate=True) as connection:
        engine.execute(connection, "DROP TABLE source_scan_policies").close()
        engine.execute(
            connection,
            "DELETE FROM schema_migrations WHERE version IN (?, ?)",
            (8, 9),
        ).close()
        engine.execute(
            connection,
            "UPDATE meta SET value=? WHERE key=?",
            ("7", "schema_version"),
        ).close()
        assert not engine.table_exists(connection, "source_scan_policies")

    result = MigrationRunner(engine).initialize()

    assert result.previous_version == 7
    assert result.current_version == 9
    assert result.applied_versions == (8, 9)
    assert result.backup_path is not None
    with engine.transaction() as connection:
        assert engine.table_exists(connection, "source_scan_policies")
        row = engine.fetchone(
            connection,
            "SELECT name FROM schema_migrations WHERE version=?",
            (8,),
        )
    assert row == {"name": "per-source scan policies"}


def test_existing_schema_eight_adds_metadata_mapping_and_reindex_hash(tmp_path: Path) -> None:
    engine = make_engine(tmp_path)
    MigrationRunner(engine).initialize()
    with engine.transaction(immediate=True) as connection:
        engine.execute(connection, "DROP TABLE metadata_mapping_rules").close()
        engine.execute(connection, "ALTER TABLE pictures DROP COLUMN metadata_index_hash").close()
        engine.execute(
            connection,
            "DELETE FROM schema_migrations WHERE version=?",
            (9,),
        ).close()
        engine.execute(
            connection,
            "UPDATE meta SET value=? WHERE key=?",
            ("8", "schema_version"),
        ).close()
        assert not engine.table_exists(connection, "metadata_mapping_rules")
        columns = engine.fetchall(connection, "PRAGMA table_info(pictures)")
        assert all(row["name"] != "metadata_index_hash" for row in columns)

    result = MigrationRunner(engine).initialize()

    assert result.previous_version == 8
    assert result.current_version == 9
    assert result.applied_versions == (9,)
    assert result.backup_path is not None
    with engine.transaction() as connection:
        assert engine.table_exists(connection, "metadata_mapping_rules")
        columns = engine.fetchall(connection, "PRAGMA table_info(pictures)")
        row = engine.fetchone(
            connection,
            "SELECT name FROM schema_migrations WHERE version=?",
            (9,),
        )
    assert any(item["name"] == "metadata_index_hash" for item in columns)
    assert row == {"name": "metadata mapping overrides"}
