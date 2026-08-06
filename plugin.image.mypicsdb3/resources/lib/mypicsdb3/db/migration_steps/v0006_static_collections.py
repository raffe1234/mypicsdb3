from __future__ import annotations

import hashlib

from ..migration_step import MigrationStep


MIGRATION_NAME = "manual media collections"
MIGRATION_CHECKSUM = hashlib.sha256(
    b"mypicsdb3:schema:6:manual-media-collections"
).hexdigest()

SQLITE_COLLECTIONS = """CREATE TABLE IF NOT EXISTS collections (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
)"""

SQLITE_ITEMS = """CREATE TABLE IF NOT EXISTS collection_items (
    collection_id INTEGER NOT NULL,
    picture_id INTEGER NOT NULL,
    position INTEGER NOT NULL,
    added_at TEXT NOT NULL,
    PRIMARY KEY(collection_id, picture_id),
    UNIQUE(collection_id, position),
    FOREIGN KEY(collection_id) REFERENCES collections(id) ON DELETE CASCADE,
    FOREIGN KEY(picture_id) REFERENCES pictures(id) ON DELETE CASCADE
)"""

MYSQL_COLLECTIONS = """CREATE TABLE IF NOT EXISTS collections (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
    name VARCHAR(191) NOT NULL UNIQUE,
    created_at DATETIME(6) NOT NULL,
    updated_at DATETIME(6) NOT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin"""

MYSQL_ITEMS = """CREATE TABLE IF NOT EXISTS collection_items (
    collection_id BIGINT UNSIGNED NOT NULL,
    picture_id BIGINT UNSIGNED NOT NULL,
    position INT UNSIGNED NOT NULL,
    added_at DATETIME(6) NOT NULL,
    PRIMARY KEY(collection_id, picture_id),
    UNIQUE KEY uq_collection_items_position (collection_id, position),
    INDEX idx_collection_items_picture (picture_id),
    CONSTRAINT fk_collection_items_collection
        FOREIGN KEY(collection_id) REFERENCES collections(id) ON DELETE CASCADE,
    CONSTRAINT fk_collection_items_picture
        FOREIGN KEY(picture_id) REFERENCES pictures(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin"""

INDEX_NAME = "idx_collection_items_picture"


def _sqlite_index_exists(engine, connection) -> bool:
    return engine.fetchone(
        connection,
        "SELECT name FROM sqlite_master WHERE type='index' AND name=?",
        (INDEX_NAME,),
    ) is not None


def apply(engine, connection) -> None:
    if engine.backend == "mysql":
        engine.execute(connection, MYSQL_COLLECTIONS).close()
        engine.execute(connection, MYSQL_ITEMS).close()
        return
    engine.execute(connection, SQLITE_COLLECTIONS).close()
    engine.execute(connection, SQLITE_ITEMS).close()
    if not _sqlite_index_exists(engine, connection):
        engine.execute(
            connection,
            "CREATE INDEX %s ON collection_items(picture_id)" % INDEX_NAME,
        ).close()


MIGRATION = MigrationStep(
    version=6,
    name=MIGRATION_NAME,
    checksum=MIGRATION_CHECKSUM,
    apply=apply,
)
