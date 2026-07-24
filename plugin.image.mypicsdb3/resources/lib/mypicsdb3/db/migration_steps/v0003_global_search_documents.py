from __future__ import annotations

import hashlib
from typing import Any, Dict, List, Tuple

from ...search_index import build_picture_search_document
from ..migration_step import MigrationStep


MIGRATION_NAME = "normalized global search documents"
MIGRATION_CHECKSUM = hashlib.sha256(
    b"mypicsdb3:schema:3:normalized-global-search-documents"
).hexdigest()
BACKFILL_BATCH_SIZE = 500


SQLITE_TABLE = """CREATE TABLE IF NOT EXISTS picture_search_documents (
    picture_id INTEGER PRIMARY KEY,
    document TEXT NOT NULL,
    FOREIGN KEY(picture_id) REFERENCES pictures(id) ON DELETE CASCADE
)"""

MYSQL_TABLE = """CREATE TABLE IF NOT EXISTS picture_search_documents (
    picture_id BIGINT UNSIGNED NOT NULL PRIMARY KEY,
    document TEXT NOT NULL,
    CONSTRAINT fk_picture_search_documents_picture
        FOREIGN KEY(picture_id) REFERENCES pictures(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin"""


def _placeholders(count: int) -> str:
    return ",".join("?" for _ in range(count))


def _tag_map(engine, connection, picture_ids: Tuple[int, ...]) -> Dict[int, List[str]]:
    if not picture_ids:
        return {}
    rows = engine.fetchall(
        connection,
        "SELECT pt.picture_id, t.name FROM picture_tags pt "
        "JOIN tags t ON t.id=pt.tag_id "
        "WHERE pt.picture_id IN (%s) ORDER BY pt.picture_id, t.name"
        % _placeholders(len(picture_ids)),
        picture_ids,
    )
    result: Dict[int, List[str]] = {}
    for row in rows:
        result.setdefault(int(row["picture_id"]), []).append(str(row["name"]))
    return result


def _backfill(engine, connection) -> None:
    engine.execute(connection, "DELETE FROM picture_search_documents").close()
    last_id = 0
    while True:
        pictures = engine.fetchall(
            connection,
            "SELECT id, uri, filename, caption, camera_make, camera_model, "
            "city, state, country, sublocation FROM pictures "
            "WHERE id>? ORDER BY id LIMIT ?",
            (last_id, BACKFILL_BATCH_SIZE),
        )
        if not pictures:
            break
        picture_ids = tuple(int(row["id"]) for row in pictures)
        keywords = _tag_map(engine, connection, picture_ids)
        documents: List[Tuple[int, str]] = []
        for row in pictures:
            picture_id = int(row["id"])
            documents.append(
                (
                    picture_id,
                    build_picture_search_document(
                        row,
                        keywords.get(picture_id, ()),
                    ),
                )
            )
        cursor = engine.executemany(
            connection,
            "INSERT INTO picture_search_documents (picture_id, document) VALUES (?, ?)",
            documents,
        )
        cursor.close()
        last_id = picture_ids[-1]


def apply(engine, connection) -> None:
    table = MYSQL_TABLE if engine.backend == "mysql" else SQLITE_TABLE
    engine.execute(connection, table).close()
    _backfill(engine, connection)


MIGRATION = MigrationStep(
    version=3,
    name=MIGRATION_NAME,
    checksum=MIGRATION_CHECKSUM,
    apply=apply,
)
