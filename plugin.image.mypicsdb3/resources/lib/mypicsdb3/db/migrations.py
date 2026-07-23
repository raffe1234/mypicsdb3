from __future__ import annotations

import os
import shutil
import socket
import sqlite3
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Optional, Sequence, Tuple

from .. import SCHEMA_VERSION, VERSION
from .locks import MIGRATION_LOCK_NAME, acquire_lock, refresh_lock, release_lock
from .migration_step import MigrationStep
from .migration_steps import BASELINE_CHECKSUM, BASELINE_NAME
from .schema import create_schema


class MigrationError(RuntimeError):
    """Base class for safe, user-visible migration failures."""


class SchemaTooNewError(MigrationError):
    pass


class MigrationLockError(MigrationError):
    pass


class MigrationChecksumError(MigrationError):
    pass


from .migration_steps.v0002_date_browsing import MIGRATION as DATE_BROWSING_MIGRATION


@dataclass(frozen=True)
class SchemaState:
    is_empty: bool
    version: Optional[int]
    tables: Tuple[str, ...]
    history_versions: Tuple[int, ...]


@dataclass(frozen=True)
class MigrationResult:
    previous_version: Optional[int]
    current_version: int
    created_database: bool = False
    bootstrapped_history: bool = False
    applied_versions: Tuple[int, ...] = ()
    backup_path: Optional[str] = None


SQLITE_MIGRATION_TABLE = """CREATE TABLE IF NOT EXISTS schema_migrations (
    version INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    checksum TEXT NOT NULL,
    applied_at TEXT NOT NULL,
    addon_version TEXT NOT NULL
)"""

MYSQL_MIGRATION_TABLE = """CREATE TABLE IF NOT EXISTS schema_migrations (
    version INT NOT NULL PRIMARY KEY,
    name VARCHAR(191) NOT NULL,
    checksum CHAR(64) NOT NULL,
    applied_at DATETIME(6) NOT NULL,
    addon_version VARCHAR(32) NOT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin"""

DEFAULT_MIGRATIONS: Tuple[MigrationStep, ...] = (DATE_BROWSING_MIGRATION,)
MIGRATION_LOCK_TTL_SECONDS = 7200


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S.%f")


def _schema_version_select(engine) -> str:
    return "SELECT value FROM meta WHERE `key`=?" if engine.backend == "mysql" else "SELECT value FROM meta WHERE key=?"


def _schema_version_insert(engine) -> str:
    return "INSERT INTO meta (`key`, value) VALUES (?, ?)" if engine.backend == "mysql" else "INSERT INTO meta (key, value) VALUES (?, ?)"


def _schema_version_update(engine) -> str:
    return "UPDATE meta SET value=? WHERE `key`=?" if engine.backend == "mysql" else "UPDATE meta SET value=? WHERE key=?"


def _backup_size(path: Path) -> int:
    total = 0
    for candidate in (path, Path(str(path) + "-wal"), Path(str(path) + "-shm")):
        try:
            total += candidate.stat().st_size
        except FileNotFoundError:
            pass
    return total


def backup_sqlite_database(database_path: str, schema_version: int, logger=None) -> str:
    """Create and verify an atomic SQLite backup before a schema mutation."""
    source_path = Path(database_path)
    if not source_path.is_file():
        raise MigrationError("The SQLite database does not exist and cannot be backed up")

    backup_dir = source_path.parent / "backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    required = _backup_size(source_path)
    reserve = max(10 * 1024 * 1024, required // 10)
    free = shutil.disk_usage(str(backup_dir)).free
    if free < required + reserve:
        raise MigrationError(
            "Not enough free space for a safe SQLite migration backup "
            "(need approximately %d bytes, have %d)" % (required + reserve, free)
        )

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    final_path = backup_dir / ("mypicsdb3-before-schema-%d-%s.sqlite" % (schema_version, stamp))
    partial_path = Path(str(final_path) + ".partial")

    source = None
    destination = None
    try:
        source = sqlite3.connect(str(source_path), timeout=30)
        source.execute("PRAGMA busy_timeout=30000")
        source.execute("PRAGMA wal_checkpoint(FULL)")
        destination = sqlite3.connect(str(partial_path))
        source.backup(destination)
        destination.execute("DELETE FROM locks WHERE name=?", (MIGRATION_LOCK_NAME,))
        destination.commit()
        check = destination.execute("PRAGMA quick_check").fetchone()
        if not check or str(check[0]).lower() != "ok":
            raise MigrationError("The SQLite migration backup failed its integrity check")
        destination.close()
        destination = None
        source.close()
        source = None
        os.replace(str(partial_path), str(final_path))
    except Exception:
        if destination is not None:
            destination.close()
        if source is not None:
            source.close()
        try:
            partial_path.unlink()
        except FileNotFoundError:
            pass
        raise

    if logger:
        logger.info("Created SQLite migration backup: %s", final_path)
    return str(final_path)


class MigrationRunner:
    def __init__(
        self,
        engine,
        logger=None,
        target_version: int = SCHEMA_VERSION,
        migrations: Optional[Sequence[MigrationStep]] = None,
        addon_version: str = VERSION,
    ):
        self.engine = engine
        self.logger = logger
        self.target_version = int(target_version)
        self.addon_version = addon_version
        self.migrations = tuple(migrations if migrations is not None else DEFAULT_MIGRATIONS)
        self._migration_by_version: Dict[int, MigrationStep] = {}
        for migration in self.migrations:
            if migration.version <= 1:
                raise ValueError("Migration versions must be greater than the schema 1 baseline")
            if migration.version in self._migration_by_version:
                raise ValueError("Duplicate migration version %d" % migration.version)
            self._migration_by_version[migration.version] = migration

    def inspect(self) -> SchemaState:
        if self.engine.backend == "sqlite" and not Path(self.engine.settings.sqlite_path).exists():
            return SchemaState(True, None, (), ())
        connection = self.engine.connect_readonly()
        try:
            tables = tuple(self.engine.list_tables(connection))
            if "meta" not in tables:
                if not tables:
                    return SchemaState(True, None, tables, ())
                raise MigrationError(
                    "The database contains tables but has no MyPicsDB 3 schema version marker"
                )
            row = self.engine.fetchone(connection, _schema_version_select(self.engine), ("schema_version",))
            if row is None:
                raise MigrationError("The database meta table has no schema_version value")
            try:
                version = int(row["value"])
            except (TypeError, ValueError) as exc:
                raise MigrationError("The database schema_version value is invalid") from exc
            history_versions: Tuple[int, ...] = ()
            if "schema_migrations" in tables:
                history_versions = tuple(
                    int(item["version"])
                    for item in self.engine.fetchall(
                        connection,
                        "SELECT version FROM schema_migrations ORDER BY version",
                    )
                )
            return SchemaState(False, version, tables, history_versions)
        finally:
            connection.close()

    def initialize(self) -> MigrationResult:
        state = self.inspect()
        if state.is_empty:
            return self._create_database()
        if state.version is None:
            raise MigrationError("Could not determine the database schema version")
        self._reject_newer_schema(state.version)
        self._validate_migration_path(state.version)

        history_complete = 1 in state.history_versions
        if state.version == self.target_version and history_complete:
            self._validate_history()
            return MigrationResult(state.version, state.version)

        owner = "%s:%s:%s" % (socket.gethostname(), os.getpid(), uuid.uuid4().hex[:12])
        if "locks" not in state.tables:
            raise MigrationError("The schema 1 database is missing its locks table")
        if not acquire_lock(
            self.engine,
            MIGRATION_LOCK_NAME,
            owner,
            MIGRATION_LOCK_TTL_SECONDS,
        ):
            raise MigrationLockError(
                "A catalogue scan or another database migration is already running"
            )

        backup_path = None
        applied = []
        bootstrapped = False
        previous_version = state.version
        try:
            locked_state = self.inspect()
            if locked_state.version is None:
                raise MigrationError("Could not determine the locked database schema version")
            self._reject_newer_schema(locked_state.version)
            needs_change = (
                locked_state.version < self.target_version
                or 1 not in locked_state.history_versions
            )
            if not needs_change:
                self._validate_history()
                return MigrationResult(previous_version, locked_state.version)

            if self.engine.backend == "sqlite":
                backup_path = backup_sqlite_database(
                    self.engine.settings.sqlite_path,
                    locked_state.version,
                    self.logger,
                )
            else:
                self._mysql_preflight()

            if not refresh_lock(
                self.engine,
                MIGRATION_LOCK_NAME,
                owner,
                MIGRATION_LOCK_TTL_SECONDS,
            ):
                raise MigrationLockError("The database migration lock was lost")

            bootstrapped = self._bootstrap_history(locked_state.version)
            self._validate_history()
            current_version = locked_state.version
            for version in range(current_version + 1, self.target_version + 1):
                migration = self._migration_by_version.get(version)
                if migration is None:
                    raise MigrationError("No migration is registered for schema version %d" % version)
                if not refresh_lock(
                    self.engine,
                    MIGRATION_LOCK_NAME,
                    owner,
                    MIGRATION_LOCK_TTL_SECONDS,
                ):
                    raise MigrationLockError("The database migration lock was lost")
                self._apply_migration(migration)
                applied.append(version)
                current_version = version
            self._validate_history()
            return MigrationResult(
                previous_version,
                current_version,
                bootstrapped_history=bootstrapped,
                applied_versions=tuple(applied),
                backup_path=backup_path,
            )
        finally:
            release_lock(self.engine, MIGRATION_LOCK_NAME, owner)

    def _create_database(self) -> MigrationResult:
        self._validate_migration_path(1)
        with self.engine.transaction(immediate=True) as connection:
            create_schema(self.engine, connection)
            self._ensure_migration_table(connection)
            self._write_schema_version(connection, self.target_version)
            self._record_baseline(connection)
            for version in range(2, self.target_version + 1):
                migration = self._migration_by_version[version]
                self._record_migration(connection, migration)
        return MigrationResult(None, self.target_version, created_database=True)

    def _validate_migration_path(self, current_version: int) -> None:
        if current_version < 1:
            raise MigrationError("Schema versions older than 1 are not supported")
        missing = [
            version
            for version in range(current_version + 1, self.target_version + 1)
            if version not in self._migration_by_version
        ]
        if missing:
            raise MigrationError(
                "No migration is registered for schema version(s): %s"
                % ", ".join(str(value) for value in missing)
            )

    def _reject_newer_schema(self, version: int) -> None:
        if version > self.target_version:
            raise SchemaTooNewError(
                "The database schema (%d) is newer than this add-on supports (%d); "
                "the database was not modified" % (version, self.target_version)
            )

    def _ensure_migration_table(self, connection) -> None:
        statement = MYSQL_MIGRATION_TABLE if self.engine.backend == "mysql" else SQLITE_MIGRATION_TABLE
        self.engine.execute(connection, statement).close()

    def _write_schema_version(self, connection, version: int) -> None:
        row = self.engine.fetchone(connection, _schema_version_select(self.engine), ("schema_version",))
        if row is None:
            self.engine.execute(
                connection,
                _schema_version_insert(self.engine),
                ("schema_version", str(version)),
            ).close()
        else:
            self.engine.execute(
                connection,
                _schema_version_update(self.engine),
                (str(version), "schema_version"),
            ).close()

    def _record_baseline(self, connection) -> None:
        row = self.engine.fetchone(
            connection,
            "SELECT version, checksum FROM schema_migrations WHERE version=?",
            (1,),
        )
        if row is None:
            self.engine.execute(
                connection,
                "INSERT INTO schema_migrations "
                "(version, name, checksum, applied_at, addon_version) VALUES (?, ?, ?, ?, ?)",
                (1, BASELINE_NAME, BASELINE_CHECKSUM, _utc_now(), self.addon_version),
            ).close()
        elif str(row["checksum"]) != BASELINE_CHECKSUM:
            raise MigrationChecksumError("Schema 1 baseline checksum does not match this add-on")

    def _bootstrap_history(self, current_version: int) -> bool:
        with self.engine.transaction(immediate=True) as connection:
            existed = self.engine.table_exists(connection, "schema_migrations")
            self._ensure_migration_table(connection)
            self._record_baseline(connection)
            # A future database may have been migrated by an older runner that
            # updated meta but failed to retain a complete history. Refuse to
            # invent those records: only schema 1 is safe to register as a
            # known baseline.
            if current_version > 1:
                rows = self.engine.fetchall(
                    connection,
                    "SELECT version FROM schema_migrations WHERE version>1 ORDER BY version",
                )
                recorded = {int(row["version"]) for row in rows}
                missing = [version for version in range(2, current_version + 1) if version not in recorded]
                if missing:
                    raise MigrationError(
                        "Migration history is incomplete for schema version(s): %s"
                        % ", ".join(str(value) for value in missing)
                    )
        return not existed or current_version == 1

    def _expected_checksums(self) -> Dict[int, str]:
        expected = {1: BASELINE_CHECKSUM}
        expected.update({step.version: step.checksum for step in self.migrations})
        return expected

    def _validate_history(self) -> None:
        connection = self.engine.connect_readonly()
        try:
            if not self.engine.table_exists(connection, "schema_migrations"):
                raise MigrationError("The schema_migrations table is missing")
            rows = self.engine.fetchall(
                connection,
                "SELECT version, checksum FROM schema_migrations ORDER BY version",
            )
            expected = self._expected_checksums()
            recorded = set()
            for row in rows:
                version = int(row["version"])
                recorded.add(version)
                if version not in expected:
                    raise MigrationChecksumError(
                        "The database contains unknown migration version %d" % version
                    )
                if str(row["checksum"]) != expected[version]:
                    raise MigrationChecksumError(
                        "Migration checksum mismatch for schema version %d" % version
                    )
            version_row = self.engine.fetchone(
                connection,
                _schema_version_select(self.engine),
                ("schema_version",),
            )
            current_version = int(version_row["value"]) if version_row else 0
            missing = [version for version in range(1, current_version + 1) if version not in recorded]
            if missing:
                raise MigrationError(
                    "Migration history is incomplete for schema version(s): %s"
                    % ", ".join(str(value) for value in missing)
                )
        finally:
            connection.close()

    def _record_migration(self, connection, migration: MigrationStep) -> None:
        self.engine.execute(
            connection,
            "INSERT INTO schema_migrations "
            "(version, name, checksum, applied_at, addon_version) VALUES (?, ?, ?, ?, ?)",
            (
                migration.version,
                migration.name,
                migration.checksum,
                _utc_now(),
                self.addon_version,
            ),
        ).close()

    def _apply_migration(self, migration: MigrationStep) -> None:
        with self.engine.transaction(immediate=True) as connection:
            migration.apply(self.engine, connection)
            self._write_schema_version(connection, migration.version)
            self._record_migration(connection, migration)
        if self.logger:
            self.logger.info(
                "Applied database migration %d: %s",
                migration.version,
                migration.name,
            )

    def _mysql_preflight(self) -> None:
        connection = self.engine.connect()
        try:
            row = self.engine.fetchone(connection, "SELECT VERSION() AS version")
            if not row or not row.get("version"):
                raise MigrationError("Could not determine the MySQL/MariaDB server version")
            if self.logger:
                self.logger.warning(
                    "MySQL/MariaDB schema migration starting on server %s. "
                    "Confirm that an external database backup exists.",
                    row["version"],
                )
        finally:
            connection.close()
