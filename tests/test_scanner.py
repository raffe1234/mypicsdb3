from __future__ import annotations

import os
from pathlib import Path

import mypicsdb3.scanner as scanner_module
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


def setup_scanner(
    tmp_path: Path,
    root: Path,
    exclude_fragments=("#recycle",),
):
    settings = Settings(
        profile_path=str(tmp_path / "profile"),
        database_backend="sqlite",
        extensions=("jpg",),
        exclude_fragments=exclude_fragments,
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


def test_scanner_always_ignores_synology_eadir_trees(tmp_path: Path) -> None:
    root = tmp_path / "photos"
    metadata = root / "Album@eaDir" / "20260515_094806.jpg"
    metadata.mkdir(parents=True)
    (metadata / "SYNOPHOTO_THUMB_B.jpg").write_bytes(b"thumbnail")
    (metadata / "SYNOPHOTO_THUMB_S.jpg").write_bytes(b"thumbnail")
    (metadata / "SYNOPHOTO_THUMB_XL.jpg").write_bytes(b"thumbnail")
    (root / "20260515_094806.jpg").write_bytes(b"original")

    catalog, _, scanner = setup_scanner(
        tmp_path,
        root,
        exclude_fragments=(),
    )
    result = scanner.scan_sources()

    assert result.pictures_seen == 1
    assert result.pictures_added == 1
    assert [row["filename"] for row in catalog.recent_added(10)] == [
        "20260515_094806.jpg"
    ]


def test_scan_stops_as_soon_as_a_blocking_listdir_returns(tmp_path: Path) -> None:
    root = tmp_path / "photos"
    root.mkdir()
    (root / "image.jpg").write_bytes(b"image")
    catalog, _, original_scanner = setup_scanner(tmp_path, root)
    state = {"cancelled": False}

    class CancelAfterListdirFilesystem(LocalFilesystem):
        def listdir(self, path):
            value = super().listdir(path)
            state["cancelled"] = True
            return value

    scanner = Scanner(
        catalog,
        CancelAfterListdirFilesystem(),
        original_scanner.settings,
        metadata_reader=fake_metadata,
        cancelled=lambda: state["cancelled"],
    )

    result = scanner.scan_sources()

    assert result.cancelled is True
    assert catalog.overview()["pictures"] == 0
    assert catalog.latest_scan()["status"] == "cancelled"


def test_scan_stops_after_stat_before_reading_metadata(tmp_path: Path) -> None:
    root = tmp_path / "photos"
    root.mkdir()
    (root / "image.jpg").write_bytes(b"image")
    catalog, _, original_scanner = setup_scanner(tmp_path, root)
    state = {"cancelled": False}
    metadata_calls = []

    class CancelAfterStatFilesystem(LocalFilesystem):
        def stat(self, path):
            value = super().stat(path)
            state["cancelled"] = True
            return value

    def metadata_reader(*args):
        metadata_calls.append(args)
        return fake_metadata(*args)

    scanner = Scanner(
        catalog,
        CancelAfterStatFilesystem(),
        original_scanner.settings,
        metadata_reader=metadata_reader,
        cancelled=lambda: state["cancelled"],
    )

    result = scanner.scan_sources()

    assert result.cancelled is True
    assert metadata_calls == []
    assert catalog.overview()["pictures"] == 0


def test_active_scan_refreshes_its_shorter_lock(monkeypatch, tmp_path: Path) -> None:
    root = tmp_path / "photos"
    root.mkdir()
    (root / "image.jpg").write_bytes(b"image")
    catalog, _, original_scanner = setup_scanner(tmp_path, root)
    refresh_calls = []
    original_refresh = catalog.refresh_lock

    def refresh_lock(name, owner, ttl_seconds, connection=None):
        refresh_calls.append((name, owner, ttl_seconds))
        return original_refresh(name, owner, ttl_seconds, connection=connection)

    monkeypatch.setattr(catalog, "refresh_lock", refresh_lock)
    monkeypatch.setattr(scanner_module, "SCAN_LOCK_REFRESH_SECONDS", 0)
    scanner = Scanner(
        catalog,
        LocalFilesystem(),
        original_scanner.settings,
        metadata_reader=fake_metadata,
    )

    result = scanner.scan_sources()

    assert result.cancelled is False
    assert refresh_calls
    assert all(call[0] == "catalogue-scan" for call in refresh_calls)
    assert all(call[2] == 1800 for call in refresh_calls)


def test_video_scan_skips_picture_metadata_and_stores_media_type(tmp_path: Path) -> None:
    media = tmp_path / "media"
    media.mkdir()
    (media / "photo.jpg").write_bytes(b"picture")
    (media / "clip.mp4").write_bytes(b"video")

    settings = Settings(
        profile_path=str(tmp_path / "profile"),
        extensions=("jpg",),
        include_videos=True,
        video_extensions=("mp4",),
    )
    catalog = Catalog(DatabaseEngine(settings))
    catalog.initialize()
    source = catalog.sync_sources([{"label": "Media", "uri": str(media)}])[0]
    catalog.set_source_enabled(source.id, True)
    metadata_calls = []

    def picture_metadata(path, filesystem, scan_settings, file_size):
        metadata_calls.append(Path(path).name)
        return MetadataResult(mime_type="image/jpeg")

    stats = Scanner(
        catalog,
        LocalFilesystem(),
        settings,
        metadata_reader=picture_metadata,
    ).scan_sources()

    assert stats.pictures_seen == 2
    assert metadata_calls == ["photo.jpg"]
    rows = catalog.recent_added(10)
    assert {row["filename"]: row["media_type"] for row in rows} == {
        "photo.jpg": "picture",
        "clip.mp4": "video",
    }
    video = next(row for row in rows if row["media_type"] == "video")
    assert video["mime_type"] == "video/mp4"
    assert video["thumb_uri"] is None
    assert video["taken_source"] == "File mtime fallback"


def test_partial_directory_traversal_preserves_missing_state_until_clean_scan(
    tmp_path: Path,
) -> None:
    root = tmp_path / "photos"
    readable = root / "Readable"
    blocked = root / "Blocked"
    nested = blocked / "Nested"
    readable.mkdir(parents=True)
    nested.mkdir(parents=True)
    deleted = readable / "deleted.jpg"
    preserved = nested / "preserved.jpg"
    deleted.write_bytes(b"deleted later")
    preserved.write_bytes(b"keep indexed")

    catalog, source, scanner = setup_scanner(tmp_path, root)
    first = scanner.scan_sources()
    assert first.pictures_added == 2

    deleted.unlink()
    added = readable / "added.jpg"
    added.write_bytes(b"new during partial scan")

    class PartiallyUnavailableFilesystem(LocalFilesystem):
        def listdir(self, path):
            if Path(path).resolve() == blocked.resolve():
                raise OSError("temporary SMB directory failure")
            return super().listdir(path)

    partial_scanner = Scanner(
        catalog,
        PartiallyUnavailableFilesystem(),
        scanner.settings,
        metadata_reader=fake_metadata,
    )
    partial = partial_scanner.scan_source(catalog.get_source(source.id))

    assert partial.errors == 1
    assert partial.pictures_added == 1
    assert partial.missing_marked == 0
    assert catalog.overview()["missing"] == 0
    assert catalog.overview()["folders"] == 4
    assert {row["filename"] for row in catalog.recent_added(10)} == {
        "added.jpg",
        "deleted.jpg",
        "preserved.jpg",
    }
    latest = catalog.latest_scan()
    assert latest["status"] == "partial"
    assert catalog.get_source(source.id).last_scan_status == "partial"
    assert "Incomplete source traversal" in latest["message"]

    complete = scanner.scan_source(catalog.get_source(source.id))

    assert complete.errors == 0
    assert complete.missing_marked == 1
    assert catalog.overview()["missing"] == 1
    assert {row["filename"] for row in catalog.recent_added(10)} == {
        "added.jpg",
        "preserved.jpg",
    }
    assert catalog.latest_scan()["status"] == "completed"


def test_listed_existing_file_access_error_does_not_mark_it_missing(
    tmp_path: Path,
) -> None:
    root = tmp_path / "photos"
    root.mkdir()
    deleted = root / "deleted.jpg"
    inaccessible = root / "inaccessible.jpg"
    deleted.write_bytes(b"deleted later")
    inaccessible.write_bytes(b"temporarily inaccessible")

    catalog, source, scanner = setup_scanner(tmp_path, root)
    first = scanner.scan_sources()
    assert first.pictures_added == 2

    deleted.unlink()

    class FileAccessFailureFilesystem(LocalFilesystem):
        def stat(self, path):
            if Path(path).resolve() == inaccessible.resolve():
                raise OSError("temporary SMB stat failure")
            return super().stat(path)

    failed_file_scanner = Scanner(
        catalog,
        FileAccessFailureFilesystem(),
        scanner.settings,
        metadata_reader=fake_metadata,
    )
    result = failed_file_scanner.scan_source(catalog.get_source(source.id))

    assert result.errors == 1
    assert result.missing_marked == 1
    assert catalog.overview()["missing"] == 1
    assert [row["filename"] for row in catalog.recent_added(10)] == [
        "inaccessible.jpg"
    ]
    assert catalog.latest_scan()["status"] == "completed_with_errors"


def test_slow_smb_operations_are_logged_without_failing_scan(tmp_path, monkeypatch) -> None:
    root = tmp_path / "photos"
    root.mkdir()
    (root / "image.jpg").write_bytes(b"image")
    catalog, _source, original = setup_scanner(tmp_path, root)
    messages = []
    logger = type(
        "Logger",
        (),
        {"warning": lambda self, message, *args: messages.append(message % args)},
    )()
    monkeypatch.setattr(scanner_module, "SLOW_IO_WARNING_SECONDS", 0.0)
    scanner = Scanner(
        catalog,
        LocalFilesystem(),
        original.settings,
        logger=logger,
        metadata_reader=fake_metadata,
    )

    result = scanner.scan_sources()

    assert result.errors == 0
    assert any(message.startswith("Slow directory listing:") for message in messages)
    assert any(message.startswith("Slow media inspection:") for message in messages)
