from __future__ import annotations

import hashlib

from ..migration_step import MigrationStep


MIGRATION_NAME = "saved picture searches"
MIGRATION_CHECKSUM = hashlib.sha256(
    b"mypicsdb3:schema:5:saved-picture-searches"
).hexdigest()

SQLITE_TABLE = """CREATE TABLE IF NOT EXISTS saved_searches (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    query_version INTEGER NOT NULL,
    query_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
)"""

MYSQL_TABLE = """CREATE TABLE IF NOT EXISTS saved_searches (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
    name VARCHAR(191) NOT NULL UNIQUE,
    query_version INT NOT NULL,
    query_json LONGTEXT NOT NULL,
    created_at DATETIME(6) NOT NULL,
    updated_at DATETIME(6) NOT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin"""


def apply(engine, connection) -> None:
    engine.execute(
        connection,
        MYSQL_TABLE if engine.backend == "mysql" else SQLITE_TABLE,
    ).close()


MIGRATION = MigrationStep(
    version=5,
    name=MIGRATION_NAME,
    checksum=MIGRATION_CHECKSUM,
    apply=apply,
)
