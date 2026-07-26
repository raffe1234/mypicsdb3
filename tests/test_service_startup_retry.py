from __future__ import annotations

import sys
import types

from mypicsdb3 import entrypoints


class FakeLog:
    def __init__(self):
        self.messages = []

    def info(self, message, *args):
        self.messages.append(("info", message % args if args else message))

    def error(self, message, *args):
        self.messages.append(("error", message % args if args else message))


class FakeContext:
    def __init__(self):
        self.log = FakeLog()


class FakeMonitor:
    def __init__(self, abort_on_wait=False):
        self.abort_on_wait = abort_on_wait
        self.wait_calls = []
        self.aborted = False

    def abortRequested(self):
        return self.aborted

    def waitForAbort(self, timeout):
        self.wait_calls.append(timeout)
        if self.abort_on_wait:
            self.aborted = True
        return self.aborted


def test_service_retries_transient_unknown_addon_id(monkeypatch):
    attempts = {"count": 0}
    context = FakeContext()
    monitor = FakeMonitor()

    class KodiContext:
        def __new__(cls):
            attempts["count"] += 1
            if attempts["count"] < 3:
                raise RuntimeError("Unknown addon id 'plugin.image.mypicsdb3'.")
            return context

    class ServiceLoop:
        def __init__(self, received, monitor=None):
            assert received is context
            assert monitor is not None

        def run(self):
            return None

    kodi_module = types.ModuleType("mypicsdb3.kodi")
    kodi_module.KodiContext = KodiContext
    kodi_module.create_abort_monitor = lambda: monitor
    service_module = types.ModuleType("mypicsdb3.service_loop")
    service_module.ServiceLoop = ServiceLoop
    monkeypatch.setitem(sys.modules, "mypicsdb3.kodi", kodi_module)
    monkeypatch.setitem(sys.modules, "mypicsdb3.service_loop", service_module)
    entrypoints.service_main()
    assert attempts["count"] == 3
    assert monitor.wait_calls == [1.0, 1.0]
    assert ("info", "MyPicsDB 3 service started") in context.log.messages
    assert ("info", "MyPicsDB 3 service stopped") in context.log.messages


def test_service_retry_stops_when_kodi_starts_shutting_down(monkeypatch):
    attempts = {"count": 0}
    monitor = FakeMonitor(abort_on_wait=True)

    class KodiContext:
        def __new__(cls):
            attempts["count"] += 1
            raise RuntimeError("Unknown addon id 'plugin.image.mypicsdb3'.")

    class ServiceLoop:
        def __init__(self, *args, **kwargs):
            raise AssertionError("service loop must not start during shutdown")

    kodi_module = types.ModuleType("mypicsdb3.kodi")
    kodi_module.KodiContext = KodiContext
    kodi_module.create_abort_monitor = lambda: monitor
    service_module = types.ModuleType("mypicsdb3.service_loop")
    service_module.ServiceLoop = ServiceLoop
    monkeypatch.setitem(sys.modules, "mypicsdb3.kodi", kodi_module)
    monkeypatch.setitem(sys.modules, "mypicsdb3.service_loop", service_module)

    entrypoints.service_main()

    assert attempts["count"] == 1
    assert monitor.wait_calls == [1.0]
