from __future__ import annotations

import hashlib

from ..migration_step import MigrationStep


MIGRATION_NAME = "mixed picture and video media type"
MIGRATION_CHECKSUM = hashlib.sha256(
    b"mypicsdb3:schema:4:mixed-picture-video-media-type"
).hexdigest()
COLUMN_NAME = "media_type"
INDEX_NAME = "idx_pictures_media_type"


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


def _index_exists(engine, connection) -> bool:
    if engine.backend == "mysql":
        return engine.fetchone(
            connection,
            "SELECT INDEX_NAME AS name FROM information_schema.STATISTICS "
            "WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='pictures' AND INDEX_NAME=?",
            (INDEX_NAME,),
        ) is not None
    return engine.fetchone(
        connection,
        "SELECT name FROM sqlite_master WHERE type='index' AND name=?",
        (INDEX_NAME,),
    ) is not None


def apply(engine, connection) -> None:
    if not _column_exists(engine, connection):
        if engine.backend == "mysql":
            engine.execute(
                connection,
                "ALTER TABLE pictures ADD COLUMN media_type VARCHAR(16) "
                "NOT NULL DEFAULT 'picture' AFTER extension",
            ).close()
        else:
            engine.execute(
                connection,
                "ALTER TABLE pictures ADD COLUMN media_type TEXT "
                "NOT NULL DEFAULT 'picture'",
            ).close()
    if not _index_exists(engine, connection):
        engine.execute(
            connection,
            "CREATE INDEX %s ON pictures(is_missing, media_type, taken_at)" % INDEX_NAME,
        ).close()


MIGRATION = MigrationStep(
    version=4,
    name=MIGRATION_NAME,
    checksum=MIGRATION_CHECKSUM,
    apply=apply,
)
