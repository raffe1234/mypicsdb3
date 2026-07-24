from __future__ import annotations

import os

import pytest

from mypicsdb3 import VERSION
from mypicsdb3.config import Settings
from mypicsdb3.db.catalog import Catalog
from mypicsdb3.db.engine import DatabaseEngine
from mypicsdb3.db.schema import create_schema
from mypicsdb3.utils import utc_now


pytestmark = pytest.mark.skipif(
    not os.environ.get("MYPICSDB3_TEST_MYSQL"),
    reason="MySQL integration test is opt-in",
)


def mysql_settings(tmp_path) -> Settings:
    return Settings(
        profile_path=str(tmp_path),
        database_backend="mysql",
        mysql_host=os.environ.get("MYPICSDB3_MYSQL_HOST", "127.0.0.1"),
        mysql_port=int(os.environ.get("MYPICSDB3_MYSQL_PORT", "3306")),
        mysql_database=os.environ.get("MYPICSDB3_MYSQL_DATABASE", "mypicsdb3_test"),
        mysql_username=os.environ.get("MYPICSDB3_MYSQL_USERNAME", "mypicsdb3"),
        mysql_password=os.environ.get("MYPICSDB3_MYSQL_PASSWORD", "mypicsdb3"),
        mysql_auto_create=True,
    )


def reset_database(engine: DatabaseEngine) -> None:
    with engine.transaction() as connection:
        engine.execute(connection, "SET FOREIGN_KEY_CHECKS=0").close()
        try:
            for table_name in engine.list_tables(connection):
                engine.execute(
                    connection,
                    "DROP TABLE IF EXISTS `%s`" % table_name.replace("`", "``"),
                ).close()
        finally:
            engine.execute(connection, "SET FOREIGN_KEY_CHECKS=1").close()


@pytest.fixture(autouse=True)
def clean_mysql_database(tmp_path):
    engine = DatabaseEngine(mysql_settings(tmp_path))
    reset_database(engine)
    yield
    reset_database(engine)


def test_mysql_or_mariadb_schema_and_source_roundtrip(tmp_path) -> None:
    catalog = Catalog(DatabaseEngine(mysql_settings(tmp_path)))
    catalog.initialize()
    sources = catalog.sync_sources([{"label": "Test", "uri": "/tmp/photos"}])
    assert sources[0].label == "Test"
    catalog.test_connection()


def test_existing_mysql_schema_one_bootstraps_history_without_data_loss(tmp_path) -> None:
    engine = DatabaseEngine(mysql_settings(tmp_path))
    with engine.transaction() as connection:
        create_schema(engine, connection)
        engine.execute(
            connection,
            "DROP INDEX idx_pictures_date_browse ON pictures",
        ).close()
        engine.execute(
            connection,
            "INSERT INTO meta (`key`, value) VALUES (?, ?)",
            ("schema_version", "1"),
        ).close()
        engine.execute(
            connection,
            "INSERT INTO sources "
            "(label, uri, uri_hash, enabled, available, created_at, updated_at) "
            "VALUES (?, ?, ?, 1, 1, ?, ?)",
            (
                "Existing photos",
                "/srv/photos/",
                "existing-schema-one-source",
                "2026-07-23 12:00:00.000000",
                "2026-07-23 12:00:00.000000",
            ),
        ).close()
        assert not engine.table_exists(connection, "schema_migrations")

    catalog = Catalog(engine)
    first = catalog.initialize()
    second = catalog.initialize()

    assert first.bootstrapped_history is True
    assert first.current_version == 2
    assert first.applied_versions == (2,)
    assert second.bootstrapped_history is False
    assert second.applied_versions == ()
    with engine.transaction() as connection:
        source = engine.fetchone(
            connection,
            "SELECT label, uri FROM sources WHERE uri_hash=?",
            ("existing-schema-one-source",),
        )
        history = engine.fetchall(
            connection,
            "SELECT version, addon_version FROM schema_migrations ORDER BY version",
        )
        count = engine.fetchone(
            connection,
            "SELECT COUNT(*) AS total FROM schema_migrations",
        )
        index = engine.fetchone(
            connection,
            "SELECT INDEX_NAME AS name FROM information_schema.STATISTICS "
            "WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='pictures' "
            "AND INDEX_NAME='idx_pictures_date_browse'",
        )

    assert source == {"label": "Existing photos", "uri": "/srv/photos/"}
    assert [row["version"] for row in history] == [1, 2]
    assert {row["addon_version"] for row in history} == {VERSION}
    assert count["total"] == 2
    assert index is not None


def test_mysql_rating_policy_matches_group_counts_and_picture_results(tmp_path) -> None:
    catalog = Catalog(DatabaseEngine(mysql_settings(tmp_path)))
    catalog.initialize()
    source = catalog.sync_sources([{"label": "Photos", "uri": "/srv/photos"}])[0]
    now = utc_now()
    with catalog.engine.transaction() as connection:
        folder_id = catalog.upsert_folder(
            connection,
            source.id,
            "/srv/photos/",
            "",
            "Photos",
            now,
        )
        for index, rating in enumerate((None, 0, 3), start=1):
            catalog.insert_picture(
                connection,
                {
                    "source_id": source.id,
                    "folder_id": folder_id,
                    "uri": "/srv/photos/image-%d.jpg" % index,
                    "filename": "image-%d.jpg" % index,
                    "extension": "jpg",
                    "file_size": 100,
                    "file_mtime": float(index),
                    "discovered_at": "2026-07-24 0%d:00:00" % index,
                    "last_seen_at": now,
                    "taken_at": "2020-07-17 0%d:00:00" % index,
                    "taken_source": "XMP",
                    "rating": rating,
                    "metadata_hash": "rating-%d" % index,
                    "thumb_uri": "/srv/photos/image-%d.jpg" % index,
                },
                ["Shared"],
            )
        catalog.update_folder_summaries(connection, source.id)

    catalog.set_rating_policy("rated_and_unrated")
    assert {row["rating"] for row in catalog.recent_added(10)} == {None, 3}

    catalog.set_rating_policy("3")
    assert [row["rating"] for row in catalog.recent_added(10)] == [3]
    assert catalog.years()[0]["picture_count"] == 1
    assert catalog.recent_folders(10)[0]["picture_count"] == 1
    assert catalog.tags()[0]["picture_count"] == 1


def test_mysql_query_model_matches_page_count_and_minimum_rating_policy(tmp_path) -> None:
    catalog = Catalog(DatabaseEngine(mysql_settings(tmp_path)))
    catalog.initialize()
    source = catalog.sync_sources([{"label": "Photos", "uri": "/srv/query-model"}])[0]
    now = utc_now()
    with catalog.engine.transaction() as connection:
        folder_id = catalog.upsert_folder(
            connection,
            source.id,
            "/srv/query-model/",
            "",
            "Query model",
            now,
        )
        for index, (name, rating, favorite, keyword) in enumerate(
            (
                ("selected.jpg", 5, 1, "Summer"),
                ("low.jpg", 2, 1, "Summer"),
                ("other.jpg", 5, 0, "Winter"),
            ),
            start=1,
        ):
            picture_id = catalog.insert_picture(
                connection,
                {
                    "source_id": source.id,
                    "folder_id": folder_id,
                    "uri": "/srv/query-model/" + name,
                    "filename": name,
                    "extension": "jpg",
                    "file_size": 100,
                    "file_mtime": float(index),
                    "discovered_at": "2026-07-24 0%d:00:00" % index,
                    "last_seen_at": now,
                    "taken_at": "2020-07-%02d 10:00:00" % (16 + index),
                    "taken_source": "EXIF",
                    "camera_make": "Canon",
                    "camera_model": "EOS R6",
                    "rating": rating,
                    "metadata_hash": "query-model-%d" % index,
                    "thumb_uri": "/srv/query-model/" + name,
                },
                [keyword],
            )
            if favorite:
                catalog.engine.execute(
                    connection,
                    "UPDATE pictures SET favorite=1 WHERE id=?",
                    (picture_id,),
                ).close()

    query = {
        "version": 1,
        "root": {
            "type": "group",
            "match": "all",
            "negated": False,
            "children": [
                {"type": "rule", "field": "favorite", "operator": "eq", "value": True},
                {"type": "rule", "field": "keyword", "operator": "eq", "value": "summer"},
                {
                    "type": "rule",
                    "field": "taken_date",
                    "operator": "between",
                    "from": "2020-07-01",
                    "to": "2020-07-31",
                },
                {
                    "type": "rule",
                    "field": "camera",
                    "operator": "eq",
                    "value": {"make": "Canon", "model": "EOS R6"},
                },
            ],
        },
        "sort": [{"field": "filename", "direction": "asc"}],
        "scope": {
            "source_ids": [source.id],
            "include_missing": False,
            "include_excluded": False,
        },
        "default_policy": {"apply_min_rating": True},
    }

    catalog.set_rating_policy("3")
    assert [row["filename"] for row in catalog.query_pictures(query, 10)] == ["selected.jpg"]
    assert catalog.count_query_pictures(query) == 1

    query["default_policy"] = {"apply_min_rating": False}
    assert [row["filename"] for row in catalog.query_pictures(query, 10)] == [
        "low.jpg",
        "selected.jpg",
    ]
    assert catalog.count_query_pictures(query) == 2
