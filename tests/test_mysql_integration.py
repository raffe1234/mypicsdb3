from __future__ import annotations

import os

import pytest

from mypicsdb3 import VERSION
from mypicsdb3.config import Settings
from mypicsdb3.db.catalog import Catalog
from mypicsdb3.db.engine import DatabaseEngine
from mypicsdb3.db.schema import create_schema
from mypicsdb3.search import build_global_search_request
from mypicsdb3.metadata_mapping import MetadataMappingRule
from mypicsdb3.source_scan_policy import SourceScanPolicy
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
    catalog.set_source_scan_policy(
        sources[0].id,
        SourceScanPolicy(
            recursive=False,
            include_videos=True,
            picture_extensions=("jpg", "nef"),
            video_extensions=("mp4",),
            exclude_fragments=("#recycle",),
            exclude_hidden=True,
        ),
    )
    assert catalog.get_source_scan_policy(sources[0].id) == SourceScanPolicy(
        recursive=False,
        include_videos=True,
        picture_extensions=("jpg", "nef"),
        video_extensions=("mp4",),
        exclude_fragments=("#recycle",),
        exclude_hidden=True,
    )
    catalog.set_metadata_mapping_rule(
        MetadataMappingRule("xmp", "CountryName", "country", 7)
    )
    catalog.set_metadata_mapping_rule(
        MetadataMappingRule("iptc", "caption/abstract", None, 9)
    )
    overrides = catalog.list_metadata_mapping_overrides()
    assert [(r.source_type, r.source_tag, r.target_field, r.priority) for r in overrides] == [
        ("iptc", "caption/abstract", None, 9),
        ("xmp", "CountryName", "country", 7),
    ]
    stale_scan_id = catalog.begin_scan_run(sources[0].id)
    assert catalog.recover_stale_local_lock("catalogue-scan", "host:1234:test") is None
    assert catalog.interrupt_running_scan_runs("interrupted test") == 1
    latest = catalog.latest_scan()
    assert latest["id"] == stale_scan_id
    assert latest["status"] == "interrupted"
    assert latest["finished_at"]
    catalog.test_connection()


def test_existing_mysql_schema_one_bootstraps_history_without_data_loss(tmp_path) -> None:
    engine = DatabaseEngine(mysql_settings(tmp_path))
    with engine.transaction() as connection:
        create_schema(engine, connection)
        engine.execute(connection, "DROP TABLE metadata_mapping_rules").close()
        engine.execute(connection, "DROP TABLE source_scan_policies").close()
        engine.execute(connection, "DROP TABLE collection_music_playlists").close()
        engine.execute(connection, "DROP TABLE collection_items").close()
        engine.execute(connection, "DROP TABLE collections").close()
        engine.execute(connection, "DROP TABLE saved_searches").close()
        engine.execute(
            connection,
            "DROP TABLE picture_search_documents",
        ).close()
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
    assert first.current_version == 9
    assert first.applied_versions == (2, 3, 4, 5, 6, 7, 8, 9)
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
        search_table = engine.fetchone(
            connection,
            "SELECT TABLE_NAME AS name FROM information_schema.TABLES "
            "WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='picture_search_documents'",
        )

    assert source == {"label": "Existing photos", "uri": "/srv/photos/"}
    assert [row["version"] for row in history] == [1, 2, 3, 4, 5, 6, 7, 8, 9]
    assert {row["addon_version"] for row in history} == {VERSION}
    assert count["total"] == 9
    assert index is not None
    assert search_table is not None


def test_existing_mysql_schema_eight_adds_metadata_mapping_schema(tmp_path) -> None:
    engine = DatabaseEngine(mysql_settings(tmp_path))
    catalog = Catalog(engine)
    catalog.initialize()
    source = catalog.sync_sources([{"label": "Photos", "uri": "/srv/schema-eight"}])[0]

    with engine.transaction() as connection:
        engine.execute(connection, "DROP TABLE metadata_mapping_rules").close()
        engine.execute(connection, "ALTER TABLE pictures DROP COLUMN metadata_index_hash").close()
        engine.execute(connection, "DELETE FROM schema_migrations WHERE version=?", (9,)).close()
        engine.execute(
            connection,
            "UPDATE meta SET value=? WHERE `key`=?",
            ("8", "schema_version"),
        ).close()

    result = Catalog(engine).initialize()

    assert result.previous_version == 8
    assert result.current_version == 9
    assert result.applied_versions == (9,)
    with engine.transaction() as connection:
        mapping_table = engine.fetchone(
            connection,
            "SELECT TABLE_NAME AS name FROM information_schema.TABLES "
            "WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='metadata_mapping_rules'",
        )
        index_column = engine.fetchone(
            connection,
            "SELECT COLUMN_NAME AS name FROM information_schema.COLUMNS "
            "WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='pictures' "
            "AND COLUMN_NAME='metadata_index_hash'",
        )
        preserved_source = engine.fetchone(
            connection,
            "SELECT label FROM sources WHERE id=?",
            (source.id,),
        )
    assert mapping_table is not None
    assert index_column is not None
    assert preserved_source == {"label": "Photos"}


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


def test_existing_mysql_schema_two_backfills_global_search_documents(tmp_path) -> None:
    engine = DatabaseEngine(mysql_settings(tmp_path))
    catalog = Catalog(engine)
    catalog.initialize()
    source = catalog.sync_sources([{"label": "Photos", "uri": "/srv/search-backfill"}])[0]
    now = utc_now()
    with engine.transaction() as connection:
        folder_id = catalog.upsert_folder(
            connection,
            source.id,
            "/srv/search-backfill/Åland/",
            "",
            "Åland",
            now,
        )
        picture_id = catalog.insert_picture(
            connection,
            {
                "source_id": source.id,
                "folder_id": folder_id,
                "uri": "/srv/search-backfill/Åland/Sommar.jpg",
                "filename": "Sommar.jpg",
                "extension": "jpg",
                "file_size": 100,
                "file_mtime": 1.0,
                "discovered_at": now,
                "last_seen_at": now,
                "taken_at": "2024-07-17 10:00:00",
                "taken_source": "EXIF",
                "caption": "Blå båt",
                "camera_make": "Fujifilm",
                "camera_model": "X-T5",
                "city": "Göteborg",
                "country": "Sverige",
                "rating": 5,
                "metadata_hash": "search-backfill",
                "thumb_uri": "/srv/search-backfill/Åland/Sommar.jpg",
            },
            ["Familj"],
        )
        engine.execute(connection, "DROP TABLE picture_search_documents").close()
        engine.execute(
            connection,
            "DELETE FROM schema_migrations WHERE version=?",
            (3,),
        ).close()
        engine.execute(
            connection,
            "UPDATE meta SET value=? WHERE `key`=?",
            ("2", "schema_version"),
        ).close()

    result = Catalog(engine).initialize()

    assert result.previous_version == 2
    assert result.current_version == 9
    assert result.applied_versions == (3,)
    with engine.transaction() as connection:
        row = engine.fetchone(
            connection,
            "SELECT document FROM picture_search_documents WHERE picture_id=?",
            (picture_id,),
        )
    assert row is not None
    assert " åland " in row["document"]
    assert " familj " in row["document"]
    assert " göteborg " in row["document"]


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
                    "width": 6000 if name != "other.jpg" else 2000,
                    "height": 4000 if name != "other.jpg" else 2000,
                    "orientation": 1,
                    "mime_type": "image/jpeg",
                    "camera_make": "Canon",
                    "camera_model": "EOS R6",
                    "rating": rating,
                    "city": "Stockholm" if name != "other.jpg" else "Paris",
                    "country": "Sweden" if name != "other.jpg" else "France",
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
                    "field": "text",
                    "operator": "contains_tokens",
                    "value": "summer",
                },
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

    facet_base = {
        "version": 1,
        "root": {"type": "group", "match": "all", "negated": False, "children": []},
        "sort": [],
        "scope": {"source_ids": [source.id], "include_missing": False, "include_excluded": False},
        "default_policy": {"apply_min_rating": False},
    }
    assert catalog.query_facet_counts(facet_base, "country") == [
        {"value": "Sweden", "picture_count": 2},
        {"value": "France", "picture_count": 1},
    ]
    assert catalog.query_facet_counts(facet_base, "camera_make") == [
        {"value": "Canon", "picture_count": 3}
    ]
    assert catalog.query_facet_counts(facet_base, "taken_year") == [
        {"value": 2020, "picture_count": 3}
    ]
    assert catalog.query_facet_counts(facet_base, "aspect") == [
        {"value": "landscape", "picture_count": 2},
        {"value": "square", "picture_count": 1},
    ]
    assert catalog.query_facet_counts(facet_base, "keyword") == [
        {"value": "Summer", "picture_count": 2},
        {"value": "Winter", "picture_count": 1},
    ]
    assert catalog.query_facet_counts(facet_base, "country", 1, 1) == [
        {"value": "France", "picture_count": 1}
    ]
    aspect_query = dict(facet_base)
    aspect_query["root"] = {
        "type": "group",
        "match": "all",
        "negated": False,
        "children": [{"type": "rule", "field": "aspect", "operator": "eq", "value": "square"}],
    }
    assert [row["filename"] for row in catalog.query_pictures(aspect_query, 10)] == ["other.jpg"]


def test_mysql_saved_search_roundtrip(tmp_path) -> None:
    catalog = Catalog(DatabaseEngine(mysql_settings(tmp_path)))
    catalog.initialize()
    query = build_global_search_request("åland sommar").query

    saved_id = catalog.create_saved_search("Sommarresor", query)
    saved = catalog.get_saved_search(saved_id)

    assert saved is not None
    assert saved.name == "Sommarresor"
    assert saved.query.root.children[0].value.text == "åland sommar"
    assert catalog.rename_saved_search(saved_id, "Östersjön") is True
    assert catalog.list_saved_searches()[0]["name"] == "Östersjön"
    assert catalog.delete_saved_search(saved_id) is True


def test_mysql_manual_collection_roundtrip_preserves_mixed_order(tmp_path) -> None:
    catalog = Catalog(DatabaseEngine(mysql_settings(tmp_path)))
    catalog.initialize()
    source = catalog.sync_sources(
        [{"label": "Collection media", "uri": "/srv/collection-media"}]
    )[0]
    now = utc_now()
    with catalog.engine.transaction() as connection:
        folder_id = catalog.upsert_folder(
            connection,
            source.id,
            "/srv/collection-media/",
            "",
            "Collection media",
            now,
        )
        media_ids = []
        for filename, media_type in (("clip.mp4", "video"), ("photo.jpg", "picture")):
            media_ids.append(
                catalog.insert_picture(
                    connection,
                    {
                        "source_id": source.id,
                        "folder_id": folder_id,
                        "uri": "/srv/collection-media/" + filename,
                        "filename": filename,
                        "extension": filename.rsplit(".", 1)[-1],
                        "media_type": media_type,
                        "file_size": 100,
                        "file_mtime": 1.0,
                        "discovered_at": now,
                        "last_seen_at": now,
                        "taken_at": "2026-08-06 12:00:00.000000",
                        "taken_source": "test",
                        "rating": None if media_type == "video" else 5,
                        "metadata_hash": filename,
                        "thumb_uri": "/srv/collection-media/" + filename,
                    },
                    [],
                )
            )

    collection_id = catalog.create_collection("Mixed picks")
    assert catalog.add_picture_to_collection(collection_id, media_ids[0]) is True
    assert catalog.add_picture_to_collection(collection_id, media_ids[1]) is True
    assert catalog.add_picture_to_collection(collection_id, media_ids[0]) is False
    assert [
        row["id"] for row in catalog.pictures_in_collection(collection_id, 10)
    ] == media_ids
    assert catalog.move_picture_in_collection(
        collection_id, media_ids[1], "top"
    ) is True
    assert [
        row["id"] for row in catalog.pictures_in_collection(collection_id, 10)
    ] == [media_ids[1], media_ids[0]]
    assert catalog.remove_picture_from_collection(collection_id, media_ids[1]) is True
    assert [
        (row["id"], row["collection_position"])
        for row in catalog.pictures_in_collection(collection_id, 10)
    ] == [(media_ids[0], 1)]
    assert catalog.list_collections()[0]["available_count"] == 1

    snapshot_query = {
        "version": 1,
        "root": {"type": "group", "match": "all", "negated": False, "children": []},
        "sort": [{"field": "filename", "direction": "desc"}],
        "scope": {
            "source_ids": [source.id],
            "include_missing": False,
            "include_excluded": False,
        },
        "default_policy": {"apply_min_rating": False},
    }
    snapshot_id, snapshot_count = catalog.create_collection_snapshot(
        "Frozen MySQL result", snapshot_query
    )
    assert snapshot_count == 2
    assert [
        row["filename"] for row in catalog.pictures_in_collection(snapshot_id, 10)
    ] == ["photo.jpg", "clip.mp4"]
    assert catalog.ordered_query_picture_ids(snapshot_query) == [
        media_ids[1],
        media_ids[0],
    ]
    assert catalog.ordered_collection_picture_ids(snapshot_id) == [
        media_ids[1],
        media_ids[0],
    ]
    export_rows = catalog.media_for_export([media_ids[1], media_ids[0]])
    assert {row["id"] for row in export_rows} == set(media_ids)
    assert {row["source_label"] for row in export_rows} == {"Collection media"}

    assert catalog.rename_collection(collection_id, "Renamed picks") is True
    assert catalog.get_collection(collection_id).name == "Renamed picks"
    assert catalog.delete_collection(collection_id) is True


def test_mysql_collection_music_playlist_roundtrip(tmp_path) -> None:
    catalog = Catalog(DatabaseEngine(mysql_settings(tmp_path)))
    catalog.initialize()
    smart_id = catalog.create_saved_search(
        "Summer music", build_global_search_request("summer").query
    )
    manual_id = catalog.create_collection("Family music")

    assert catalog.set_music_playlist(
        "smart", smart_id, "smb://nas/music/summer.m3u"
    )
    assert catalog.set_music_playlist(
        "manual", manual_id, "smb://nas/music/family.pls"
    )
    assert catalog.get_music_playlist("smart", smart_id).endswith("summer.m3u")
    assert catalog.get_music_playlist("manual", manual_id).endswith("family.pls")
    assert catalog.list_saved_searches()[0]["music_playlist_uri"].endswith(
        "summer.m3u"
    )
    assert catalog.list_collections()[0]["music_playlist_uri"].endswith(
        "family.pls"
    )

    assert catalog.delete_saved_search(smart_id)
    assert catalog.delete_collection(manual_id)
    with catalog.engine.transaction() as connection:
        total = catalog.engine.fetchone(
            connection,
            "SELECT COUNT(*) AS total FROM collection_music_playlists",
        )["total"]
    assert total == 0
