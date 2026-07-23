from __future__ import annotations

from typing import List

from .. import SCHEMA_VERSION


SQLITE_SCHEMA = [
    """CREATE TABLE IF NOT EXISTS meta (
        key TEXT PRIMARY KEY,
        value TEXT NOT NULL
    )""",
    """CREATE TABLE IF NOT EXISTS sources (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        label TEXT NOT NULL,
        uri TEXT NOT NULL,
        uri_hash TEXT NOT NULL UNIQUE,
        enabled INTEGER NOT NULL DEFAULT 0,
        available INTEGER NOT NULL DEFAULT 1,
        last_scan_at TEXT,
        last_scan_status TEXT,
        last_error TEXT,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    )""",
    """CREATE TABLE IF NOT EXISTS folders (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        source_id INTEGER NOT NULL,
        parent_uri TEXT NOT NULL,
        uri TEXT NOT NULL,
        uri_hash TEXT NOT NULL UNIQUE,
        name TEXT NOT NULL,
        discovered_at TEXT NOT NULL,
        last_seen_at TEXT NOT NULL,
        missing_since TEXT,
        latest_taken_at TEXT,
        latest_discovered_at TEXT,
        representative_picture_id INTEGER,
        random_key REAL NOT NULL,
        is_missing INTEGER NOT NULL DEFAULT 0,
        FOREIGN KEY(source_id) REFERENCES sources(id) ON DELETE CASCADE
    )""",
    """CREATE TABLE IF NOT EXISTS pictures (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        source_id INTEGER NOT NULL,
        folder_id INTEGER NOT NULL,
        uri TEXT NOT NULL,
        uri_hash TEXT NOT NULL UNIQUE,
        filename TEXT NOT NULL,
        extension TEXT NOT NULL,
        file_size INTEGER NOT NULL,
        file_mtime REAL NOT NULL,
        discovered_at TEXT NOT NULL,
        last_seen_at TEXT NOT NULL,
        missing_since TEXT,
        taken_at TEXT,
        taken_source TEXT,
        taken_year INTEGER,
        taken_month INTEGER,
        taken_day INTEGER,
        width INTEGER,
        height INTEGER,
        orientation INTEGER,
        mime_type TEXT,
        camera_make TEXT,
        camera_model TEXT,
        rating INTEGER,
        gps_latitude REAL,
        gps_longitude REAL,
        city TEXT,
        state TEXT,
        country TEXT,
        sublocation TEXT,
        caption TEXT,
        metadata_hash TEXT,
        thumb_uri TEXT,
        random_key REAL NOT NULL,
        favorite INTEGER NOT NULL DEFAULT 0,
        is_missing INTEGER NOT NULL DEFAULT 0,
        FOREIGN KEY(source_id) REFERENCES sources(id) ON DELETE CASCADE,
        FOREIGN KEY(folder_id) REFERENCES folders(id) ON DELETE CASCADE
    )""",
    """CREATE TABLE IF NOT EXISTS tags (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        normalized_name TEXT NOT NULL UNIQUE
    )""",
    """CREATE TABLE IF NOT EXISTS picture_tags (
        picture_id INTEGER NOT NULL,
        tag_id INTEGER NOT NULL,
        PRIMARY KEY(picture_id, tag_id),
        FOREIGN KEY(picture_id) REFERENCES pictures(id) ON DELETE CASCADE,
        FOREIGN KEY(tag_id) REFERENCES tags(id) ON DELETE CASCADE
    )""",
    """CREATE TABLE IF NOT EXISTS scan_runs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        source_id INTEGER,
        started_at TEXT NOT NULL,
        finished_at TEXT,
        status TEXT NOT NULL,
        pictures_seen INTEGER NOT NULL DEFAULT 0,
        pictures_added INTEGER NOT NULL DEFAULT 0,
        pictures_updated INTEGER NOT NULL DEFAULT 0,
        pictures_unchanged INTEGER NOT NULL DEFAULT 0,
        errors INTEGER NOT NULL DEFAULT 0,
        message TEXT,
        FOREIGN KEY(source_id) REFERENCES sources(id) ON DELETE SET NULL
    )""",
    """CREATE TABLE IF NOT EXISTS locks (
        name TEXT PRIMARY KEY,
        owner TEXT NOT NULL,
        acquired_at TEXT NOT NULL,
        expires_at TEXT NOT NULL
    )""",
    "CREATE INDEX IF NOT EXISTS idx_pictures_taken ON pictures(is_missing, taken_at DESC)",
    "CREATE INDEX IF NOT EXISTS idx_pictures_added ON pictures(is_missing, discovered_at DESC)",
    "CREATE INDEX IF NOT EXISTS idx_pictures_random ON pictures(is_missing, random_key)",
    "CREATE INDEX IF NOT EXISTS idx_pictures_date_parts ON pictures(is_missing, taken_month, taken_day, taken_year)",
    "CREATE INDEX IF NOT EXISTS idx_pictures_folder ON pictures(folder_id, is_missing)",
    "CREATE INDEX IF NOT EXISTS idx_pictures_camera ON pictures(is_missing, camera_make, camera_model)",
    "CREATE INDEX IF NOT EXISTS idx_pictures_favorite ON pictures(is_missing, favorite)",
    "CREATE INDEX IF NOT EXISTS idx_folders_parent ON folders(source_id, parent_uri, is_missing)",
    "CREATE INDEX IF NOT EXISTS idx_folders_recent ON folders(is_missing, latest_discovered_at DESC)",
    "CREATE INDEX IF NOT EXISTS idx_folders_random ON folders(is_missing, random_key)",
]

MYSQL_SCHEMA = [
    """CREATE TABLE IF NOT EXISTS meta (
        `key` VARCHAR(191) PRIMARY KEY,
        `value` TEXT NOT NULL
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin""",
    """CREATE TABLE IF NOT EXISTS sources (
        id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
        label VARCHAR(512) NOT NULL,
        uri LONGTEXT NOT NULL,
        uri_hash CHAR(64) NOT NULL UNIQUE,
        enabled TINYINT(1) NOT NULL DEFAULT 0,
        available TINYINT(1) NOT NULL DEFAULT 1,
        last_scan_at DATETIME(6) NULL,
        last_scan_status VARCHAR(32) NULL,
        last_error TEXT NULL,
        created_at DATETIME(6) NOT NULL,
        updated_at DATETIME(6) NOT NULL
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin""",
    """CREATE TABLE IF NOT EXISTS folders (
        id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
        source_id BIGINT UNSIGNED NOT NULL,
        parent_uri LONGTEXT NOT NULL,
        uri LONGTEXT NOT NULL,
        uri_hash CHAR(64) NOT NULL UNIQUE,
        name VARCHAR(1024) NOT NULL,
        discovered_at DATETIME(6) NOT NULL,
        last_seen_at DATETIME(6) NOT NULL,
        missing_since DATETIME(6) NULL,
        latest_taken_at DATETIME(6) NULL,
        latest_discovered_at DATETIME(6) NULL,
        representative_picture_id BIGINT UNSIGNED NULL,
        random_key DOUBLE NOT NULL,
        is_missing TINYINT(1) NOT NULL DEFAULT 0,
        CONSTRAINT fk_folders_source FOREIGN KEY(source_id) REFERENCES sources(id) ON DELETE CASCADE
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin""",
    """CREATE TABLE IF NOT EXISTS pictures (
        id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
        source_id BIGINT UNSIGNED NOT NULL,
        folder_id BIGINT UNSIGNED NOT NULL,
        uri LONGTEXT NOT NULL,
        uri_hash CHAR(64) NOT NULL UNIQUE,
        filename VARCHAR(1024) NOT NULL,
        extension VARCHAR(32) NOT NULL,
        file_size BIGINT NOT NULL,
        file_mtime DOUBLE NOT NULL,
        discovered_at DATETIME(6) NOT NULL,
        last_seen_at DATETIME(6) NOT NULL,
        missing_since DATETIME(6) NULL,
        taken_at DATETIME(6) NULL,
        taken_source VARCHAR(64) NULL,
        taken_year SMALLINT NULL,
        taken_month TINYINT NULL,
        taken_day TINYINT NULL,
        width INT NULL,
        height INT NULL,
        orientation TINYINT NULL,
        mime_type VARCHAR(128) NULL,
        camera_make VARCHAR(255) NULL,
        camera_model VARCHAR(255) NULL,
        rating TINYINT NULL,
        gps_latitude DOUBLE NULL,
        gps_longitude DOUBLE NULL,
        city VARCHAR(255) NULL,
        state VARCHAR(255) NULL,
        country VARCHAR(255) NULL,
        sublocation VARCHAR(255) NULL,
        caption TEXT NULL,
        metadata_hash CHAR(64) NULL,
        thumb_uri LONGTEXT NULL,
        random_key DOUBLE NOT NULL,
        favorite TINYINT(1) NOT NULL DEFAULT 0,
        is_missing TINYINT(1) NOT NULL DEFAULT 0,
        CONSTRAINT fk_pictures_source FOREIGN KEY(source_id) REFERENCES sources(id) ON DELETE CASCADE,
        CONSTRAINT fk_pictures_folder FOREIGN KEY(folder_id) REFERENCES folders(id) ON DELETE CASCADE,
        INDEX idx_pictures_taken (is_missing, taken_at),
        INDEX idx_pictures_added (is_missing, discovered_at),
        INDEX idx_pictures_random (is_missing, random_key),
        INDEX idx_pictures_date_parts (is_missing, taken_month, taken_day, taken_year),
        INDEX idx_pictures_folder (folder_id, is_missing),
        INDEX idx_pictures_camera (is_missing, camera_make, camera_model),
        INDEX idx_pictures_favorite (is_missing, favorite)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin""",
    """CREATE TABLE IF NOT EXISTS tags (
        id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
        name VARCHAR(191) NOT NULL,
        normalized_name VARCHAR(191) NOT NULL UNIQUE
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin""",
    """CREATE TABLE IF NOT EXISTS picture_tags (
        picture_id BIGINT UNSIGNED NOT NULL,
        tag_id BIGINT UNSIGNED NOT NULL,
        PRIMARY KEY(picture_id, tag_id),
        CONSTRAINT fk_picture_tags_picture FOREIGN KEY(picture_id) REFERENCES pictures(id) ON DELETE CASCADE,
        CONSTRAINT fk_picture_tags_tag FOREIGN KEY(tag_id) REFERENCES tags(id) ON DELETE CASCADE
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin""",
    """CREATE TABLE IF NOT EXISTS scan_runs (
        id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
        source_id BIGINT UNSIGNED NULL,
        started_at DATETIME(6) NOT NULL,
        finished_at DATETIME(6) NULL,
        status VARCHAR(32) NOT NULL,
        pictures_seen INT NOT NULL DEFAULT 0,
        pictures_added INT NOT NULL DEFAULT 0,
        pictures_updated INT NOT NULL DEFAULT 0,
        pictures_unchanged INT NOT NULL DEFAULT 0,
        errors INT NOT NULL DEFAULT 0,
        message TEXT NULL,
        CONSTRAINT fk_scan_runs_source FOREIGN KEY(source_id) REFERENCES sources(id) ON DELETE SET NULL
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin""",
    """CREATE TABLE IF NOT EXISTS locks (
        name VARCHAR(191) PRIMARY KEY,
        owner VARCHAR(191) NOT NULL,
        acquired_at DATETIME(6) NOT NULL,
        expires_at DATETIME(6) NOT NULL
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin""",
    "CREATE INDEX idx_folders_parent ON folders(source_id, is_missing)",
    "CREATE INDEX idx_folders_recent ON folders(is_missing, latest_discovered_at)",
    "CREATE INDEX idx_folders_random ON folders(is_missing, random_key)",
]


def create_schema(engine, connection) -> None:
    """Create the current schema objects without deciding migration policy.

    Version checks, backups and migration history belong to MigrationRunner.
    Keeping this function deterministic also makes fresh-database creation and
    schema inspection straightforward.
    """
    statements: List[str] = MYSQL_SCHEMA if engine.backend == "mysql" else SQLITE_SCHEMA
    for statement in statements:
        try:
            cursor = engine.execute(connection, statement)
            cursor.close()
        except Exception as exc:
            # MariaDB raises an error when CREATE INDEX is repeated. Existing tables are valid.
            message = str(exc).lower()
            if engine.backend == "mysql" and ("duplicate key name" in message or "already exists" in message):
                continue
            raise


def initialise_schema(engine, connection) -> None:
    """Compatibility wrapper for callers that still initialise a fresh schema.

    Production startup uses MigrationRunner so existing databases are backed up
    and version-checked before any structural change.
    """
    create_schema(engine, connection)
    row = engine.fetchone(
        connection,
        "SELECT value FROM meta WHERE `key`=?" if engine.backend == "mysql" else "SELECT value FROM meta WHERE key=?",
        ("schema_version",),
    )
    if row is None:
        engine.execute(
            connection,
            "INSERT INTO meta (`key`, value) VALUES (?, ?)" if engine.backend == "mysql" else "INSERT INTO meta (key, value) VALUES (?, ?)",
            ("schema_version", str(SCHEMA_VERSION)),
        ).close()
    elif int(row["value"]) != SCHEMA_VERSION:
        raise RuntimeError("Use MigrationRunner for an existing database schema")
