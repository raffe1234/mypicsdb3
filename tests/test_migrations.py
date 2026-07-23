from __future__ import annotations

import hashlib
import sqlite3
from pathlib import Path

import pytest

from mypicsdb3.config import Settings
from mypicsdb3.db.catalog import Catalog
from mypicsdb3.db.engine import DatabaseEngine
from mypicsdb3.db.locks import MIGRATION_LOCK_NAME, SCAN_LOCK_NAME, acquire_lock, release_lock
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
    assert result.current_version == 2
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
    assert [row["version"] for row in rows] == [1, 2]
    assert rows[0]["name"] == "initial catalogue schema"
    assert rows[1]["name"] == "year-first date browsing index"
    assert all(len(row["checksum"]) == 64 for row in rows)
    assert index is not None
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
    assert result.current_version == 2
    assert result.applied_versions == (2,)
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
        )["value"] == "2"
        assert engine.fetchone(
            connection,
            "SELECT COUNT(*) AS total FROM schema_migrations",
        )["total"] == 2
        assert engine.fetchone(
            connection,
            "SELECT name FROM sqlite_master WHERE type='index' "
            "AND name='idx_pictures_date_browse'",
        ) is not None


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
