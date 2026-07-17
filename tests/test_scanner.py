from __future__ import annotations

import os
from pathlib import Path

from mypicsdb3.config import Settings
from mypicsdb3.db.catalog import Catalog
from mypicsdb3.db.engine import DatabaseEngine
from mypicsdb3.filesystem import LocalFilesystem
from mypicsdb3.models import MetadataResult
from mypicsdb3.scanner import Scanner


def fake_metadata(path, filesystem, settings, file_size):
    filename = Path(path).name
    year = 2020 if filename.startswith("old") else 2026
    return MetadataResult(
        taken_at=f"{year}-07-17 12:00:00",
        taken_source="Test metadata",
        width=1600,
        height=900,
        orientation=1,
        mime_type="image/jpeg",
        camera_make="Test",
        camera_model="Camera",
        rating=4,
        gps_latitude=59.0 if settings.store_gps else None,
        gps_longitude=18.0 if settings.store_gps else None,
        keywords=["Test", filename],
        location={"country": "Sweden"},
        caption=filename,
        metadata_hash="metadata-" + filename,
    )


def setup_scanner(tmp_path: Path, root: Path):
    settings = Settings(
        profile_path=str(tmp_path / "profile"),
        database_backend="sqlite",
        extensions=("jpg",),
        exclude_fragments=("#recycle",),
        batch_size=10,
        store_gps=True,
    )
    catalog = Catalog(DatabaseEngine(settings))
    catalog.initialize()
    source = catalog.sync_sources([{"label": "Photos", "uri": str(root)}])[0]
    catalog.set_source_enabled(source.id, True)
    scanner = Scanner(catalog, LocalFilesystem(), settings, metadata_reader=fake_metadata)
    return catalog, source, scanner


def test_incremental_scan_missing_files_and_unavailable_source(tmp_path: Path) -> None:
    root = tmp_path / "photos"
    album = root / "Summer"
    album.mkdir(parents=True)
    (root / "old.jpg").write_bytes(b"old")
    (album / "new.jpg").write_bytes(b"new")
    (root / "ignore.txt").write_text("not a picture", encoding="utf-8")
    hidden = root / ".hidden"
    hidden.mkdir()
    (hidden / "hidden.jpg").write_bytes(b"hidden")

    catalog, source, scanner = setup_scanner(tmp_path, root)
    first = scanner.scan_sources()
    assert first.pictures_added == 2
    assert first.pictures_seen == 2
    assert first.errors == 0
    assert catalog.overview()["pictures"] == 2
    assert len(catalog.recent_taken(10)) == 2
    assert len(catalog.recent_folders(10)) == 2

    second = scanner.scan_sources()
    assert second.pictures_unchanged == 2
    assert second.pictures_added == 0

    (album / "new.jpg").write_bytes(b"new and changed")
    os.utime(album / "new.jpg", None)
    third = scanner.scan_sources()
    assert third.pictures_updated == 1
    assert third.pictures_unchanged == 1

    (album / "new.jpg").unlink()
    fourth = scanner.scan_sources()
    assert fourth.missing_marked >= 1
    assert catalog.overview()["missing"] == 1
    assert len(catalog.recent_taken(10)) == 1
    assert catalog.cleanup_missing(0) == 1
    assert catalog.overview()["pictures"] == 1

    root.rename(tmp_path / "photos-offline")
    unavailable = scanner.scan_source(catalog.get_source(source.id))
    assert unavailable.sources_unavailable == 1
    assert unavailable.errors == 1
    assert catalog.overview()["missing"] == 0


def test_scanner_honours_excluded_fragments(tmp_path: Path) -> None:
    root = tmp_path / "photos"
    excluded = root / "#recycle"
    excluded.mkdir(parents=True)
    (excluded / "deleted.jpg").write_bytes(b"deleted")
    (root / "kept.jpg").write_bytes(b"kept")

    catalog, _, scanner = setup_scanner(tmp_path, root)
    result = scanner.scan_sources()
    assert result.pictures_seen == 1
    assert catalog.recent_added(10)[0]["filename"] == "kept.jpg"
