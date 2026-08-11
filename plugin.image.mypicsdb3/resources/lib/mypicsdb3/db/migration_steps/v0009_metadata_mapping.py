from __future__ import annotations

import hashlib

from ..migration_step import MigrationStep


MIGRATION_NAME = "metadata mapping overrides"
MIGRATION_CHECKSUM = hashlib.sha256(
    b"mypicsdb3:schema:9:metadata-mapping-overrides"
).hexdigest()
COLUMN_NAME = "metadata_index_hash"

SQLITE_TABLE = """CREATE TABLE IF NOT EXISTS metadata_mapping_rules (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_type TEXT NOT NULL,
    source_tag TEXT NOT NULL,
    normalized_tag TEXT NOT NULL,
    target_field TEXT,
    rule_priority INTEGER NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(source_type, normalized_tag)
)"""

MYSQL_TABLE = """CREATE TABLE IF NOT EXISTS metadata_mapping_rules (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
    source_type VARCHAR(16) NOT NULL,
    source_tag VARCHAR(191) NOT NULL,
    normalized_tag VARCHAR(191) NOT NULL,
    target_field VARCHAR(32) NULL,
    rule_priority INT NOT NULL,
    created_at DATETIME(6) NOT NULL,
    updated_at DATETIME(6) NOT NULL,
    UNIQUE KEY uq_metadata_mapping_source_tag (source_type, normalized_tag)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin"""


def _column_exists(engine, connection) -> bool:
    if engine.backend == "mysql":
        return engine.fetchone(
            connection,
            "SELECT COLUMN_NAME AS name FROM information_schema.COLUMNS "
            "WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='pictures' AND COLUMN_NAME=?",
            (COLUMN_NAME,),
        ) is not None
    return any(
        str(row.get("name")) == COLUMN_NAME
        for row in engine.fetchall(connection, "PRAGMA table_info(pictures)")
    )


def apply(engine, connection) -> None:
    engine.execute(connection, MYSQL_TABLE if engine.backend == "mysql" else SQLITE_TABLE).close()
    if not _column_exists(engine, connection):
        if engine.backend == "mysql":
            engine.execute(
                connection,
                "ALTER TABLE pictures ADD COLUMN metadata_index_hash CHAR(64) NULL AFTER metadata_hash",
            ).close()
        else:
            engine.execute(
                connection,
                "ALTER TABLE pictures ADD COLUMN metadata_index_hash TEXT",
            ).close()


MIGRATION = MigrationStep(
    version=9,
    name=MIGRATION_NAME,
    checksum=MIGRATION_CHECKSUM,
    apply=apply,
)
