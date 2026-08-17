from __future__ import annotations

from types import SimpleNamespace

import pytest

from mypicsdb3 import metadata_refresh
from mypicsdb3.metadata_refresh import (
    MetadataRefreshBusy,
    MetadataRefresher,
)
from mypicsdb3.models import FileStat, MetadataResult


class FakeFilesystem:
    def stat(self, path):
        assert path.startswith("smb://server/photos/")
        return FileStat(size=456, mtime=1720000000.0)


class FakeCatalog:
    def __init__(self):
        self.locked = False
        self.recovered = []
        self.refreshed = []
        self.folder_summaries = []
        self.meta = {}
        self.rows = {
            1: {
                "id": 1,
                "source_id": 7,
                "folder_id": 2,
                "uri": "smb://server/photos/one.jpg",
                "filename": "one.jpg",
                "extension": "jpg",
                "media_type": "picture",
                "discovered_at": "2026-01-01 00:00:00",
                "last_seen_at": "2026-08-17 08:00:00",
                "thumb_uri": "smb://server/photos/one.jpg",
                "camera_make": None,
                "camera_model": None,
                "gps_latitude": None,
                "gps_longitude": None,
                "city": None,
                "country": None,
            },
            2: {
                "id": 2,
                "source_id": 7,
                "folder_id": 2,
                "uri": "smb://server/photos/two.jpg",
                "filename": "two.jpg",
                "extension": "jpg",
                "media_type": "picture",
                "discovered_at": "2026-01-01 00:00:00",
                "last_seen_at": "2026-08-17 08:00:00",
                "thumb_uri": "smb://server/photos/two.jpg",
                "camera_make": None,
                "camera_model": None,
                "gps_latitude": None,
                "gps_longitude": None,
                "city": None,
                "country": None,
            },
        }

    def recover_stale_local_lock(self, name, owner):
        self.recovered.append((name, owner))
        return None

    def acquire_lock(self, name, owner, ttl):
        if self.locked:
            return False
        self.locked = True
        return True

    def refresh_lock(self, name, owner, ttl):
        return self.locked

    def release_lock(self, name, owner):
        self.locked = False

    def list_metadata_mapping_overrides(self):
        return []

    def picture_by_id(self, picture_id):
        row = self.rows.get(int(picture_id))
        return dict(row) if row else None

    def picture_ids_in_folder(self, folder_id):
        assert int(folder_id) == 2
        return [1, 2]

    def metadata_refresh_picture_horizon(self, max_picture_id=None):
        ids = [
            picture_id
            for picture_id, row in self.rows.items()
            if row.get("media_type") == "picture"
            and (max_picture_id is None or picture_id <= int(max_picture_id))
        ]
        return (len(ids), max(ids) if ids else 0)

    def picture_ids_for_metadata_refresh(self, after_id, max_picture_id, limit=200):
        ids = [
            picture_id
            for picture_id, row in sorted(self.rows.items())
            if row.get("media_type") == "picture"
            and picture_id > int(after_id)
            and picture_id <= int(max_picture_id)
        ]
        return ids[: int(limit)]

    def refresh_picture_record(self, picture_id, record, keywords):
        if int(picture_id) not in self.rows:
            return False
        self.refreshed.append((int(picture_id), dict(record), list(keywords)))
        return True

    def refresh_folder_summary(self, folder_id):
        self.folder_summaries.append(int(folder_id))

    def meta_value(self, key):
        return self.meta.get(str(key))

    def set_meta_value(self, key, value):
        self.meta[str(key)] = str(value)


def settings(profile_path=""):
    return SimpleNamespace(
        profile_path=str(profile_path),
        database_backend="sqlite",
        batch_size=100,
        read_xmp=True,
        read_iptc=True,
        store_gps=True,
        reverse_geocoding_endpoint="https://nominatim.openstreetmap.org",
        metadata_prefix_mb=2,
        deep_metadata_max_mb=64,
    )


def fresh_result():
    return MetadataResult(
        taken_at="2024-05-06 07:08:09",
        taken_source="EXIF DateTimeOriginal",
        width=4000,
        height=3000,
        orientation=1,
        mime_type="image/jpeg",
        camera_make="Samsung",
        camera_model="SM-S921B",
        rating=4,
        gps_latitude=59.3293,
        gps_longitude=18.0686,
        keywords=["Family"],
        location={"city": "Stockholm", "country": "Sweden"},
        caption="Test",
        metadata_hash="fresh-hash",
    )


def test_inspect_picture_reads_fresh_metadata_without_writing(monkeypatch) -> None:
    catalog = FakeCatalog()

    def fake_extract(path, filesystem, cfg, file_size, mapping_rules=(), diagnostics=None):
        assert path.endswith("one.jpg")
        assert file_size == 456
        diagnostics.update({"exif_tag_count": 42, "exif_make": "Samsung"})
        return fresh_result()

    monkeypatch.setattr(metadata_refresh, "extract_metadata", fake_extract)
    inspection = MetadataRefresher(catalog, FakeFilesystem(), settings()).inspect_picture(1)

    assert inspection.row["camera_make"] is None
    assert inspection.fresh.camera_make == "Samsung"
    assert inspection.source_details["exif_tag_count"] == 42
    assert catalog.refreshed == []
    assert catalog.locked is False


def test_refresh_picture_replaces_catalogue_metadata_and_preserves_scan_seen_time(monkeypatch) -> None:
    catalog = FakeCatalog()

    def fake_extract(path, filesystem, cfg, file_size, mapping_rules=(), diagnostics=None):
        diagnostics.update({"exif_tag_count": 42})
        return fresh_result()

    monkeypatch.setattr(metadata_refresh, "extract_metadata", fake_extract)
    inspection = MetadataRefresher(catalog, FakeFilesystem(), settings()).refresh_picture(1)

    assert inspection.fresh.camera_model == "SM-S921B"
    assert len(catalog.refreshed) == 1
    picture_id, record, keywords = catalog.refreshed[0]
    assert picture_id == 1
    assert record["camera_make"] == "Samsung"
    assert record["camera_model"] == "SM-S921B"
    assert record["gps_latitude"] == 59.3293
    assert record["gps_longitude"] == 18.0686
    assert record["city"] == "Stockholm"
    assert record["country"] == "Sweden"
    assert record["last_seen_at"] == "2026-08-17 08:00:00"
    assert record["metadata_index_hash"]
    assert keywords == ["Family"]
    assert catalog.folder_summaries == [2]
    assert catalog.locked is False


def test_refresh_folder_is_exact_folder_serial_and_cancellable(monkeypatch) -> None:
    catalog = FakeCatalog()

    def fake_extract(path, filesystem, cfg, file_size, mapping_rules=(), diagnostics=None):
        return fresh_result()

    monkeypatch.setattr(metadata_refresh, "extract_metadata", fake_extract)
    progress_calls = []

    def cancelled():
        return len(progress_calls) >= 1

    stats = MetadataRefresher(catalog, FakeFilesystem(), settings()).refresh_folder(
        2,
        cancelled=cancelled,
        progress=lambda index, total, filename: progress_calls.append((index, total, filename)),
    )

    assert stats.requested == 2
    assert stats.refreshed == 1
    assert stats.failed == 0
    assert [item[0] for item in catalog.refreshed] == [1]
    assert progress_calls == [(1, 2, "one.jpg")]
    assert catalog.folder_summaries == [2]
    assert catalog.locked is False


def test_refresh_refuses_to_run_when_catalogue_writer_lock_is_busy() -> None:
    catalog = FakeCatalog()
    catalog.locked = True
    refresher = MetadataRefresher(catalog, FakeFilesystem(), settings())

    with pytest.raises(MetadataRefreshBusy):
        refresher.refresh_picture(1)

def test_refresh_preserves_online_enrichment_when_embedded_location_is_missing(monkeypatch) -> None:
    from mypicsdb3.geocoding import ResolvedLocation, save_location_enrichment

    catalog = FakeCatalog()
    save_location_enrichment(
        catalog,
        "smb://server/photos/one.jpg",
        ResolvedLocation(
            country="Spain",
            state="Comunitat Valenciana",
            city="Benidorm",
            sublocation="Levante",
            attribution="Data © OpenStreetMap contributors",
        ),
    )

    def fake_extract(path, filesystem, cfg, file_size, mapping_rules=(), diagnostics=None):
        result = fresh_result()
        result.location = {}
        return result

    monkeypatch.setattr(metadata_refresh, "extract_metadata", fake_extract)
    MetadataRefresher(catalog, FakeFilesystem(), settings()).refresh_picture(1)

    _picture_id, record, _keywords = catalog.refreshed[-1]
    assert record["country"] == "Spain"
    assert record["state"] == "Comunitat Valenciana"
    assert record["city"] == "Benidorm"
    assert record["sublocation"] == "Levante"


def test_refresh_all_is_serial_cancellable_and_resumes_from_local_checkpoint(monkeypatch, tmp_path) -> None:
    catalog = FakeCatalog()

    def fake_extract(path, filesystem, cfg, file_size, mapping_rules=(), diagnostics=None):
        return fresh_result()

    monkeypatch.setattr(metadata_refresh, "extract_metadata", fake_extract)
    progress_calls = []
    refresher = MetadataRefresher(catalog, FakeFilesystem(), settings(tmp_path))

    first = refresher.refresh_all(
        cancelled=lambda: len(progress_calls) >= 1,
        progress=lambda done, total, filename: progress_calls.append((done, total, filename)),
    )

    assert first.completed is False
    assert first.processed == 1
    assert first.refreshed == 1
    assert progress_calls == [(1, 2, "one.jpg")]
    checkpoint = refresher.all_refresh_checkpoint()
    assert checkpoint is not None
    assert checkpoint["last_picture_id"] == 1
    assert checkpoint["processed"] == 1

    resumed_calls = []
    second = MetadataRefresher(
        catalog, FakeFilesystem(), settings(tmp_path)
    ).refresh_all(
        cancelled=lambda: False,
        progress=lambda done, total, filename: resumed_calls.append((done, total, filename)),
    )

    assert second.completed is True
    assert second.resumed is True
    assert second.processed == 2
    assert second.refreshed == 2
    assert resumed_calls == [(2, 2, "two.jpg")]
    assert refresher.all_refresh_checkpoint() is None
    assert [item[0] for item in catalog.refreshed] == [1, 2]


def test_refresh_all_restart_discards_saved_checkpoint(monkeypatch, tmp_path) -> None:
    catalog = FakeCatalog()
    monkeypatch.setattr(
        metadata_refresh,
        "extract_metadata",
        lambda path, filesystem, cfg, file_size, mapping_rules=(), diagnostics=None: fresh_result(),
    )
    refresher = MetadataRefresher(catalog, FakeFilesystem(), settings(tmp_path))
    calls = []
    refresher.refresh_all(
        cancelled=lambda: len(calls) >= 1,
        progress=lambda done, total, filename: calls.append(done),
    )
    assert refresher.all_refresh_checkpoint() is not None

    catalog.refreshed.clear()
    stats = refresher.refresh_all(cancelled=lambda: False, restart=True)
    assert stats.completed is True
    assert stats.resumed is False
    assert [item[0] for item in catalog.refreshed] == [1, 2]


def test_refresh_reuses_existing_coordinate_cache_without_online_lookup(monkeypatch) -> None:
    from mypicsdb3.geocoding import ResolvedLocation, load_location_enrichment

    catalog = FakeCatalog()
    cached = ResolvedLocation(
        country="Spain",
        state="Comunitat Valenciana",
        city="Benidorm",
        sublocation="Levante",
        provider="Nominatim / OpenStreetMap",
        from_cache=True,
    )

    def fake_extract(path, filesystem, cfg, file_size, mapping_rules=(), diagnostics=None):
        result = fresh_result()
        result.location = {}
        return result

    monkeypatch.setattr(metadata_refresh, "extract_metadata", fake_extract)
    monkeypatch.setattr(
        metadata_refresh,
        "load_cached_reverse_geocoding",
        lambda *args, **kwargs: cached,
    )

    MetadataRefresher(catalog, FakeFilesystem(), settings()).refresh_picture(1)

    _picture_id, record, _keywords = catalog.refreshed[-1]
    assert record["country"] == "Spain"
    assert record["state"] == "Comunitat Valenciana"
    assert record["city"] == "Benidorm"
    stored = load_location_enrichment(catalog, "smb://server/photos/one.jpg")
    assert stored is not None
    assert stored.city == "Benidorm"
