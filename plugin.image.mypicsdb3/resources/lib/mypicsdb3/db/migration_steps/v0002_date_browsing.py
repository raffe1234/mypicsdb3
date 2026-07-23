from __future__ import annotations

import hashlib

from ..migration_step import MigrationStep


MIGRATION_NAME = "year-first date browsing index"
MIGRATION_CHECKSUM = hashlib.sha256(
    b"mypicsdb3:schema:2:year-first-date-browsing-index"
).hexdigest()
INDEX_NAME = "idx_pictures_date_browse"


def _index_exists(engine, connection) -> bool:
    if engine.backend == "mysql":
        row = engine.fetchone(
            connection,
            "SELECT INDEX_NAME AS name FROM information_schema.STATISTICS "
            "WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='pictures' AND INDEX_NAME=?",
            (INDEX_NAME,),
        )
        return row is not None
    row = engine.fetchone(
        connection,
        "SELECT name FROM sqlite_master WHERE type='index' AND name=?",
        (INDEX_NAME,),
    )
    return row is not None


def apply(engine, connection) -> None:
    if _index_exists(engine, connection):
        return
    engine.execute(
        connection,
        "CREATE INDEX %s ON pictures"
        "(is_missing, taken_year, taken_month, taken_day, taken_at)" % INDEX_NAME,
    ).close()


MIGRATION = MigrationStep(
    version=2,
    name=MIGRATION_NAME,
    checksum=MIGRATION_CHECKSUM,
    apply=apply,
)
