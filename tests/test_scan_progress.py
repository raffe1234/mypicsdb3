from __future__ import annotations

from dataclasses import replace
from types import SimpleNamespace

import pytest

from mypicsdb3.filesystem import LocalFilesystem
from mypicsdb3.models import ScanStats
from mypicsdb3.scan_progress import ScanCountHistory, ScanProgressDisplay
from mypicsdb3.scanner import Scanner
from test_scanner import setup_scanner, fake_metadata


def test_estimate_counts_unchanged_and_new_files_after_processing(tmp_path):
    root = tmp_path / "photos"
    root.mkdir()
    for i in range(3):
        (root / ("%d.jpg" % i)).write_bytes(b"image")
    catalog, source, scanner = setup_scanner(tmp_path, root)
    first = scanner.scan_sources()
    assert first.estimated_total is None
    (root / "3.jpg").write_bytes(b"new")
    reports = []
    scanner.progress = lambda source, path, stats: reports.append((path, stats))
    second = scanner.scan_sources()
    assert second.estimated_total == 3
    assert second.pictures_seen == 4
    assert second.pictures_unchanged == 3
    assert second.pictures_added == 1
    assert reports[-1][1].pictures_seen == 4
    assert reports[-1][1].pictures_added == 1
    policy = scanner._effective_source_policy(source)
    assert ScanCountHistory(catalog).load(source, policy) == 4


def test_history_invalidates_changed_scope_and_source_path(tmp_path):
    root = tmp_path / "photos"
    root.mkdir()
    (root / "image.jpg").write_bytes(b"image")
    catalog, source, scanner = setup_scanner(tmp_path, root)
    scanner.scan_sources()
    history = ScanCountHistory(catalog)
    policy = scanner._effective_source_policy(source)
    assert history.load(source, policy) == 1
    assert history.load(source, replace(policy, recursive=False)) is None
    assert history.load(source, replace(policy, exclude_hidden=not policy.exclude_hidden)) is None
    assert history.load(source, replace(policy, include_videos=True)) is None
    assert history.load(replace(source, uri=str(root / "other")), policy) is None


@pytest.mark.parametrize("failure", ["cancel", "list", "stat", "unavailable"])
def test_incomplete_scan_preserves_good_history(tmp_path, failure):
    root = tmp_path / "photos"
    root.mkdir()
    (root / "one.jpg").write_bytes(b"image")
    catalog, source, scanner = setup_scanner(tmp_path, root)
    scanner.scan_sources()
    key = ScanCountHistory.key(source)
    original = catalog.meta_value(key)
    (root / "two.jpg").write_bytes(b"image")
    stop = [False]

    class FailingFilesystem(LocalFilesystem):
        def listdir(self, path):
            if failure == "list":
                raise OSError("unreadable directory")
            return super().listdir(path)

        def stat(self, path):
            if failure == "stat":
                raise OSError("cannot stat")
            return super().stat(path)

        def exists(self, path):
            if failure == "unavailable":
                return False
            return super().exists(path)

    def progress(source, path, stats):
        if failure == "cancel" and stats.pictures_seen:
            stop[0] = True

    scanner = Scanner(catalog, FailingFilesystem(), scanner.settings,
                      metadata_reader=fake_metadata, progress=progress,
                      cancelled=lambda: stop[0])
    result = scanner.scan_sources()
    assert result.cancelled or result.errors
    assert catalog.meta_value(key) == original


def test_selected_sources_and_resume_use_aggregate_counters_without_double_counting(tmp_path):
    root = tmp_path / "photos"
    root.mkdir()
    (root / "one.jpg").write_bytes(b"image")
    catalog, first_source, scanner = setup_scanner(tmp_path, root)
    second_root = tmp_path / "second"
    second_root.mkdir()
    (second_root / "two.jpg").write_bytes(b"image")
    sources = catalog.sync_sources([
        {"label": "Photos", "uri": str(root)},
        {"label": "Second", "uri": str(second_root)},
    ])
    second_source = next(s for s in sources if s.id != first_source.id)
    catalog.set_source_enabled(second_source.id, True)
    scanner.scan_sources()
    selected = scanner.scan_sources([first_source.id])
    assert selected.estimated_total == 1
    stop = [False]

    def progress(source, path, stats):
        if source.id == second_source.id:
            stop[0] = True

    interrupted = Scanner(catalog, LocalFilesystem(), scanner.settings,
                          metadata_reader=fake_metadata, progress=progress,
                          cancelled=lambda: stop[0])
    assert interrupted.scan_sources().cancelled
    starts, reports = [], []
    resumed = Scanner(catalog, LocalFilesystem(), scanner.settings,
                      metadata_reader=fake_metadata, started=starts.append,
                      progress=lambda source, path, stats: reports.append(stats))
    result = resumed.scan_sources()
    assert starts[0].pictures_seen == 1
    assert starts[0].estimated_total == 2
    assert reports[-1].pictures_seen == 2
    assert reports[-1].estimated_total == 2
    assert result.pictures_seen == 2
    assert not result.cancelled


def test_missing_source_reference_keeps_whole_scan_estimate_unknown(tmp_path):
    root = tmp_path / "photos"
    root.mkdir()
    catalog, first_source, scanner = setup_scanner(tmp_path, root)
    scanner.scan_sources()
    second_root = tmp_path / "second"
    second_root.mkdir()
    sources = catalog.sync_sources([
        {"label": "Photos", "uri": str(root)},
        {"label": "Second", "uri": str(second_root)},
    ])
    for source in sources:
        catalog.set_source_enabled(source.id, True)
    assert scanner.scan_sources().estimated_total is None
    assert scanner.scan_sources().estimated_total == 0


def test_history_errors_do_not_stop_indexing(tmp_path, monkeypatch):
    root = tmp_path / "photos"
    root.mkdir()
    (root / "image.jpg").write_bytes(b"image")
    catalog, source, scanner = setup_scanner(tmp_path, root)
    key = ScanCountHistory.key(source)
    catalog.set_meta_value(key, "not JSON")
    assert ScanCountHistory(catalog).load(source, scanner._effective_source_policy(source)) is None
    setter = catalog.set_meta_value

    def broken_history(name, value):
        if name == key:
            raise OSError("history unavailable")
        setter(name, value)

    monkeypatch.setattr(catalog, "set_meta_value", broken_history)
    result = scanner.scan_sources()
    assert result.pictures_added == 1
    assert result.errors == 0


def test_eta_excludes_playback_pause_and_previous_session_work():
    now = [100.0]
    display = ScanProgressDisplay(lambda: now[0])
    display.start(ScanStats(pictures_seen=500))
    stats = ScanStats(pictures_seen=510, estimated_total=1000)
    now[0] = 110.0
    percent, eta, elapsed = display.values(stats)
    assert (percent, eta, elapsed) == (51, 490, 10)
    display.pause()
    now[0] = 3710.0
    assert display.values(stats)[1] is None
    display.resume()
    assert display.values(stats) == (51, 490, 10)
    now[0] += 10
    stats.pictures_seen = 520
    assert display.values(stats) == (52, 480, 20)


@pytest.mark.parametrize("seen,total,expected", [
    (0, None, None), (50, None, None), (0, 0, None),
    (10, 100, 10), (99, 100, 99), (100, 100, None), (150, 100, None),
])
def test_percentage_never_claims_completion_during_traversal(seen, total, expected):
    now = [0.0]
    display = ScanProgressDisplay(lambda: now[0])
    display.start(ScanStats())
    now[0] = 30
    stats = ScanStats(pictures_seen=seen, estimated_total=total)
    percent, eta, elapsed = display.values(stats)
    assert percent == expected
    if expected is None:
        assert eta is None
    value, message = display.render(SimpleNamespace(label="Photos"), "/photos/", stats,
                                    lambda _, fallback: fallback)
    assert 0 <= value < 100
    if total and seen >= total:
        assert "still scanning" in message
        assert "time left unknown" in message


def test_eta_waits_for_useful_current_session_sample():
    now = [0.0]
    display = ScanProgressDisplay(lambda: now[0])
    display.start(ScanStats())
    now[0] = 1
    assert display.values(ScanStats(pictures_seen=100, estimated_total=1000))[1] is None
    now[0] = 30
    assert display.values(ScanStats(pictures_seen=1, estimated_total=1000))[1] is None


def test_cancellation_during_listing_keeps_folder_pending_for_resume(tmp_path):
    root = tmp_path / "photos"
    root.mkdir()
    (root / "image.jpg").write_bytes(b"image")
    catalog, source, original = setup_scanner(tmp_path, root)
    from mypicsdb3.scanner import ScanCancelled

    class CancelListing(LocalFilesystem):
        def listdir(self, path):
            raise ScanCancelled()

    scanner = Scanner(catalog, CancelListing(), original.settings,
                      metadata_reader=fake_metadata)
    result = scanner.scan_sources()
    assert result.cancelled
    assert catalog.meta_value(ScanCountHistory.key(source)) is None
    resumed = Scanner(catalog, LocalFilesystem(), original.settings,
                      metadata_reader=fake_metadata)
    result = resumed.scan_sources()
    assert result.pictures_seen == 1
    assert result.pictures_added == 1
    assert not result.cancelled


def test_removed_files_lower_reference_only_after_complete_scan(tmp_path):
    root = tmp_path / "photos"
    root.mkdir()
    (root / "one.jpg").write_bytes(b"image")
    (root / "two.jpg").write_bytes(b"image")
    catalog, source, scanner = setup_scanner(tmp_path, root)
    scanner.scan_sources()
    (root / "two.jpg").unlink()
    result = scanner.scan_sources()
    assert result.estimated_total == 2
    assert result.pictures_seen == 1
    assert result.missing_marked == 1
    assert ScanCountHistory(catalog).load(source, scanner._effective_source_policy(source)) == 1
