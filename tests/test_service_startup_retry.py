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


def test_service_retries_transient_unknown_addon_id(monkeypatch):
    attempts = {"count": 0}
    context = FakeContext()

    class KodiContext:
        def __new__(cls):
            attempts["count"] += 1
            if attempts["count"] < 3:
                raise RuntimeError("Unknown addon id 'plugin.image.mypicsdb3'.")
            return context

    class ServiceLoop:
        def __init__(self, received):
            assert received is context

        def run(self):
            return None

    kodi_module = types.ModuleType("mypicsdb3.kodi")
    kodi_module.KodiContext = KodiContext
    service_module = types.ModuleType("mypicsdb3.service_loop")
    service_module.ServiceLoop = ServiceLoop
    monkeypatch.setitem(sys.modules, "mypicsdb3.kodi", kodi_module)
    monkeypatch.setitem(sys.modules, "mypicsdb3.service_loop", service_module)
    monkeypatch.setattr(entrypoints.time, "sleep", lambda _seconds: None)
    entrypoints.service_main()
    assert attempts["count"] == 3
    assert ("info", "MyPicsDB 3 service started") in context.log.messages
    assert ("info", "MyPicsDB 3 service stopped") in context.log.messages
