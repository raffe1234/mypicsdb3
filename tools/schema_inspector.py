#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional


def _schema_fingerprint(tables: Iterable[Dict[str, Any]]) -> str:
    canonical = json.dumps(list(tables), ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _quote_sqlite(identifier: str) -> str:
    return '"%s"' % identifier.replace('"', '""')


def _quote_mysql(identifier: str) -> str:
    return "`%s`" % identifier.replace("`", "``")


def inspect_sqlite(path: str, include_row_counts: bool = True) -> Dict[str, Any]:
    database_path = Path(path).expanduser().resolve()
    if not database_path.is_file():
        raise FileNotFoundError(str(database_path))

    connection = sqlite3.connect(database_path.as_uri() + "?mode=ro", uri=True, timeout=30)
    connection.row_factory = sqlite3.Row
    try:
        table_rows = connection.execute(
            "SELECT name, sql FROM sqlite_master "
            "WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
        ).fetchall()
        tables: List[Dict[str, Any]] = []
        for table_row in table_rows:
            name = str(table_row["name"])
            columns = [
                {
                    "position": int(row["cid"]),
                    "name": str(row["name"]),
                    "type": str(row["type"] or ""),
                    "not_null": bool(row["notnull"]),
                    "default": row["dflt_value"],
                    "primary_key_position": int(row["pk"]),
                }
                for row in connection.execute("PRAGMA table_info(%s)" % _quote_sqlite(name)).fetchall()
            ]
            indexes = []
            for index_row in connection.execute("PRAGMA index_list(%s)" % _quote_sqlite(name)).fetchall():
                index_name = str(index_row["name"])
                index_columns = [
                    str(row["name"])
                    for row in connection.execute(
                        "PRAGMA index_info(%s)" % _quote_sqlite(index_name)
                    ).fetchall()
                    if row["name"] is not None
                ]
                indexes.append(
                    {
                        "name": index_name,
                        "unique": bool(index_row["unique"]),
                        "origin": str(index_row["origin"]),
                        "partial": bool(index_row["partial"]),
                        "columns": index_columns,
                    }
                )
            foreign_keys = [
                {
                    "id": int(row["id"]),
                    "sequence": int(row["seq"]),
                    "target_table": str(row["table"]),
                    "from": str(row["from"]),
                    "to": str(row["to"]),
                    "on_update": str(row["on_update"]),
                    "on_delete": str(row["on_delete"]),
                }
                for row in connection.execute(
                    "PRAGMA foreign_key_list(%s)" % _quote_sqlite(name)
                ).fetchall()
            ]
            table: Dict[str, Any] = {
                "name": name,
                "create_sql": table_row["sql"],
                "columns": columns,
                "indexes": indexes,
                "foreign_keys": foreign_keys,
            }
            if include_row_counts:
                table["row_count"] = int(
                    connection.execute(
                        "SELECT COUNT(*) FROM %s" % _quote_sqlite(name)
                    ).fetchone()[0]
                )
            tables.append(table)

        schema_version = None
        migrations: List[Dict[str, Any]] = []
        names = {table["name"] for table in tables}
        if "meta" in names:
            row = connection.execute(
                "SELECT value FROM meta WHERE key=?", ("schema_version",)
            ).fetchone()
            schema_version = row[0] if row else None
        if "schema_migrations" in names:
            migrations = [
                dict(row)
                for row in connection.execute(
                    "SELECT version, name, checksum, applied_at, addon_version "
                    "FROM schema_migrations ORDER BY version"
                ).fetchall()
            ]

        schema_only = [
            {
                "name": table["name"],
                "columns": table["columns"],
                "indexes": table["indexes"],
                "foreign_keys": table["foreign_keys"],
            }
            for table in tables
        ]
        return {
            "backend": "sqlite",
            "database": str(database_path),
            "file_size": database_path.stat().st_size,
            "schema_version": schema_version,
            "migration_history": migrations,
            "schema_fingerprint": _schema_fingerprint(schema_only),
            "tables": tables,
        }
    finally:
        connection.close()


def inspect_mysql(
    host: str,
    port: int,
    database: str,
    username: str,
    password: str,
    include_row_counts: bool = True,
) -> Dict[str, Any]:
    try:
        import pymysql  # type: ignore
    except ImportError as exc:
        raise RuntimeError("PyMySQL is required for MySQL/MariaDB inspection") from exc

    connection = pymysql.connect(
        host=host,
        port=port,
        user=username,
        password=password,
        database=database,
        charset="utf8mb4",
        autocommit=True,
        cursorclass=pymysql.cursors.DictCursor,
        connect_timeout=10,
        read_timeout=60,
    )
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT VERSION() AS version")
            server_version = str(cursor.fetchone()["version"])
            cursor.execute(
                "SELECT TABLE_NAME AS name FROM information_schema.TABLES "
                "WHERE TABLE_SCHEMA=%s ORDER BY TABLE_NAME",
                (database,),
            )
            table_names = [str(row["name"]) for row in cursor.fetchall()]

            tables: List[Dict[str, Any]] = []
            for name in table_names:
                cursor.execute(
                    "SELECT ORDINAL_POSITION AS position, COLUMN_NAME AS name, "
                    "COLUMN_TYPE AS type, IS_NULLABLE AS nullable, COLUMN_DEFAULT AS default_value, "
                    "COLUMN_KEY AS column_key, EXTRA AS extra "
                    "FROM information_schema.COLUMNS "
                    "WHERE TABLE_SCHEMA=%s AND TABLE_NAME=%s ORDER BY ORDINAL_POSITION",
                    (database, name),
                )
                columns = [dict(row) for row in cursor.fetchall()]
                cursor.execute(
                    "SELECT INDEX_NAME AS name, NON_UNIQUE AS non_unique, SEQ_IN_INDEX AS sequence, "
                    "COLUMN_NAME AS column_name FROM information_schema.STATISTICS "
                    "WHERE TABLE_SCHEMA=%s AND TABLE_NAME=%s ORDER BY INDEX_NAME, SEQ_IN_INDEX",
                    (database, name),
                )
                grouped: Dict[str, Dict[str, Any]] = {}
                for row in cursor.fetchall():
                    index = grouped.setdefault(
                        str(row["name"]),
                        {
                            "name": str(row["name"]),
                            "unique": not bool(row["non_unique"]),
                            "columns": [],
                        },
                    )
                    index["columns"].append(str(row["column_name"]))
                table: Dict[str, Any] = {
                    "name": name,
                    "columns": columns,
                    "indexes": list(grouped.values()),
                }
                if include_row_counts:
                    cursor.execute("SELECT COUNT(*) AS total FROM %s" % _quote_mysql(name))
                    table["row_count"] = int(cursor.fetchone()["total"])
                tables.append(table)

            schema_version = None
            migrations: List[Dict[str, Any]] = []
            if "meta" in table_names:
                cursor.execute("SELECT value FROM meta WHERE `key`=%s", ("schema_version",))
                row = cursor.fetchone()
                schema_version = row["value"] if row else None
            if "schema_migrations" in table_names:
                cursor.execute(
                    "SELECT version, name, checksum, applied_at, addon_version "
                    "FROM schema_migrations ORDER BY version"
                )
                migrations = [dict(row) for row in cursor.fetchall()]

        schema_only = [
            {"name": table["name"], "columns": table["columns"], "indexes": table["indexes"]}
            for table in tables
        ]
        return {
            "backend": "mysql",
            "database": database,
            "server": "%s:%d" % (host, port),
            "server_version": server_version,
            "schema_version": schema_version,
            "migration_history": migrations,
            "schema_fingerprint": _schema_fingerprint(schema_only),
            "tables": tables,
        }
    finally:
        connection.close()
