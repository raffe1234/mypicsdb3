from __future__ import annotations

from pathlib import Path
from typing import Optional

from mypicsdb3.config import Settings
from mypicsdb3.db.catalog import Catalog
from mypicsdb3.db.engine import DatabaseEngine
from mypicsdb3.utils import sha256_text, utc_now


def make_catalog(tmp_path: Path) -> Catalog:
    settings = Settings(profile_path=str(tmp_path), database_backend="sqlite")
    catalog = Catalog(DatabaseEngine(settings))
    catalog.initialize()
    return catalog


def add_picture(
    catalog: Catalog,
    root: Path,
    name: str = "image.jpg",
    taken_at: Optional[str] = "2020-07-17 14:15:16",
    discovered_at: str = "2026-07-17 09:00:00",
    rating: Optional[int] = 5,
    media_type: str = "picture",
) -> int:
    source = catalog.sync_sources([{"label": "Photos", "uri": str(root)}])[0]
    catalog.set_source_enabled(source.id, True)
    now = utc_now()
    with catalog.engine.transaction() as connection:
        folder_id = catalog.upsert_folder(connection, source.id, str(root) + "/", "", "Photos", now)
        picture_id = catalog.insert_picture(
            connection,
            {
                "source_id": source.id,
                "folder_id": folder_id,
                "uri": str(root / name),
                "filename": name,
                "extension": Path(name).suffix.lstrip(".").lower() or (
                    "mp4" if media_type == "video" else "jpg"
                ),
                "media_type": media_type,
                "file_size": 123,
                "file_mtime": 1000.0,
                "discovered_at": discovered_at,
                "last_seen_at": now,
                "taken_at": taken_at,
                "taken_source": "EXIF DateTimeOriginal",
                "width": 1920,
                "height": 1080,
                "orientation": 1,
                "mime_type": "image/jpeg",
                "camera_make": "Canon",
                "camera_model": "EOS R6",
                "rating": rating,
                "gps_latitude": 59.3293,
                "gps_longitude": 18.0686,
                "city": "Stockholm",
                "state": None,
                "country": "Sweden",
                "sublocation": None,
                "caption": "A summer memory",
                "metadata_hash": "abc",
                "thumb_uri": str(root / name),
            },
            ["Summer", "Family", "summer"],
        )
        catalog.update_folder_summaries(connection, source.id)
    return picture_id


def test_catalog_queries_and_favorites(tmp_path: Path) -> None:
    catalog = make_catalog(tmp_path)
    picture_id = add_picture(catalog, tmp_path / "photos")

    assert catalog.overview()["pictures"] == 1
    assert catalog.recent_taken(10)[0]["filename"] == "image.jpg"
    assert catalog.recent_added(10)[0]["id"] == picture_id
    assert catalog.on_this_day(7, 17, 2026, 10)[0]["taken_year"] == 2020
    assert catalog.pictures_for_year(2020, 10)[0]["camera_model"] == "EOS R6"
    assert catalog.pictures_for_camera("Canon", "EOS R6", 10)[0]["id"] == picture_id
    assert catalog.random_pictures(10)[0]["id"] == picture_id
    assert catalog.random_folders(10)[0]["picture_count"] == 1
    assert catalog.years() == [{"year": 2020, "picture_count": 1, "uri": str(tmp_path / "photos" / "image.jpg"), "thumb_uri": str(tmp_path / "photos" / "image.jpg"), "media_type": "picture"}]
    assert catalog.cameras()[0]["picture_count"] == 1
    tags = catalog.tags()
    assert {row["name"] for row in tags} == {"Summer", "Family"}
    family = next(row for row in tags if row["name"] == "Family")
    assert catalog.pictures_for_tag(family["id"], 10)[0]["id"] == picture_id

    assert catalog.toggle_favorite(picture_id) is True
    assert catalog.favorites(10)[0]["id"] == picture_id
    assert catalog.rated(10)[0]["rating"] == 5
    assert catalog.geotagged(10)[0]["city"] == "Stockholm"
    location_row = catalog.picture_by_id(picture_id)
    assert location_row is not None
    assert location_row["gps_latitude"] == 59.3293
    assert location_row["gps_longitude"] == 18.0686
    assert location_row["city"] == "Stockholm"
    assert catalog.picture_by_id(0) is None
    assert catalog.picture_ids_in_folder(int(location_row["folder_id"])) == [picture_id]

    refreshed = dict(location_row)
    refreshed.update({
        "camera_make": "Samsung",
        "camera_model": "SM-S921B",
        "gps_latitude": 59.3,
        "gps_longitude": 18.0,
        "city": "Stockholm",
        "country": "Sweden",
        "metadata_hash": "refreshed",
        "metadata_index_hash": "index-signature",
    })
    assert catalog.refresh_picture_record(picture_id, refreshed, ["Refreshed"]) is True
    refreshed_row = catalog.picture_by_id(picture_id)
    assert refreshed_row["camera_make"] == "Samsung"
    assert refreshed_row["camera_model"] == "SM-S921B"
    assert {row["name"] for row in catalog.tags()} == {"Refreshed"}


def test_album_art_prefers_a_picture_over_a_newer_video(tmp_path: Path) -> None:
    catalog = make_catalog(tmp_path)
    root = tmp_path / "mixed-album"
    picture_id = add_picture(
        catalog,
        root,
        "cover.jpg",
        taken_at="2024-01-01 12:00:00",
        discovered_at="2026-07-20 09:00:00",
    )
    add_picture(
        catalog,
        root,
        "latest.mp4",
        taken_at="2026-06-21 03:15:00",
        discovered_at="2026-07-21 09:00:00",
        media_type="video",
    )

    recent = catalog.recent_folders(10)[0]
    random_album = catalog.random_folders(10)[0]

    assert recent["representative_uri"].endswith("cover.jpg")
    assert recent["representative_media_type"] == "picture"
    assert random_album["representative_uri"].endswith("cover.jpg")
    assert random_album["representative_media_type"] == "picture"
    with catalog.engine.transaction() as connection:
        summary = catalog.engine.fetchone(
            connection,
            "SELECT representative_picture_id, latest_taken_at, latest_discovered_at "
            "FROM folders WHERE id=?",
            (recent["id"],),
        )
    assert summary["representative_picture_id"] == picture_id
    assert summary["latest_taken_at"] == "2026-06-21 03:15:00"
    assert summary["latest_discovered_at"] == "2026-07-21 09:00:00"


def test_album_art_prefers_common_still_format_over_newer_raw(tmp_path: Path) -> None:
    catalog = make_catalog(tmp_path)
    root = tmp_path / "raw-album"
    add_picture(
        catalog,
        root,
        "cover.jpg",
        taken_at="2024-01-01 12:00:00",
        discovered_at="2026-07-20 09:00:00",
    )
    add_picture(
        catalog,
        root,
        "latest.nef",
        taken_at="2026-06-21 03:15:00",
        discovered_at="2026-07-21 09:00:00",
    )

    album = catalog.recent_folders(10)[0]

    assert album["representative_uri"].endswith("cover.jpg")
    assert album["representative_extension"] == "jpg"


def test_video_only_album_keeps_video_as_fallback_art(tmp_path: Path) -> None:
    catalog = make_catalog(tmp_path)
    root = tmp_path / "video-album"
    video_id = add_picture(
        catalog,
        root,
        "only.mp4",
        taken_at="2026-06-21 00:15:53",
        media_type="video",
    )

    album = catalog.recent_folders(10)[0]

    assert album["representative_uri"].endswith("only.mp4")
    assert album["representative_media_type"] == "video"
    with catalog.engine.transaction() as connection:
        summary = catalog.engine.fetchone(
            connection,
            "SELECT representative_picture_id FROM folders WHERE id=?",
            (album["id"],),
        )
    assert summary["representative_picture_id"] == video_id


def test_date_hierarchy_and_undated_queries(tmp_path: Path) -> None:
    catalog = make_catalog(tmp_path)
    root = tmp_path / "photos"
    first = add_picture(catalog, root, "first.jpg", "2020-07-17 14:15:16")
    second = add_picture(catalog, root, "second.jpg", "2020-07-18 09:00:00")
    third = add_picture(catalog, root, "third.jpg", "2021-12-25 18:30:00")
    undated = add_picture(
        catalog,
        root,
        "undated.jpg",
        None,
        discovered_at="2026-07-20 11:00:00",
    )

    assert [(row["year"], row["picture_count"]) for row in catalog.years()] == [
        (2021, 1),
        (2020, 2),
    ]
    assert [(row["month"], row["picture_count"]) for row in catalog.months_for_year(2020)] == [
        (7, 2),
    ]
    assert [(row["day"], row["picture_count"]) for row in catalog.days_for_month(2020, 7)] == [
        (17, 1),
        (18, 1),
    ]
    assert [row["id"] for row in catalog.pictures_for_day(2020, 7, 17, 10)] == [first]
    assert [row["id"] for row in catalog.pictures_for_day(2020, 7, 18, 10)] == [second]
    assert [row["id"] for row in catalog.pictures_for_day(2021, 12, 25, 10)] == [third]
    assert catalog.undated_summary()["picture_count"] == 1
    assert [row["id"] for row in catalog.pictures_without_date(10)] == [undated]


def test_scan_lock_is_exclusive(tmp_path: Path) -> None:
    catalog = make_catalog(tmp_path)
    assert catalog.acquire_lock("catalogue-scan", "first", ttl_seconds=60)
    assert not catalog.acquire_lock("catalogue-scan", "second", ttl_seconds=60)
    catalog.release_lock("catalogue-scan", "first")
    assert catalog.acquire_lock("catalogue-scan", "second", ttl_seconds=60)


def test_scan_lock_can_be_refreshed_but_expired_lock_is_not_revived(tmp_path: Path) -> None:
    catalog = make_catalog(tmp_path)
    assert catalog.acquire_lock("catalogue-scan", "first", ttl_seconds=60)
    assert not catalog.refresh_lock("catalogue-scan", "second", ttl_seconds=120)
    assert catalog.refresh_lock("catalogue-scan", "first", ttl_seconds=120)

    with catalog.engine.transaction() as connection:
        catalog.engine.execute(
            connection,
            "UPDATE locks SET expires_at=? WHERE name=?",
            ("2000-01-01 00:00:00", "catalogue-scan"),
        ).close()

    assert not catalog.refresh_lock("catalogue-scan", "first", ttl_seconds=120)
    assert catalog.acquire_lock("catalogue-scan", "second", ttl_seconds=60)


def test_delete_source_removes_its_catalogue_rows(tmp_path: Path) -> None:
    catalog = make_catalog(tmp_path)
    add_picture(catalog, tmp_path / "photos")
    source = catalog.get_sources()[0]

    assert catalog.delete_source(source.id) is True
    assert catalog.get_sources() == []
    assert catalog.overview()["pictures"] == 0
    assert catalog.overview()["folders"] == 0
    assert catalog.tags() == []
    assert catalog.delete_source(source.id) is False


def test_sync_sources_removes_kodi_picture_addons_virtual_source(tmp_path: Path) -> None:
    catalog = make_catalog(tmp_path)
    virtual_uri = "addons://sources/image/"
    now = utc_now()
    with catalog.engine.transaction() as connection:
        catalog.engine.execute(
            connection,
            "INSERT INTO sources (label, uri, uri_hash, enabled, available, created_at, updated_at) "
            "VALUES (?, ?, ?, 0, 1, ?, ?)",
            ("Picture add-ons", virtual_uri, sha256_text(virtual_uri), now, now),
        ).close()

    sources = catalog.sync_sources([
        {"label": "Photos", "uri": str(tmp_path / "photos")},
        {"label": "Picture add-ons", "uri": virtual_uri},
    ])

    assert [source.label for source in sources] == ["Photos"]


def test_videos_share_date_and_folder_views_without_fake_ratings(tmp_path: Path) -> None:
    catalog = make_catalog(tmp_path)
    root = tmp_path / "media"
    picture_id = add_picture(catalog, root, "photo.jpg", rating=5)
    video_id = add_picture(
        catalog,
        root,
        "clip.mp4",
        taken_at="2020-07-18 10:00:00",
        rating=None,
        media_type="video",
    )

    assert catalog.overview()["videos"] == 1
    assert [row["id"] for row in catalog.videos(10)] == [video_id]
    assert {row["id"] for row in catalog.pictures_for_year(2020, 10)} == {
        picture_id,
        video_id,
    }
    catalog.set_rating_policy("5")
    folder_id = catalog.recent_taken(10)[0]["folder_id"]
    assert {row["id"] for row in catalog.pictures_in_folder(folder_id, 10)} == {
        picture_id,
        video_id,
    }
    assert [row["id"] for row in catalog.rated(10)] == [picture_id]


def test_seeded_random_picture_rows_are_repeatable(tmp_path: Path) -> None:
    catalog = make_catalog(tmp_path)
    root = tmp_path / "seeded-random"
    picture_ids = [
        add_picture(catalog, root, "memory-1.jpg", "2018-07-17 08:00:00"),
        add_picture(catalog, root, "memory-2.jpg", "2019-07-17 09:00:00"),
        add_picture(catalog, root, "memory-3.jpg", "2020-07-17 10:00:00"),
        add_picture(catalog, root, "memory-4.jpg", "2021-07-17 11:00:00"),
    ]
    with catalog.engine.transaction() as connection:
        for picture_id, random_key in zip(picture_ids, (0.1, 0.3, 0.6, 0.9)):
            catalog.engine.execute(
                connection,
                "UPDATE pictures SET random_key=? WHERE id=?",
                (random_key, picture_id),
            ).close()

    first = [row["id"] for row in catalog.random_pictures(3, seed=0.25)]
    second = [row["id"] for row in catalog.random_pictures(3, seed=0.25)]
    day_first = [
        row["id"]
        for row in catalog.random_on_this_day(7, 17, 2026, 3, seed=0.25)
    ]
    day_second = [
        row["id"]
        for row in catalog.random_on_this_day(7, 17, 2026, 3, seed=0.25)
    ]

    assert first == second
    assert day_first == day_second


def test_random_on_this_day_uses_all_earlier_years_without_duplicates(
    tmp_path: Path, monkeypatch
) -> None:
    catalog = make_catalog(tmp_path)
    root = tmp_path / "photos"
    ids = [
        add_picture(catalog, root, "memory-2018.jpg", "2018-07-17 08:00:00"),
        add_picture(catalog, root, "memory-2020.jpg", "2020-07-17 09:00:00"),
        add_picture(catalog, root, "memory-2024.jpg", "2024-07-17 10:00:00"),
    ]
    add_picture(catalog, root, "today.jpg", "2026-07-17 11:00:00")
    add_picture(catalog, root, "other-day.jpg", "2024-07-18 12:00:00")

    with catalog.engine.transaction() as connection:
        for picture_id, random_key in zip(ids, (0.1, 0.6, 0.9)):
            catalog.engine.execute(
                connection,
                "UPDATE pictures SET random_key=? WHERE id=?",
                (random_key, picture_id),
            ).close()

    monkeypatch.setattr("mypicsdb3.db.catalog.random.random", lambda: 0.5)
    shuffled = []

    def reverse_rows(rows):
        shuffled.append([row["id"] for row in rows])
        rows.reverse()

    monkeypatch.setattr("mypicsdb3.db.catalog.random.shuffle", reverse_rows)
    rows = catalog.random_on_this_day(7, 17, 2026, 10)

    assert shuffled == [[ids[1], ids[2], ids[0]]]
    assert [row["id"] for row in rows] == [ids[0], ids[2], ids[1]]
    assert {row["id"] for row in rows} == set(ids)
    assert len(rows) == len({row["id"] for row in rows})
    assert catalog.media_type_for_uri(str(root / "memory-2020.jpg")) == "picture"
    assert catalog.media_type_for_uri(str(root / "missing.jpg")) is None


def test_manual_collections_preserve_mixed_media_order_and_reject_duplicates(
    tmp_path: Path,
) -> None:
    catalog = make_catalog(tmp_path)
    root = tmp_path / "collection-media"
    first = add_picture(
        catalog,
        root,
        "first.jpg",
        taken_at="2020-01-01 10:00:00",
    )
    second = add_picture(
        catalog,
        root,
        "second.mp4",
        taken_at="2024-01-01 10:00:00",
        media_type="video",
        rating=None,
    )
    third = add_picture(
        catalog,
        root,
        "third.jpg",
        taken_at="2026-01-01 10:00:00",
    )

    collection_id = catalog.create_collection("  Family picks  ")
    assert catalog.get_collection(collection_id).name == "Family picks"
    assert catalog.add_picture_to_collection(collection_id, second) is True
    assert catalog.add_picture_to_collection(collection_id, first) is True
    assert catalog.add_picture_to_collection(collection_id, second) is False

    rows = catalog.pictures_in_collection(collection_id, 10)
    assert [row["id"] for row in rows] == [second, first]
    assert [row["media_type"] for row in rows] == ["video", "picture"]

    summary = catalog.list_collections()[0]
    assert summary["name"] == "Family picks"
    assert summary["item_count"] == 2
    assert summary["available_count"] == 2
    assert summary["uri"].endswith("second.mp4")

    assert catalog.remove_picture_from_collection(collection_id, second) is True
    assert catalog.remove_picture_from_collection(collection_id, second) is False
    assert catalog.add_picture_to_collection(collection_id, third) is True
    assert [row["id"] for row in catalog.pictures_in_collection(collection_id, 10)] == [
        first,
        third,
    ]



def test_collection_snapshot_freezes_query_membership_and_order(tmp_path: Path) -> None:
    catalog = make_catalog(tmp_path)
    root = tmp_path / "snapshot"
    first = add_picture(catalog, root, "b.jpg", taken_at="2024-01-02 10:00:00")
    second = add_picture(catalog, root, "a.jpg", taken_at="2024-01-03 10:00:00")
    source = catalog.sync_sources([{"label": "Photos", "uri": str(root)}])[0]
    query = {
        "version": 1,
        "root": {"type": "group", "match": "all", "negated": False, "children": []},
        "sort": [{"field": "filename", "direction": "asc"}],
        "scope": {
            "source_ids": [source.id],
            "include_missing": False,
            "include_excluded": False,
        },
        "default_policy": {"apply_min_rating": False},
    }

    collection_id, item_count = catalog.create_collection_snapshot(
        "Frozen result", query
    )
    assert item_count == 2
    assert [
        row["id"] for row in catalog.pictures_in_collection(collection_id, 10)
    ] == [second, first]

    add_picture(catalog, root, "aa.jpg", taken_at="2024-01-04 10:00:00")
    assert catalog.collection_available_count(collection_id) == 2
    assert [
        row["filename"] for row in catalog.pictures_in_collection(collection_id, 10)
    ] == ["a.jpg", "b.jpg"]


def test_collection_snapshot_rolls_back_when_query_is_empty(tmp_path: Path) -> None:
    from mypicsdb3.static_collections import CollectionValidationError

    catalog = make_catalog(tmp_path)
    query = {
        "version": 1,
        "root": {
            "type": "group",
            "match": "all",
            "negated": False,
            "children": [
                {
                    "type": "rule",
                    "field": "country",
                    "operator": "eq",
                    "value": "Nowhere",
                }
            ],
        },
        "sort": [],
        "scope": {
            "source_ids": [],
            "include_missing": False,
            "include_excluded": False,
        },
        "default_policy": {"apply_min_rating": False},
    }
    try:
        catalog.create_collection_snapshot("Empty", query)
    except CollectionValidationError:
        pass
    else:
        raise AssertionError("Empty snapshots must be rejected")
    assert catalog.list_collections() == []


def test_manual_collection_items_can_be_reordered_and_positions_are_compacted(
    tmp_path: Path,
) -> None:
    catalog = make_catalog(tmp_path)
    root = tmp_path / "ordered-collection"
    first = add_picture(catalog, root, "first.jpg")
    second = add_picture(
        catalog,
        root,
        "second.mp4",
        media_type="video",
        rating=None,
    )
    third = add_picture(catalog, root, "third.jpg")
    collection_id = catalog.create_collection("Ordered")
    for picture_id in (first, second, third):
        assert catalog.add_picture_to_collection(collection_id, picture_id)

    assert catalog.move_picture_in_collection(collection_id, third, "top")
    assert [row["id"] for row in catalog.pictures_in_collection(collection_id, 10)] == [
        third,
        first,
        second,
    ]
    assert not catalog.move_picture_in_collection(collection_id, third, "up")

    assert catalog.move_picture_in_collection(collection_id, first, "down")
    assert [row["id"] for row in catalog.pictures_in_collection(collection_id, 10)] == [
        third,
        second,
        first,
    ]
    assert not catalog.move_picture_in_collection(collection_id, first, "bottom")

    assert catalog.move_picture_in_collection(collection_id, first, "top")
    assert catalog.move_picture_in_collection(collection_id, first, "down")
    assert [row["id"] for row in catalog.pictures_in_collection(collection_id, 10)] == [
        third,
        first,
        second,
    ]

    assert catalog.remove_picture_from_collection(collection_id, first)
    with catalog.engine.transaction() as connection:
        stored = catalog.engine.fetchall(
            connection,
            "SELECT picture_id, position FROM collection_items "
            "WHERE collection_id=? ORDER BY position",
            (collection_id,),
        )
    assert [(row["picture_id"], row["position"]) for row in stored] == [
        (third, 1),
        (second, 2),
    ]
    assert catalog.collection_available_count(collection_id) == 2

    try:
        catalog.move_picture_in_collection(collection_id, third, "sideways")
    except ValueError:
        pass
    else:
        raise AssertionError("Invalid move directions must be rejected")


def test_manual_collection_rename_delete_and_missing_media_are_safe(
    tmp_path: Path,
) -> None:
    catalog = make_catalog(tmp_path)
    root = tmp_path / "missing-collection"
    visible = add_picture(catalog, root, "visible.jpg")
    missing = add_picture(catalog, root, "missing.jpg")
    collection_id = catalog.create_collection("Before")
    assert catalog.add_picture_to_collection(collection_id, missing)
    assert catalog.add_picture_to_collection(collection_id, visible)

    assert catalog.rename_collection(collection_id, "After") is True
    assert catalog.get_collection(collection_id).name == "After"
    with catalog.engine.transaction() as connection:
        catalog.engine.execute(
            connection,
            "UPDATE pictures SET is_missing=1, missing_since=? WHERE id=?",
            ("2020-01-01 00:00:00", missing),
        ).close()

    assert [row["id"] for row in catalog.pictures_in_collection(collection_id, 10)] == [
        visible
    ]
    summary = catalog.list_collections()[0]
    assert summary["item_count"] == 2
    assert summary["available_count"] == 1

    assert catalog.delete_collection(collection_id) is True
    assert catalog.get_collection(collection_id) is None
    assert catalog.recent_added(10)
    with catalog.engine.transaction() as connection:
        assert catalog.engine.fetchone(
            connection,
            "SELECT COUNT(*) AS total FROM pictures",
        )["total"] == 2
        assert catalog.engine.fetchone(
            connection,
            "SELECT COUNT(*) AS total FROM collection_items",
        )["total"] == 0


def test_export_selection_helpers_freeze_order_and_return_bounded_metadata(
    tmp_path: Path,
) -> None:
    catalog = make_catalog(tmp_path)
    root = tmp_path / "export"
    first = add_picture(catalog, root, "b.jpg", taken_at="2024-01-02 10:00:00")
    second = add_picture(catalog, root, "a.jpg", taken_at="2024-01-03 10:00:00")
    source = catalog.sync_sources([{"label": "Photos", "uri": str(root)}])[0]
    query = {
        "version": 1,
        "root": {"type": "group", "match": "all", "negated": False, "children": []},
        "sort": [{"field": "filename", "direction": "asc"}],
        "scope": {
            "source_ids": [source.id],
            "include_missing": False,
            "include_excluded": False,
        },
        "default_policy": {"apply_min_rating": False},
    }

    assert catalog.ordered_query_picture_ids(query) == [second, first]
    collection_id = catalog.create_collection("Export order")
    assert catalog.add_picture_to_collection(collection_id, first) is True
    assert catalog.add_picture_to_collection(collection_id, second) is True
    assert catalog.ordered_collection_picture_ids(collection_id) == [first, second]

    rows = catalog.media_for_export([second, first])
    by_id = {row["id"]: row for row in rows}
    assert set(by_id) == {first, second}
    assert by_id[first]["filename"] == "b.jpg"
    assert by_id[second]["source_label"] == "Photos"

    try:
        catalog.media_for_export(list(range(1, 502)))
    except ValueError as exc:
        assert "at most 500" in str(exc)
    else:
        raise AssertionError("Unbounded export metadata batches must be rejected")


def test_catalog_meta_value_roundtrip(tmp_path: Path) -> None:
    catalog = make_catalog(tmp_path)

    assert catalog.meta_value("last_complete_scan_at") is None
    catalog.set_meta_value("last_complete_scan_at", "2026-08-17 10:00:00.000000")
    assert catalog.meta_value("last_complete_scan_at") == "2026-08-17 10:00:00.000000"
    catalog.set_meta_value("last_complete_scan_at", "2026-08-17 11:00:00.000000")
    assert catalog.meta_value("last_complete_scan_at") == "2026-08-17 11:00:00.000000"
