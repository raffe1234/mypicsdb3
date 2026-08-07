from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from mypicsdb3.config import Settings
from mypicsdb3.db.engine import DatabaseEngine
from mypicsdb3.query_model import parse_picture_query
from mypicsdb3.screensaver import (
    SCREEN_SOURCE_MANUAL,
    SCREEN_SOURCE_SMART,
    ScreensaverReadOnlyProvider,
    ScreensaverSourceError,
    normalize_item_limit,
    normalize_slide_seconds,
)
from mypicsdb3.utils import utc_now


def _engine(tmp_path: Path) -> DatabaseEngine:
    settings = Settings(profile_path=str(tmp_path))
    engine = DatabaseEngine(settings)
    connection = engine.connect()
    try:
        connection.executescript(
            """
            CREATE TABLE pictures (
                id INTEGER PRIMARY KEY,
                uri TEXT NOT NULL,
                filename TEXT NOT NULL,
                media_type TEXT NOT NULL,
                is_missing INTEGER NOT NULL DEFAULT 0,
                rating INTEGER,
                source_id INTEGER NOT NULL DEFAULT 1,
                folder_id INTEGER NOT NULL DEFAULT 1,
                random_key REAL NOT NULL DEFAULT 0.0,
                favorite INTEGER NOT NULL DEFAULT 0,
                taken_at TEXT,
                discovered_at TEXT
            );
            CREATE TABLE collections (
                id INTEGER PRIMARY KEY,
                name TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE collection_items (
                collection_id INTEGER NOT NULL,
                picture_id INTEGER NOT NULL,
                position INTEGER NOT NULL,
                added_at TEXT NOT NULL,
                PRIMARY KEY (collection_id, picture_id)
            );
            CREATE TABLE saved_searches (
                id INTEGER PRIMARY KEY,
                name TEXT NOT NULL,
                query_version INTEGER NOT NULL,
                query_json TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE picture_tags (picture_id INTEGER, tag_id INTEGER);
            CREATE TABLE tags (id INTEGER PRIMARY KEY, normalized_name TEXT);
            CREATE TABLE picture_search_documents (picture_id INTEGER, document TEXT);
            """
        )
        connection.commit()
    finally:
        connection.close()
    return engine


def _insert_picture(connection, picture_id, uri, media_type="picture", random_key=0.0, rating=None):
    connection.execute(
        "INSERT INTO pictures "
        "(id, uri, filename, media_type, is_missing, rating, random_key, taken_at, discovered_at) "
        "VALUES (?, ?, ?, ?, 0, ?, ?, ?, ?)",
        (
            picture_id,
            uri,
            uri.rsplit("/", 1)[-1],
            media_type,
            rating,
            random_key,
            "2020-01-01 12:00:00",
            "2020-01-02 12:00:00",
        ),
    )


def test_screensaver_lists_manual_and_smart_sources_without_writes(tmp_path: Path):
    engine = _engine(tmp_path)
    now = utc_now()
    query = parse_picture_query({"version": 1, "root": {"type": "group", "match": "all", "children": []}})
    from mypicsdb3.query_model import canonical_picture_query_json

    connection = engine.connect()
    try:
        connection.execute(
            "INSERT INTO collections VALUES (1, 'Trip', ?, ?)", (now, now)
        )
        connection.execute(
            "INSERT INTO saved_searches VALUES (2, 'Five stars', 1, ?, ?, ?)",
            (canonical_picture_query_json(query), now, now),
        )
        connection.commit()
    finally:
        connection.close()

    provider = ScreensaverReadOnlyProvider(engine.settings, engine=engine)
    sources = provider.list_sources()
    assert [(item.source_type, item.source_id, item.name) for item in sources] == [
        (SCREEN_SOURCE_MANUAL, 1, "Trip"),
        (SCREEN_SOURCE_SMART, 2, "Five stars"),
    ]


def test_manual_screensaver_filters_videos_missing_and_min_rating(tmp_path: Path):
    settings = Settings(profile_path=str(tmp_path), minimum_rating_policy="3")
    engine = DatabaseEngine(settings)
    _engine(tmp_path)
    engine = DatabaseEngine(settings)
    connection = engine.connect()
    try:
        now = utc_now()
        connection.execute("INSERT INTO collections VALUES (1, 'Trip', ?, ?)", (now, now))
        _insert_picture(connection, 1, "smb://photos/one.jpg", rating=4, random_key=0.1)
        _insert_picture(connection, 2, "smb://photos/low.jpg", rating=2, random_key=0.2)
        _insert_picture(connection, 3, "smb://photos/movie.mp4", media_type="video", random_key=0.3)
        _insert_picture(connection, 4, "smb://photos/missing.jpg", rating=5, random_key=0.4)
        connection.execute("UPDATE pictures SET is_missing=1 WHERE id=4")
        for position, picture_id in enumerate((1, 2, 3, 4)):
            connection.execute(
                "INSERT INTO collection_items VALUES (1, ?, ?, ?)",
                (picture_id, position, now),
            )
        connection.commit()
    finally:
        connection.close()

    provider = ScreensaverReadOnlyProvider(settings, engine=engine)
    rows = provider.pictures(SCREEN_SOURCE_MANUAL, 1, randomize=False)
    assert [row.uri for row in rows] == ["smb://photos/one.jpg"]


def test_smart_screensaver_uses_saved_query_and_picture_only(tmp_path: Path):
    engine = _engine(tmp_path)
    now = utc_now()
    from mypicsdb3.query_model import canonical_picture_query_json

    query = parse_picture_query(
        {
            "version": 1,
            "root": {
                "type": "group",
                "match": "all",
                "children": [
                    {
                        "type": "rule",
                        "field": "favorite",
                        "operator": "eq",
                        "value": True,
                    }
                ],
            },
            "sort": [{"field": "taken_at", "direction": "asc"}],
        }
    )
    connection = engine.connect()
    try:
        connection.execute(
            "INSERT INTO saved_searches VALUES (7, 'Favorites', 1, ?, ?, ?)",
            (canonical_picture_query_json(query), now, now),
        )
        _insert_picture(connection, 1, "smb://photos/a.jpg", random_key=0.1)
        _insert_picture(connection, 2, "smb://photos/b.jpg", random_key=0.2)
        _insert_picture(connection, 3, "smb://photos/c.mp4", media_type="video", random_key=0.3)
        connection.execute("UPDATE pictures SET favorite=1 WHERE id IN (1,3)")
        connection.commit()
    finally:
        connection.close()

    provider = ScreensaverReadOnlyProvider(engine.settings, engine=engine)
    rows = provider.pictures(SCREEN_SOURCE_SMART, 7, randomize=False)
    assert [row.uri for row in rows] == ["smb://photos/a.jpg"]


def test_random_screensaver_query_is_bounded_and_seeded(tmp_path: Path):
    engine = _engine(tmp_path)
    now = utc_now()
    connection = engine.connect()
    try:
        connection.execute("INSERT INTO collections VALUES (1, 'Many', ?, ?)", (now, now))
        for picture_id in range(1, 31):
            _insert_picture(
                connection,
                picture_id,
                "smb://photos/%02d.jpg" % picture_id,
                random_key=picture_id / 31.0,
            )
            connection.execute(
                "INSERT INTO collection_items VALUES (1, ?, ?, ?)",
                (picture_id, picture_id - 1, now),
            )
        connection.commit()
    finally:
        connection.close()

    provider = ScreensaverReadOnlyProvider(engine.settings, engine=engine)
    first = provider.pictures(SCREEN_SOURCE_MANUAL, 1, limit=7, randomize=True, seed=0.41)
    second = provider.pictures(SCREEN_SOURCE_MANUAL, 1, limit=7, randomize=True, seed=0.41)
    assert len(first) == 7
    assert first == second


def test_deleted_source_and_limits_fail_safely(tmp_path: Path):
    engine = _engine(tmp_path)
    provider = ScreensaverReadOnlyProvider(engine.settings, engine=engine)
    with pytest.raises(ScreensaverSourceError, match="no longer exists"):
        provider.pictures(SCREEN_SOURCE_MANUAL, 99)
    assert normalize_item_limit(999999) == 1000
    assert normalize_item_limit("bad") == 250
    assert normalize_slide_seconds(1) == 2
    assert normalize_slide_seconds("bad") == 8

def test_screensaver_ui_uses_window_coordinate_space_for_centering():
    source = (
        Path(__file__).resolve().parents[1]
        / "screensaver.mypicsdb3"
        / "default.py"
    ).read_text(encoding="utf-8")
    assert "window.getWidth()" in source
    assert "window.getHeight()" in source
    assert source.count("width, height = _window_canvas_size(window)") == 2
    assert "centered=true" in source
