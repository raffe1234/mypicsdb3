from __future__ import annotations

from pathlib import Path

from mypicsdb3.config import Settings
from mypicsdb3.db.catalog import Catalog
from mypicsdb3.db.engine import DatabaseEngine
from mypicsdb3.utils import sha256_text, utc_now


def make_catalog(tmp_path: Path) -> Catalog:
    settings = Settings(profile_path=str(tmp_path), database_backend="sqlite")
    catalog = Catalog(DatabaseEngine(settings))
    catalog.initialize()
    return catalog


def add_picture(catalog: Catalog, root: Path, name: str = "image.jpg") -> int:
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
                "extension": "jpg",
                "file_size": 123,
                "file_mtime": 1000.0,
                "discovered_at": "2026-07-17 09:00:00",
                "last_seen_at": now,
                "taken_at": "2020-07-17 14:15:16",
                "taken_source": "EXIF DateTimeOriginal",
                "width": 1920,
                "height": 1080,
                "orientation": 1,
                "mime_type": "image/jpeg",
                "camera_make": "Canon",
                "camera_model": "EOS R6",
                "rating": 5,
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
    assert catalog.years() == [{"year": 2020, "picture_count": 1, "uri": str(tmp_path / "photos" / "image.jpg"), "thumb_uri": str(tmp_path / "photos" / "image.jpg")}]
    assert catalog.cameras()[0]["picture_count"] == 1
    tags = catalog.tags()
    assert {row["name"] for row in tags} == {"Summer", "Family"}
    family = next(row for row in tags if row["name"] == "Family")
    assert catalog.pictures_for_tag(family["id"], 10)[0]["id"] == picture_id

    assert catalog.toggle_favorite(picture_id) is True
    assert catalog.favorites(10)[0]["id"] == picture_id
    assert catalog.rated(10)[0]["rating"] == 5
    assert catalog.geotagged(10)[0]["city"] == "Stockholm"


def test_scan_lock_is_exclusive(tmp_path: Path) -> None:
    catalog = make_catalog(tmp_path)
    assert catalog.acquire_lock("catalogue-scan", "first", ttl_seconds=60)
    assert not catalog.acquire_lock("catalogue-scan", "second", ttl_seconds=60)
    catalog.release_lock("catalogue-scan", "first")
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
