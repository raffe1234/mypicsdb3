from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace

import mypicsdb3.service_loop as service_loop
from mypicsdb3.service_loop import ServiceLoop


class FakeLog:
    def __init__(self):
        self.messages = []

    def info(self, message, *args):
        self.messages.append(("info", message % args if args else message))

    def warning(self, message, *args):
        self.messages.append(("warning", message % args if args else message))

    def error(self, message, *args):
        self.messages.append(("error", message % args if args else message))

    def debug(self, message, *args):
        self.messages.append(("debug", message % args if args else message))


class FakeMonitor:
    def __init__(self):
        self.aborted = False

    def abortRequested(self):
        return self.aborted

    def waitForAbort(self, _timeout):
        return self.aborted


class FakeProgressDialog:
    def __init__(self):
        self.updates = []
        self.closed = False

    def update(self, percent, heading, message):
        self.updates.append((percent, heading, message))

    def close(self):
        self.closed = True


class FakeCatalog:
    def __init__(self):
        self.synced = []
        self.initialized = False

    def initialize(self):
        self.initialized = True

    def sync_sources(self, sources):
        self.synced = list(sources)


def test_initial_scan_delay_preserves_24h_cadence_across_service_restart(tmp_path) -> None:
    monitor = FakeMonitor()
    kodi = FakeKodi(monitor)
    now = datetime(2026, 8, 17, 10, 0, tzinfo=timezone.utc)
    loop = ServiceLoop(
        kodi,
        utcnow_provider=lambda: now,
        monitor=monitor,
    )
    settings = SimpleNamespace(
        startup_delay_seconds=60,
        scan_interval_hours=24,
        profile_path=str(tmp_path),
    )

    class CatalogWithLastScan:
        def meta_value(self, key):
            assert key == service_loop.LAST_COMPLETE_SCAN_META_KEY
            return (now - timedelta(hours=2)).strftime("%Y-%m-%d %H:%M:%S.%f")

    delay = loop._initial_scan_delay(settings, CatalogWithLastScan())

    assert delay == 22 * 3600
    assert any(
        level == "info" and "cadence preserved across restart" in message
        for level, message in kodi.log.messages
    )


def test_initial_scan_delay_resumes_local_checkpoint_before_normal_interval(tmp_path) -> None:
    monitor = FakeMonitor()
    kodi = FakeKodi(monitor)
    now = datetime(2026, 8, 17, 10, 0, tzinfo=timezone.utc)
    loop = ServiceLoop(kodi, utcnow_provider=lambda: now, monitor=monitor)
    settings = SimpleNamespace(
        startup_delay_seconds=90,
        scan_interval_hours=24,
        profile_path=str(tmp_path),
    )
    (tmp_path / service_loop.CHECKPOINT_FILENAME).write_text("{}", encoding="utf-8")

    class CatalogWithLastScan:
        def meta_value(self, _key):
            return (now - timedelta(hours=1)).strftime("%Y-%m-%d %H:%M:%S.%f")

    assert loop._initial_scan_delay(settings, CatalogWithLastScan()) == 90


class FakeKodi:
    profile_path = "/tmp/mypicsdb3"

    def __init__(self, monitor):
        self.monitor = monitor
        self.log = FakeLog()
        self.dialog = FakeProgressDialog()
        self.dialogs = [self.dialog]
        self.scan_events = []
        self.cancel_requested = False
        self.playing = False
        self.invalidations = []
        self.random_invalidations = []
        self.settings = SimpleNamespace(
            auto_scan=True,
            pause_during_playback=False,
            startup_delay_seconds=0,
            scan_interval_hours=24,
            random_home_refresh_hours=2,
        )

    def abort_monitor(self):
        return self.monitor

    def refresh_settings(self):
        return self.settings

    def kodi_picture_sources(self):
        return []

    def refresh_date_sensitive_views(self):
        return True

    def mixed_slideshow_active(self):
        return False

    def is_playing(self):
        return self.playing

    def localize(self, _string_id, fallback):
        return fallback

    def begin_scan_status(self, token, kind):
        self.scan_events.append(("begin", token, kind))

    def update_scan_status(
        self,
        token,
        source,
        path,
        pictures_seen,
        pictures_unchanged=0,
        metadata_reads=0,
        pictures_added=0,
        pictures_updated=0,
        errors=0,
    ):
        self.scan_events.append(
            (
                "progress",
                token,
                source,
                path,
                pictures_seen,
                pictures_unchanged,
                metadata_reads,
                pictures_added,
                pictures_updated,
                errors,
            )
        )

    def finish_scan_status(self, token):
        self.scan_events.append(("finish", token))

    def scan_cancel_requested(self, _token):
        return self.cancel_requested

    def invalidate_home_widgets(self, reason):
        self.invalidations.append(reason)
        return len(self.invalidations)

    def invalidate_random_home_widgets(self, reason):
        self.random_invalidations.append(reason)
        return len(self.random_invalidations)

    def create_background_progress(self, heading, message):
        if self.dialog.closed:
            self.dialog = FakeProgressDialog()
            self.dialogs.append(self.dialog)
        self.scan_events.append(("dialog", heading, message))
        return self.dialog


class FakeEngine:
    def __init__(self, _settings, _log):
        pass


def test_random_home_refresh_is_scheduled_changed_and_repeated() -> None:
    monitor = FakeMonitor()
    kodi = FakeKodi(monitor)
    loop = ServiceLoop(kodi, monitor=monitor)

    loop._maintain_random_home_refresh(kodi.settings, 100.0)
    assert loop.next_random_home_refresh_at == 7300.0
    assert kodi.random_invalidations == []

    kodi.settings.random_home_refresh_hours = 4
    loop._maintain_random_home_refresh(kodi.settings, 200.0)
    assert loop.next_random_home_refresh_at == 14600.0
    assert kodi.random_invalidations == ["random home refresh interval changed"]

    loop._maintain_random_home_refresh(kodi.settings, 14599.0)
    assert kodi.random_invalidations == ["random home refresh interval changed"]

    loop._maintain_random_home_refresh(kodi.settings, 14600.0)
    assert loop.next_random_home_refresh_at == 29000.0
    assert kodi.random_invalidations == [
        "random home refresh interval changed",
        "scheduled random home refresh",
    ]


def test_automatic_scan_publishes_progress_and_closes_dialog(monkeypatch) -> None:
    monitor = FakeMonitor()
    kodi = FakeKodi(monitor)
    initial_catalog = FakeCatalog()
    scan_catalog = FakeCatalog()
    loop = ServiceLoop(
        kodi,
        date_provider=lambda: date(2026, 7, 29),
        monotonic_provider=lambda: 100.0,
        monitor=monitor,
    )
    loop._runtime_parts = lambda: (kodi.settings, initial_catalog, object())

    monkeypatch.setattr(service_loop, "DatabaseEngine", FakeEngine)
    monkeypatch.setattr(service_loop, "Catalog", lambda _engine, _log: scan_catalog)

    class FakeScanner:
        def __init__(
            self,
            _catalog,
            _filesystem,
            _settings,
            _logger,
            cancelled,
            progress,
            started,
        ):
            self.cancelled = cancelled
            self.progress = progress
            self.started = started

        def scan_sources(self):
            assert self.cancelled() is False
            self.started(SimpleNamespace())
            self.progress(
                SimpleNamespace(label="NikonD7000"),
                "smb://nas/photos/image.nef",
                SimpleNamespace(
                    pictures_seen=100,
                    pictures_unchanged=60,
                    metadata_reads=40,
                    pictures_added=25,
                    pictures_updated=15,
                    errors=1,
                ),
            )
            monitor.aborted = True
            return SimpleNamespace(cancelled=False, pictures_seen=100, errors=0)

    monkeypatch.setattr(service_loop, "Scanner", FakeScanner)

    loop.run()

    assert initial_catalog.synced == []
    assert scan_catalog.initialized is True
    assert kodi.scan_events[0][0] == "begin"
    assert ("dialog", "MyPicsDB 3", "Automatic scan") in kodi.scan_events
    assert any(
        event[0] == "progress"
        and event[4:] == (100, 60, 40, 25, 15, 1)
        for event in kodi.scan_events
    )
    assert kodi.scan_events[-1][0] == "finish"
    assert kodi.dialog.closed is True
    assert "Pictures found: 100" in kodi.dialog.updates[-1][2]
    assert ("info", "Automatic scan finished: 100 pictures, 0 errors") in kodi.log.messages


def test_overlapping_automatic_scan_is_logged_as_skipped(monkeypatch) -> None:
    monitor = FakeMonitor()
    kodi = FakeKodi(monitor)
    initial_catalog = FakeCatalog()
    scan_catalog = FakeCatalog()
    loop = ServiceLoop(
        kodi,
        date_provider=lambda: date(2026, 7, 29),
        monotonic_provider=lambda: 100.0,
        monitor=monitor,
    )
    loop._runtime_parts = lambda: (kodi.settings, initial_catalog, object())

    monkeypatch.setattr(service_loop, "DatabaseEngine", FakeEngine)
    monkeypatch.setattr(service_loop, "Catalog", lambda _engine, _log: scan_catalog)

    class BusyScanner:
        def __init__(self, *_args, **_kwargs):
            pass

        def scan_sources(self):
            monitor.aborted = True
            raise service_loop.ScanAlreadyRunning("Another scan is already running")

    monkeypatch.setattr(service_loop, "Scanner", BusyScanner)

    loop.run()

    assert (
        "info",
        "Automatic scan skipped: another scan is already running; retrying in 60 seconds",
    ) in kodi.log.messages
    assert not any(level == "error" for level, _message in kodi.log.messages)
    assert kodi.scan_events == []


def test_automatic_scan_busy_lock_retries_before_normal_interval(monkeypatch) -> None:
    attempts = {"count": 0}

    class RetryMonitor(FakeMonitor):
        def waitForAbort(self, _timeout):
            if attempts["count"] >= 2:
                self.aborted = True
            return self.aborted

    class Clock:
        def __init__(self):
            self.value = -30.0

        def __call__(self):
            self.value += 30.0
            return self.value

    monitor = RetryMonitor()
    kodi = FakeKodi(monitor)
    initial_catalog = FakeCatalog()
    scan_catalog = FakeCatalog()
    loop = ServiceLoop(
        kodi,
        date_provider=lambda: date(2026, 7, 29),
        monotonic_provider=Clock(),
        monitor=monitor,
    )
    loop._runtime_parts = lambda: (kodi.settings, initial_catalog, object())

    monkeypatch.setattr(service_loop, "DatabaseEngine", FakeEngine)
    monkeypatch.setattr(service_loop, "Catalog", lambda _engine, _log: scan_catalog)

    class BusyScanner:
        def __init__(self, *_args, **_kwargs):
            pass

        def scan_sources(self):
            attempts["count"] += 1
            raise service_loop.ScanAlreadyRunning("Another scan is already running")

    monkeypatch.setattr(service_loop, "Scanner", BusyScanner)

    loop.run()

    assert attempts["count"] == 2
    assert sum(
        1
        for level, message in kodi.log.messages
        if level == "info" and "retrying in 60 seconds" in message
    ) == 2


def test_automatic_scan_logs_service_interruption_separately(monkeypatch) -> None:
    monitor = FakeMonitor()
    kodi = FakeKodi(monitor)
    initial_catalog = FakeCatalog()
    scan_catalog = FakeCatalog()
    loop = ServiceLoop(
        kodi,
        date_provider=lambda: date(2026, 7, 29),
        monotonic_provider=lambda: 100.0,
        monitor=monitor,
    )
    loop._runtime_parts = lambda: (kodi.settings, initial_catalog, object())

    monkeypatch.setattr(service_loop, "DatabaseEngine", FakeEngine)
    monkeypatch.setattr(service_loop, "Catalog", lambda _engine, _log: scan_catalog)

    class InterruptedScanner:
        def __init__(
            self,
            _catalog,
            _filesystem,
            _settings,
            _logger,
            cancelled,
            progress,
            started,
        ):
            self.cancelled = cancelled
            self.started = started

        def scan_sources(self):
            self.started(SimpleNamespace())
            monitor.aborted = True
            assert self.cancelled() is True
            return SimpleNamespace(cancelled=True, pictures_seen=25, errors=0)

    monkeypatch.setattr(service_loop, "Scanner", InterruptedScanner)

    loop.run()

    assert (
        "info",
        "Automatic scan interrupted because Kodi or the add-on service stopped",
    ) in kodi.log.messages
    assert not any(
        message == "Automatic scan cancelled by user"
        for _level, message in kodi.log.messages
    )


def test_automatic_scan_logs_user_requested_cancellation(monkeypatch) -> None:
    monitor = FakeMonitor()
    kodi = FakeKodi(monitor)
    kodi.cancel_requested = True
    initial_catalog = FakeCatalog()
    scan_catalog = FakeCatalog()
    loop = ServiceLoop(
        kodi,
        date_provider=lambda: date(2026, 7, 29),
        monotonic_provider=lambda: 100.0,
        monitor=monitor,
    )
    loop._runtime_parts = lambda: (kodi.settings, initial_catalog, object())

    monkeypatch.setattr(service_loop, "DatabaseEngine", FakeEngine)
    monkeypatch.setattr(service_loop, "Catalog", lambda _engine, _log: scan_catalog)

    class CancelledScanner:
        def __init__(
            self,
            _catalog,
            _filesystem,
            _settings,
            _logger,
            cancelled,
            progress,
            started,
        ):
            self.cancelled = cancelled
            self.started = started

        def scan_sources(self):
            self.started(SimpleNamespace())
            assert self.cancelled() is True
            monitor.aborted = True
            return SimpleNamespace(cancelled=True, pictures_seen=25, errors=0)

    monkeypatch.setattr(service_loop, "Scanner", CancelledScanner)

    loop.run()

    assert ("info", "Automatic scan cancelled by user") in kodi.log.messages

def test_automatic_scan_hides_progress_during_playback(monkeypatch) -> None:
    monitor = FakeMonitor()
    kodi = FakeKodi(monitor)
    kodi.playing = True
    initial_catalog = FakeCatalog()
    scan_catalog = FakeCatalog()
    loop = ServiceLoop(
        kodi,
        date_provider=lambda: date(2026, 7, 29),
        monotonic_provider=lambda: 100.0,
        monitor=monitor,
    )
    loop._runtime_parts = lambda: (kodi.settings, initial_catalog, object())

    monkeypatch.setattr(service_loop, "DatabaseEngine", FakeEngine)
    monkeypatch.setattr(service_loop, "Catalog", lambda _engine, _log: scan_catalog)

    class PlaybackScanner:
        def __init__(
            self,
            _catalog,
            _filesystem,
            _settings,
            _logger,
            cancelled,
            progress,
            started,
        ):
            self.progress = progress
            self.started = started

        def scan_sources(self):
            self.started(SimpleNamespace())
            self.progress(
                SimpleNamespace(label="Family photos"),
                "smb://nas/photos/image.jpg",
                SimpleNamespace(pictures_seen=250),
            )
            monitor.aborted = True
            return SimpleNamespace(cancelled=False, pictures_seen=250, errors=0)

    monkeypatch.setattr(service_loop, "Scanner", PlaybackScanner)

    loop.run()

    assert not any(event[0] == "dialog" for event in kodi.scan_events)
    assert any(event[0] == "progress" and event[4] == 250 for event in kodi.scan_events)
    assert kodi.scan_events[-1][0] == "finish"
    assert ("info", "Automatic scan finished: 250 pictures, 0 errors") in kodi.log.messages


def test_automatic_scan_restores_progress_after_playback_stops(monkeypatch) -> None:
    monitor = FakeMonitor()
    kodi = FakeKodi(monitor)
    initial_catalog = FakeCatalog()
    scan_catalog = FakeCatalog()
    clock = iter((100.0, 101.0, 102.0, 103.0, 104.0, 105.0))
    loop = ServiceLoop(
        kodi,
        date_provider=lambda: date(2026, 7, 29),
        monotonic_provider=lambda: next(clock),
        monitor=monitor,
    )
    loop._runtime_parts = lambda: (kodi.settings, initial_catalog, object())

    monkeypatch.setattr(service_loop, "DatabaseEngine", FakeEngine)
    monkeypatch.setattr(service_loop, "Catalog", lambda _engine, _log: scan_catalog)

    class PlaybackTransitionScanner:
        def __init__(
            self,
            _catalog,
            _filesystem,
            _settings,
            _logger,
            cancelled,
            progress,
            started,
        ):
            self.progress = progress
            self.started = started

        def scan_sources(self):
            self.started(SimpleNamespace())
            self.progress(
                SimpleNamespace(label="Family photos"),
                "smb://nas/photos/first.jpg",
                SimpleNamespace(pictures_seen=100),
            )
            kodi.playing = True
            self.progress(
                SimpleNamespace(label="Family photos"),
                "smb://nas/photos/during-tv.jpg",
                SimpleNamespace(pictures_seen=200),
            )
            kodi.playing = False
            self.progress(
                SimpleNamespace(label="Family photos"),
                "smb://nas/photos/after-tv.jpg",
                SimpleNamespace(pictures_seen=300),
            )
            monitor.aborted = True
            return SimpleNamespace(cancelled=False, pictures_seen=300, errors=0)

    monkeypatch.setattr(service_loop, "Scanner", PlaybackTransitionScanner)

    loop.run()

    assert len(kodi.dialogs) == 2
    assert kodi.dialogs[0].closed is True
    assert kodi.dialogs[1].closed is True
    assert "Pictures found: 100" in kodi.dialogs[0].updates[-1][2]
    assert all("Pictures found: 200" not in update[2] for update in kodi.dialogs[0].updates)
    assert "Pictures found: 300" in kodi.dialogs[1].updates[-1][2]
    assert sum(1 for event in kodi.scan_events if event[0] == "dialog") == 2


def test_automatic_scan_pauses_silently_when_playback_starts(monkeypatch) -> None:
    class PlaybackMonitor(FakeMonitor):
        def __init__(self):
            super().__init__()
            self.kodi = None
            self.wait_calls = 0

        def waitForAbort(self, _timeout):
            self.wait_calls += 1
            self.kodi.playing = False
            return self.aborted

    monitor = PlaybackMonitor()
    kodi = FakeKodi(monitor)
    monitor.kodi = kodi
    kodi.settings.pause_during_playback = True
    initial_catalog = FakeCatalog()
    scan_catalog = FakeCatalog()
    clock = iter((100.0, 101.0, 102.0, 103.0, 104.0, 105.0))
    loop = ServiceLoop(
        kodi,
        date_provider=lambda: date(2026, 7, 29),
        monotonic_provider=lambda: next(clock),
        monitor=monitor,
    )
    loop._runtime_parts = lambda: (kodi.settings, initial_catalog, object())

    monkeypatch.setattr(service_loop, "DatabaseEngine", FakeEngine)
    monkeypatch.setattr(service_loop, "Catalog", lambda _engine, _log: scan_catalog)

    class PlaybackScanner:
        def __init__(
            self,
            _catalog,
            _filesystem,
            _settings,
            _logger,
            cancelled,
            progress,
            started,
        ):
            self.cancelled = cancelled
            self.progress = progress
            self.started = started

        def scan_sources(self):
            self.started(SimpleNamespace())
            self.progress(
                SimpleNamespace(label="Family photos"),
                "smb://nas/photos/before-tv.jpg",
                SimpleNamespace(pictures_seen=100),
            )
            kodi.playing = True
            assert self.cancelled() is False
            self.progress(
                SimpleNamespace(label="Family photos"),
                "smb://nas/photos/after-tv.jpg",
                SimpleNamespace(pictures_seen=200),
            )
            monitor.aborted = True
            return SimpleNamespace(cancelled=False, pictures_seen=200, errors=0)

    monkeypatch.setattr(service_loop, "Scanner", PlaybackScanner)

    loop.run()

    assert monitor.wait_calls == 1
    assert len(kodi.dialogs) == 2
    assert all(dialog.closed for dialog in kodi.dialogs)
    assert (
        "info",
        "Automatic scan paused during playback",
    ) in kodi.log.messages
    assert (
        "info",
        "Automatic scan resumed after playback",
    ) in kodi.log.messages
    assert all(
        "paused" not in message.lower()
        for dialog in kodi.dialogs
        for _percent, _heading, message in dialog.updates
    )


def test_automatic_cancel_while_paused_closes_progress_without_waiting_forever(
    monkeypatch,
) -> None:
    class CancelMonitor(FakeMonitor):
        def __init__(self):
            super().__init__()
            self.kodi = None
            self.wait_calls = 0

        def waitForAbort(self, _timeout):
            self.wait_calls += 1
            self.kodi.cancel_requested = True
            return False

    monitor = CancelMonitor()
    kodi = FakeKodi(monitor)
    monitor.kodi = kodi
    kodi.settings.pause_during_playback = True
    initial_catalog = FakeCatalog()
    scan_catalog = FakeCatalog()
    loop = ServiceLoop(
        kodi,
        date_provider=lambda: date(2026, 7, 29),
        monotonic_provider=lambda: 100.0,
        monitor=monitor,
    )
    loop._runtime_parts = lambda: (kodi.settings, initial_catalog, object())

    monkeypatch.setattr(service_loop, "DatabaseEngine", FakeEngine)
    monkeypatch.setattr(service_loop, "Catalog", lambda _engine, _log: scan_catalog)

    class CancelledWhilePausedScanner:
        def __init__(
            self,
            _catalog,
            _filesystem,
            _settings,
            _logger,
            cancelled,
            progress,
            started,
        ):
            self.cancelled = cancelled
            self.started = started

        def scan_sources(self):
            self.started(SimpleNamespace())
            kodi.playing = True
            assert self.cancelled() is True
            monitor.aborted = True
            return SimpleNamespace(cancelled=True, pictures_seen=10, errors=0)

    monkeypatch.setattr(service_loop, "Scanner", CancelledWhilePausedScanner)

    loop.run()

    assert monitor.wait_calls == 1
    assert all(dialog.closed for dialog in kodi.dialogs)
    assert ("info", "Automatic scan cancelled by user") in kodi.log.messages


def test_automatic_scan_invalidates_home_widgets_when_database_changes(monkeypatch) -> None:
    monitor = FakeMonitor()
    kodi = FakeKodi(monitor)
    initial_catalog = FakeCatalog()
    scan_catalog = FakeCatalog()
    loop = ServiceLoop(
        kodi,
        date_provider=lambda: date(2026, 7, 29),
        monotonic_provider=lambda: 100.0,
        monitor=monitor,
    )
    loop._runtime_parts = lambda: (kodi.settings, initial_catalog, object())

    monkeypatch.setattr(service_loop, "DatabaseEngine", FakeEngine)
    monkeypatch.setattr(service_loop, "Catalog", lambda _engine, _log: scan_catalog)

    class ChangedScanner:
        def __init__(self, _catalog, _filesystem, _settings, _logger, cancelled, progress, started):
            self.started = started

        def scan_sources(self):
            self.started(SimpleNamespace())
            monitor.aborted = True
            return SimpleNamespace(
                cancelled=False,
                pictures_seen=2,
                pictures_added=1,
                pictures_updated=1,
                missing_marked=0,
                errors=0,
            )

    monkeypatch.setattr(service_loop, "Scanner", ChangedScanner)

    loop.run()

    assert kodi.invalidations == ["automatic scan changed pictures"]
