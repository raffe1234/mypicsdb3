from __future__ import annotations

import hashlib

from ..migration_step import MigrationStep


MIGRATION_NAME = "per-source scan policies"
MIGRATION_CHECKSUM = hashlib.sha256(
    b"mypicsdb3:schema:8:per-source-scan-policies"
).hexdigest()

SQLITE_TABLE = """CREATE TABLE IF NOT EXISTS source_scan_policies (
    source_id INTEGER PRIMARY KEY,
    `recursive` INTEGER NOT NULL,
    include_videos INTEGER NOT NULL,
    picture_extensions TEXT NOT NULL,
    video_extensions TEXT NOT NULL,
    exclude_fragments TEXT NOT NULL,
    exclude_hidden INTEGER NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY(source_id) REFERENCES sources(id) ON DELETE CASCADE
)"""

MYSQL_TABLE = """CREATE TABLE IF NOT EXISTS source_scan_policies (
    source_id BIGINT UNSIGNED NOT NULL PRIMARY KEY,
    `recursive` TINYINT(1) NOT NULL,
    include_videos TINYINT(1) NOT NULL,
    picture_extensions TEXT NOT NULL,
    video_extensions TEXT NOT NULL,
    exclude_fragments TEXT NOT NULL,
    exclude_hidden TINYINT(1) NOT NULL,
    updated_at DATETIME(6) NOT NULL,
    CONSTRAINT fk_source_scan_policies_source
        FOREIGN KEY(source_id) REFERENCES sources(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin"""


def apply(engine, connection) -> None:
    engine.execute(
        connection,
        MYSQL_TABLE if engine.backend == "mysql" else SQLITE_TABLE,
    ).close()


MIGRATION = MigrationStep(
    version=8,
    name=MIGRATION_NAME,
    checksum=MIGRATION_CHECKSUM,
    apply=apply,
)
