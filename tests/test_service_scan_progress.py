from __future__ import annotations

from datetime import date
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


class FakeKodi:
    profile_path = "/tmp/mypicsdb3"

    def __init__(self, monitor):
        self.monitor = monitor
        self.log = FakeLog()
        self.dialog = FakeProgressDialog()
        self.scan_events = []
        self.cancel_requested = False
        self.settings = SimpleNamespace(
            auto_scan=True,
            pause_during_playback=False,
            startup_delay_seconds=0,
            scan_interval_hours=24,
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
        return False

    def localize(self, _string_id, fallback):
        return fallback

    def begin_scan_status(self, token, kind):
        self.scan_events.append(("begin", token, kind))

    def update_scan_status(self, token, source, path, pictures_seen):
        self.scan_events.append(("progress", token, source, path, pictures_seen))

    def finish_scan_status(self, token):
        self.scan_events.append(("finish", token))

    def scan_cancel_requested(self, _token):
        return self.cancel_requested

    def create_background_progress(self, heading, message):
        self.scan_events.append(("dialog", heading, message))
        return self.dialog


class FakeEngine:
    def __init__(self, _settings, _log):
        pass


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
                SimpleNamespace(pictures_seen=100),
            )
            monitor.aborted = True
            return SimpleNamespace(cancelled=False, pictures_seen=100, errors=0)

    monkeypatch.setattr(service_loop, "Scanner", FakeScanner)

    loop.run()

    assert initial_catalog.synced == []
    assert scan_catalog.initialized is True
    assert kodi.scan_events[0][0] == "begin"
    assert ("dialog", "MyPicsDB 3", "Automatic scan") in kodi.scan_events
    assert any(event[0] == "progress" and event[-1] == 100 for event in kodi.scan_events)
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
        "Automatic scan skipped: another scan is already running",
    ) in kodi.log.messages
    assert not any(level == "error" for level, _message in kodi.log.messages)
    assert kodi.scan_events == []

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
