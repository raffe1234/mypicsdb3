from __future__ import annotations

from datetime import date
from types import SimpleNamespace

import mypicsdb3.service_loop as service_loop
from mypicsdb3.service_loop import ServiceLoop


class FakeLog:
    def info(self, *args):
        pass

    def warning(self, *args):
        pass

    def error(self, *args):
        pass


class FakeMonitor:
    def __init__(self, aborted=False):
        self.aborted = aborted
        self.wait_calls = []

    def abortRequested(self):
        return self.aborted

    def waitForAbort(self, timeout):
        self.wait_calls.append(timeout)
        return self.aborted


class FakeCatalog:
    def __init__(self):
        self.synced_sources = None

    def sync_sources(self, sources):
        self.synced_sources = sources


class FakeKodi:
    profile_path = "/tmp/mypicsdb3"

    def __init__(self, monitor):
        self.monitor = monitor
        self.log = FakeLog()
        self.refresh_calls = 0

    def abort_monitor(self):
        return self.monitor

    def kodi_picture_sources(self):
        return []

    def execute_jsonrpc(self, method, params=None):
        assert method == "Player.GetActivePlayers"
        return []

    def refresh_settings(self):
        self.refresh_calls += 1
        self.monitor.aborted = True
        return SimpleNamespace(
            auto_scan=True,
            pause_during_playback=False,
            startup_delay_seconds=0,
            scan_interval_hours=1,
        )

    def refresh_date_sensitive_views(self):
        return True

    def is_playing(self):
        return False


def test_service_returns_before_initializing_when_shutdown_was_requested() -> None:
    monitor = FakeMonitor(aborted=True)
    kodi = FakeKodi(monitor)
    loop = ServiceLoop(kodi, monitor=monitor)
    loop._runtime_parts = lambda: (_ for _ in ()).throw(
        AssertionError("runtime must not initialize during shutdown")
    )

    loop.run()

    assert monitor.wait_calls == []


def test_shutdown_race_before_due_scan_does_not_start_scanner(monkeypatch) -> None:
    monitor = FakeMonitor()
    kodi = FakeKodi(monitor)
    settings = SimpleNamespace(
        auto_scan=True,
        pause_during_playback=False,
        startup_delay_seconds=0,
        scan_interval_hours=1,
    )
    catalog = FakeCatalog()
    loop = ServiceLoop(
        kodi,
        date_provider=lambda: date(2026, 7, 26),
        monotonic_provider=lambda: 100.0,
        monitor=monitor,
    )
    loop._runtime_parts = lambda: (settings, catalog, object())

    class ScannerMustNotStart:
        def __init__(self, *args, **kwargs):
            raise AssertionError("scanner started after shutdown notification")

    monkeypatch.setattr(service_loop, "Scanner", ScannerMustNotStart)

    loop.run()

    assert catalog.synced_sources == []
    assert kodi.refresh_calls == 1
    assert monitor.aborted is True
