from __future__ import annotations

from pathlib import Path

from mypicsdb3.config import Settings
from mypicsdb3.db.catalog import Catalog
from mypicsdb3.db.engine import DatabaseEngine
from mypicsdb3.filesystem import LocalFilesystem
from mypicsdb3.models import MetadataResult, ScanStats
from mypicsdb3.scan_checkpoint import CHECKPOINT_FILENAME, ScanCheckpointStore
from mypicsdb3.scanner import Scanner


def fake_metadata(path, filesystem, settings, file_size):
    return MetadataResult(
        taken_at="2026-07-29 12:00:00",
        taken_source="Test metadata",
        mime_type="image/jpeg",
        caption=Path(path).name,
    )


def make_catalog(tmp_path: Path, roots):
    settings = Settings(
        profile_path=str(tmp_path / "profile"),
        database_backend="sqlite",
        extensions=("jpg",),
        batch_size=10,
    )
    catalog = Catalog(DatabaseEngine(settings))
    catalog.initialize()
    sources = catalog.sync_sources(
        [
            {"label": label, "uri": str(root)}
            for label, root in roots
        ]
    )
    for source in sources:
        catalog.set_source_enabled(source.id, True)
    return settings, catalog, sources


class TrackingFilesystem(LocalFilesystem):
    def __init__(self):
        self.listed = []

    def listdir(self, path):
        self.listed.append(Path(path).resolve())
        return super().listdir(path)


class CancelAfterCompletedFolder(ScanCheckpointStore):
    def __init__(self, settings, state):
        super().__init__(settings)
        self.state = state

    def update_source(
        self,
        source,
        scan_started_at,
        pending_folders,
        stats,
        traversal_complete,
    ):
        super().update_source(
            source,
            scan_started_at,
            pending_folders,
            stats,
            traversal_complete,
        )
        # Root is folder 1 and Album A is folder 2. Cancelling here leaves
        # Album B in the persisted pending-folder stack.
        if int(stats.folders_seen or 0) >= 2:
            self.state["cancelled"] = True


class CancelAfterCompletedSource(ScanCheckpointStore):
    def __init__(self, settings, state):
        super().__init__(settings)
        self.state = state
        self.completed = 0

    def complete_source(self, source_id, overall):
        super().complete_source(source_id, overall)
        self.completed += 1
        if self.completed == 1:
            self.state["cancelled"] = True


def test_cancelled_scan_resumes_at_next_unfinished_folder(tmp_path: Path) -> None:
    root = tmp_path / "photos"
    album_a = root / "A"
    album_b = root / "B"
    album_a.mkdir(parents=True)
    album_b.mkdir(parents=True)
    (album_a / "a.jpg").write_bytes(b"a")
    (album_b / "b.jpg").write_bytes(b"b")

    settings, catalog, _sources = make_catalog(tmp_path, [("Photos", root)])
    state = {"cancelled": False}
    first_filesystem = TrackingFilesystem()
    first = Scanner(
        catalog,
        first_filesystem,
        settings,
        metadata_reader=fake_metadata,
        cancelled=lambda: state["cancelled"],
        checkpoint_store=CancelAfterCompletedFolder(settings, state),
    ).scan_sources()

    checkpoint = Path(settings.profile_path) / CHECKPOINT_FILENAME
    assert first.cancelled is True
    assert checkpoint.exists()
    assert [row["filename"] for row in catalog.recent_added(10)] == ["a.jpg"]

    second_filesystem = TrackingFilesystem()
    second = Scanner(
        catalog,
        second_filesystem,
        settings,
        metadata_reader=fake_metadata,
    ).scan_sources()

    assert second.cancelled is False
    assert second.pictures_seen == 2
    assert {row["filename"] for row in catalog.recent_added(10)} == {
        "a.jpg",
        "b.jpg",
    }
    assert album_b.resolve() in second_filesystem.listed
    assert root.resolve() not in second_filesystem.listed
    assert album_a.resolve() not in second_filesystem.listed
    assert checkpoint.exists() is False
    assert catalog.latest_scan()["status"] == "completed"


def test_changed_scan_settings_discard_saved_checkpoint(tmp_path: Path) -> None:
    root = tmp_path / "photos"
    album_a = root / "A"
    album_b = root / "B"
    album_a.mkdir(parents=True)
    album_b.mkdir(parents=True)
    (album_a / "a.jpg").write_bytes(b"a")
    (album_b / "b.jpg").write_bytes(b"b")

    settings, catalog, _sources = make_catalog(tmp_path, [("Photos", root)])
    state = {"cancelled": False}
    Scanner(
        catalog,
        TrackingFilesystem(),
        settings,
        metadata_reader=fake_metadata,
        cancelled=lambda: state["cancelled"],
        checkpoint_store=CancelAfterCompletedFolder(settings, state),
    ).scan_sources()

    changed_settings = Settings(
        profile_path=settings.profile_path,
        database_backend="sqlite",
        extensions=("jpg", "nef"),
        batch_size=10,
    )
    filesystem = TrackingFilesystem()
    result = Scanner(
        catalog,
        filesystem,
        changed_settings,
        metadata_reader=fake_metadata,
    ).scan_sources()

    assert result.cancelled is False
    assert root.resolve() in filesystem.listed
    assert album_a.resolve() in filesystem.listed
    assert album_b.resolve() in filesystem.listed
    assert not (Path(settings.profile_path) / CHECKPOINT_FILENAME).exists()


def test_resume_skips_sources_completed_before_interruption(tmp_path: Path) -> None:
    root_a = tmp_path / "source-a"
    root_b = tmp_path / "source-b"
    root_a.mkdir()
    root_b.mkdir()
    (root_a / "a.jpg").write_bytes(b"a")
    (root_b / "b.jpg").write_bytes(b"b")

    settings, catalog, _sources = make_catalog(
        tmp_path,
        [("A source", root_a), ("B source", root_b)],
    )
    state = {"cancelled": False}
    first = Scanner(
        catalog,
        TrackingFilesystem(),
        settings,
        metadata_reader=fake_metadata,
        cancelled=lambda: state["cancelled"],
        checkpoint_store=CancelAfterCompletedSource(settings, state),
    ).scan_sources()

    assert first.cancelled is True
    assert [row["filename"] for row in catalog.recent_added(10)] == ["a.jpg"]

    filesystem = TrackingFilesystem()
    second = Scanner(
        catalog,
        filesystem,
        settings,
        metadata_reader=fake_metadata,
    ).scan_sources()

    assert second.cancelled is False
    assert second.sources_scanned == 2
    assert second.pictures_seen == 2
    assert root_a.resolve() not in filesystem.listed
    assert root_b.resolve() in filesystem.listed
    assert {row["filename"] for row in catalog.recent_added(10)} == {
        "a.jpg",
        "b.jpg",
    }
    assert not (Path(settings.profile_path) / CHECKPOINT_FILENAME).exists()


def test_resume_preserves_partial_traversal_safety_flag(tmp_path: Path) -> None:
    root = tmp_path / "photos"
    blocked = root / "A-blocked"
    readable = root / "B-readable"
    blocked.mkdir(parents=True)
    readable.mkdir(parents=True)
    (blocked / "hidden-during-failure.jpg").write_bytes(b"blocked")
    (readable / "visible.jpg").write_bytes(b"visible")

    settings, catalog, _sources = make_catalog(tmp_path, [("Photos", root)])
    state = {"cancelled": False}

    class FailingFilesystem(TrackingFilesystem):
        def listdir(self, path):
            if Path(path).resolve() == blocked.resolve():
                self.listed.append(Path(path).resolve())
                raise OSError("temporary directory failure")
            return super().listdir(path)

    first = Scanner(
        catalog,
        FailingFilesystem(),
        settings,
        metadata_reader=fake_metadata,
        cancelled=lambda: state["cancelled"],
        checkpoint_store=CancelAfterCompletedFolder(settings, state),
    ).scan_sources()
    assert first.cancelled is True

    second = Scanner(
        catalog,
        TrackingFilesystem(),
        settings,
        metadata_reader=fake_metadata,
    ).scan_sources()

    assert second.cancelled is False
    assert second.missing_marked == 0
    assert catalog.latest_scan()["status"] == "partial"
    assert "Incomplete source traversal" in catalog.latest_scan()["message"]


def test_expired_checkpoint_starts_a_new_scan_plan(tmp_path: Path) -> None:
    root = tmp_path / "photos"
    root.mkdir()
    settings, _catalog, sources = make_catalog(tmp_path, [("Photos", root)])
    source = sources[0]
    first = ScanCheckpointStore(
        settings,
        time_provider=lambda: 100.0,
        max_age_seconds=60,
    )
    overall = first.prepare(sources, ScanStats(started_at="2026-07-29 12:00:00"))
    first.begin_source(
        source,
        "2026-07-29 12:00:00",
        [(str(root), "", source.label)],
        ScanStats(sources_total=1, started_at="2026-07-29 12:00:00"),
        True,
    )

    second = ScanCheckpointStore(
        settings,
        time_provider=lambda: 161.0,
        max_age_seconds=60,
    )
    restored = second.prepare(
        sources,
        ScanStats(started_at="2026-07-29 13:00:00"),
    )

    assert overall.started_at == "2026-07-29 12:00:00"
    assert second.resumed is False
    assert second.current_source(source) is None
    assert restored.started_at == "2026-07-29 13:00:00"
    second.finish()


def test_changed_source_policy_discards_saved_checkpoint(tmp_path: Path) -> None:
    from mypicsdb3.source_scan_policy import SourceScanPolicy

    root = tmp_path / "photos"
    album_a = root / "A"
    album_b = root / "B"
    album_a.mkdir(parents=True)
    album_b.mkdir(parents=True)
    (album_a / "a.jpg").write_bytes(b"a")
    (album_b / "b.jpg").write_bytes(b"b")

    settings, catalog, sources = make_catalog(tmp_path, [("Photos", root)])
    state = {"cancelled": False}
    Scanner(
        catalog,
        TrackingFilesystem(),
        settings,
        metadata_reader=fake_metadata,
        cancelled=lambda: state["cancelled"],
        checkpoint_store=CancelAfterCompletedFolder(settings, state),
    ).scan_sources()

    source = sources[0]
    catalog.set_source_scan_policy(
        source.id,
        SourceScanPolicy(
            recursive=False,
            include_videos=False,
            picture_extensions=("jpg",),
            video_extensions=("mp4",),
            exclude_fragments=(),
            exclude_hidden=True,
        ),
    )
    filesystem = TrackingFilesystem()
    result = Scanner(
        catalog,
        filesystem,
        settings,
        metadata_reader=fake_metadata,
    ).scan_sources()

    assert result.cancelled is False
    assert root.resolve() in filesystem.listed
    assert album_a.resolve() not in filesystem.listed
    assert album_b.resolve() not in filesystem.listed
    assert not (Path(settings.profile_path) / CHECKPOINT_FILENAME).exists()

def test_checkpoint_preserves_observability_counters(tmp_path: Path) -> None:
    root = tmp_path / "photos-observability"
    root.mkdir()
    settings, _catalog, sources = make_catalog(tmp_path, [("Photos", root)])
    source = sources[0]
    store = ScanCheckpointStore(settings, time_provider=lambda: 100.0)
    overall = store.prepare(sources, ScanStats(started_at="2026-08-16 12:00:00"))
    assert overall.metadata_reads == 0

    stats = ScanStats(
        sources_total=1,
        pictures_seen=12,
        pictures_unchanged=8,
        metadata_reads=4,
        directory_list_seconds=1.25,
        file_stat_seconds=2.5,
        metadata_read_seconds=3.75,
        started_at="2026-08-16 12:00:00",
    )
    pending = [(str(root), "", source.label)]
    store.begin_source(source, stats.started_at, pending, stats, True)

    restored_store = ScanCheckpointStore(settings, time_provider=lambda: 101.0)
    restored_store.prepare(sources, ScanStats(started_at="later"))
    restored = restored_store.restore_source(source)
    assert restored is not None
    restored_stats = restored[2]
    assert restored_stats.metadata_reads == 4
    assert restored_stats.directory_list_seconds == 1.25
    assert restored_stats.file_stat_seconds == 2.5
    assert restored_stats.metadata_read_seconds == 3.75
