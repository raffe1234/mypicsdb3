from __future__ import annotations

import hashlib

from ..migration_step import MigrationStep


MIGRATION_NAME = "collection music playlists"
MIGRATION_CHECKSUM = hashlib.sha256(
    b"mypicsdb3:schema:7:collection-music-playlists"
).hexdigest()

SQLITE_TABLE = """CREATE TABLE IF NOT EXISTS collection_music_playlists (
    collection_type TEXT NOT NULL,
    collection_id INTEGER NOT NULL,
    playlist_uri TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY(collection_type, collection_id),
    CHECK(collection_type IN ('smart', 'manual'))
)"""

MYSQL_TABLE = """CREATE TABLE IF NOT EXISTS collection_music_playlists (
    collection_type VARCHAR(16) NOT NULL,
    collection_id BIGINT UNSIGNED NOT NULL,
    playlist_uri TEXT NOT NULL,
    updated_at DATETIME(6) NOT NULL,
    PRIMARY KEY(collection_type, collection_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin"""


def apply(engine, connection) -> None:
    engine.execute(
        connection,
        MYSQL_TABLE if engine.backend == "mysql" else SQLITE_TABLE,
    ).close()


MIGRATION = MigrationStep(
    version=7,
    name=MIGRATION_NAME,
    checksum=MIGRATION_CHECKSUM,
    apply=apply,
)
