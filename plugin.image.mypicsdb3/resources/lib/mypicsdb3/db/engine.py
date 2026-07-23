from __future__ import annotations

import contextlib
import os
import re
import sqlite3
from pathlib import Path
from typing import Any, Dict, Iterator, Optional, Sequence

from ..config import Settings


class DatabaseEngine:
    def __init__(self, settings: Settings, logger=None):
        self.settings = settings
        self.backend = settings.database_backend
        self.logger = logger
        self.integrity_errors = (sqlite3.IntegrityError,)
        if self.backend == "mysql":
            try:
                import pymysql  # type: ignore
            except ImportError as exc:
                raise RuntimeError("PyMySQL is required for MySQL/MariaDB mode") from exc
            self.pymysql = pymysql
            self.integrity_errors = (sqlite3.IntegrityError, pymysql.IntegrityError)
        else:
            self.pymysql = None

    def _connect_sqlite(self):
        directory = os.path.dirname(self.settings.sqlite_path)
        if directory:
            os.makedirs(directory, exist_ok=True)
        connection = sqlite3.connect(self.settings.sqlite_path, timeout=30, check_same_thread=False)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA synchronous=NORMAL")
        connection.execute("PRAGMA busy_timeout=30000")
        return connection

    def _mysql_kwargs(self, include_database: bool = True) -> Dict[str, Any]:
        kwargs: Dict[str, Any] = {
            "host": self.settings.mysql_host,
            "port": self.settings.mysql_port,
            "user": self.settings.mysql_username,
            "password": self.settings.mysql_password,
            "charset": "utf8mb4",
            "connect_timeout": self.settings.mysql_connect_timeout,
            "read_timeout": 60,
            "write_timeout": 60,
            "autocommit": False,
            "cursorclass": self.pymysql.cursors.DictCursor,
        }
        if include_database:
            kwargs["database"] = self.settings.mysql_database
        return kwargs

    def _connect_mysql(self):
        try:
            return self.pymysql.connect(**self._mysql_kwargs(True))
        except self.pymysql.err.OperationalError as exc:
            if not self.settings.mysql_auto_create or exc.args[0] not in {1049}:
                raise
            database = self.settings.mysql_database
            if not re.fullmatch(r"[A-Za-z0-9_]+", database):
                raise RuntimeError("The MySQL database name may contain only letters, numbers and underscores")
            connection = self.pymysql.connect(**self._mysql_kwargs(False))
            try:
                with connection.cursor() as cursor:
                    cursor.execute("CREATE DATABASE IF NOT EXISTS `%s` CHARACTER SET utf8mb4 COLLATE utf8mb4_bin" % database)
                connection.commit()
            finally:
                connection.close()
            return self.pymysql.connect(**self._mysql_kwargs(True))

    def connect(self):
        return self._connect_mysql() if self.backend == "mysql" else self._connect_sqlite()

    def connect_readonly(self):
        if self.backend == "mysql":
            # MySQL permissions are controlled by the configured account. The
            # migration inspector performs SELECT statements only.
            return self._connect_mysql()
        uri = Path(self.settings.sqlite_path).expanduser().resolve().as_uri() + "?mode=ro"
        connection = sqlite3.connect(
            uri,
            uri=True,
            timeout=30,
            check_same_thread=False,
        )
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA busy_timeout=30000")
        return connection

    def sql(self, statement: str) -> str:
        return statement.replace("?", "%s") if self.backend == "mysql" else statement

    def execute(self, connection, statement: str, params: Sequence[Any] = ()):
        cursor = connection.cursor()
        cursor.execute(self.sql(statement), tuple(params))
        return cursor

    def executemany(self, connection, statement: str, rows):
        cursor = connection.cursor()
        cursor.executemany(self.sql(statement), rows)
        return cursor

    def fetchone(self, connection, statement: str, params: Sequence[Any] = ()) -> Optional[Dict[str, Any]]:
        cursor = self.execute(connection, statement, params)
        try:
            row = cursor.fetchone()
            return dict(row) if row is not None else None
        finally:
            cursor.close()

    def fetchall(self, connection, statement: str, params: Sequence[Any] = ()):
        cursor = self.execute(connection, statement, params)
        try:
            return [dict(row) for row in cursor.fetchall()]
        finally:
            cursor.close()

    @contextlib.contextmanager
    def transaction(self, immediate: bool = False) -> Iterator[Any]:
        connection = self.connect()
        try:
            if self.backend == "sqlite" and immediate:
                connection.execute("BEGIN IMMEDIATE")
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def table_exists(self, connection, table_name: str) -> bool:
        if self.backend == "mysql":
            row = self.fetchone(
                connection,
                "SELECT TABLE_NAME AS name FROM information_schema.TABLES "
                "WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME=?",
                (table_name,),
            )
        else:
            row = self.fetchone(
                connection,
                "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
                (table_name,),
            )
        return row is not None

    def list_tables(self, connection):
        if self.backend == "mysql":
            rows = self.fetchall(
                connection,
                "SELECT TABLE_NAME AS name FROM information_schema.TABLES "
                "WHERE TABLE_SCHEMA=DATABASE() ORDER BY TABLE_NAME",
            )
        else:
            rows = self.fetchall(
                connection,
                "SELECT name FROM sqlite_master WHERE type='table' "
                "AND name NOT LIKE 'sqlite_%' ORDER BY name",
            )
        return [str(row["name"]) for row in rows]

    def test_connection(self) -> None:
        connection = self.connect()
        try:
            self.fetchone(connection, "SELECT 1 AS ok")
        finally:
            connection.close()
