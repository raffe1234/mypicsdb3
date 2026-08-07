from __future__ import annotations

import sys
import types

import pytest

from mypicsdb3 import entrypoints
from mypicsdb3 import kodi as kodi_module
from mypicsdb3.db.migrations import MigrationError, MigrationLockError
from mypicsdb3.router import Request
from mypicsdb3.service_loop import DATABASE_BUSY_RETRY_SECONDS, ServiceLoop


class FakeLog:
    def __init__(self):
        self.messages = []

    def info(self, message, *args):
        self.messages.append(("info", message % args if args else message))


class FakeKodiContext:
    def __init__(self):
        self.log = FakeLog()
        self.notifications = []

    def localize(self, string_id, fallback):
        assert string_id == entrypoints.DATABASE_BUSY_STRING_ID
        return fallback

    def notify(self, message, error=False, milliseconds=4000, force=False):
        self.notifications.append((message, error, milliseconds, force))


def install_plugin_modules(monkeypatch, context, request, runtime_error):
    ended = []

    kodi_module = types.ModuleType("mypicsdb3.kodi")
    kodi_module.KodiContext = lambda: context

    router_module = types.ModuleType("mypicsdb3.router")
    router_module.parse_request = lambda base_url, query: request

    runtime_module = types.ModuleType("mypicsdb3.runtime")

    class Runtime:
        def __init__(self, kodi_context=None):
            assert kodi_context is context
            raise runtime_error

    runtime_module.Runtime = Runtime

    views_module = types.ModuleType("mypicsdb3.views")

    class PluginUI:
        def __init__(self, *args, **kwargs):
            raise AssertionError("PluginUI must not be created while the database is busy")

    views_module.PluginUI = PluginUI

    xbmcplugin_module = types.ModuleType("xbmcplugin")
    xbmcplugin_module.endOfDirectory = lambda handle, succeeded=True, cacheToDisc=False: ended.append(
        (handle, succeeded, cacheToDisc)
    )

    monkeypatch.setitem(sys.modules, "mypicsdb3.kodi", kodi_module)
    monkeypatch.setitem(sys.modules, "mypicsdb3.router", router_module)
    monkeypatch.setitem(sys.modules, "mypicsdb3.runtime", runtime_module)
    monkeypatch.setitem(sys.modules, "mypicsdb3.views", views_module)
    monkeypatch.setitem(sys.modules, "xbmcplugin", xbmcplugin_module)
    return ended


def test_diagnostic_log_action_bypasses_database_and_reports_current_setting(monkeypatch):
    context = types.SimpleNamespace()
    context.settings = types.SimpleNamespace(debug_logging=True)
    context.log = FakeLog()
    context.notifications = []
    context.refresh_settings = lambda: context.settings
    context.localize = lambda string_id, fallback: (
        fallback if string_id == entrypoints.DIAGNOSTIC_LOG_STRING_ID else ""
    )
    context.notify = lambda message, error=False, milliseconds=4000, force=False: (
        context.notifications.append((message, error, milliseconds, force))
    )

    fake_kodi_module = types.ModuleType("mypicsdb3.kodi")
    fake_kodi_module.KodiContext = lambda: context
    runtime_module = types.ModuleType("mypicsdb3.runtime")

    class Runtime:
        def __init__(self, *args, **kwargs):
            raise AssertionError("diagnostic action must not open the database")

    runtime_module.Runtime = Runtime
    monkeypatch.setitem(sys.modules, "mypicsdb3.kodi", fake_kodi_module)
    monkeypatch.setitem(sys.modules, "mypicsdb3.runtime", runtime_module)

    entrypoints.plugin_main(
        ["plugin://plugin.image.mypicsdb3/action/log-diagnostic", "7", ""]
    )

    assert context.log.messages == [
        ("info", "Diagnostic log entry: version=0.8.1 debug_logging=true")
    ]
    assert context.notifications == [
        (entrypoints.DIAGNOSTIC_LOG_FALLBACK, False, 4000, True)
    ]


def test_interactive_plugin_request_reports_database_busy(monkeypatch):
    context = FakeKodiContext()
    request = Request("recent-taken", {})
    ended = install_plugin_modules(
        monkeypatch,
        context,
        request,
        MigrationLockError("another migration owns the lock"),
    )

    entrypoints.plugin_main(["plugin://plugin.image.mypicsdb3", "7", ""])

    assert context.notifications == [
        (entrypoints.DATABASE_BUSY_FALLBACK, False, 5000, True)
    ]
    assert ended == [(7, True, False)]
    assert context.log.messages == [
        ("info", "Database initialization is busy: another migration owns the lock")
    ]


def test_widget_request_returns_uncached_empty_directory_without_popup(monkeypatch):
    context = FakeKodiContext()
    request = Request("recent-taken", {"widget": "1"})
    ended = install_plugin_modules(
        monkeypatch,
        context,
        request,
        MigrationLockError("another migration owns the lock"),
    )

    entrypoints.plugin_main(["plugin://plugin.image.mypicsdb3", "9", "?widget=1"])

    assert context.notifications == []
    assert ended == [(9, True, False)]


def test_non_lock_migration_failure_is_not_hidden(monkeypatch):
    context = FakeKodiContext()
    request = Request("recent-taken", {})
    ended = install_plugin_modules(
        monkeypatch,
        context,
        request,
        MigrationError("schema history is invalid"),
    )

    with pytest.raises(MigrationError, match="schema history is invalid"):
        entrypoints.plugin_main(["plugin://plugin.image.mypicsdb3", "7", ""])

    assert context.notifications == []
    assert ended == []


def test_forced_busy_notification_bypasses_notification_preference(monkeypatch):
    shown = []

    class Dialog:
        def notification(self, heading, message, icon, milliseconds):
            shown.append((heading, message, icon, milliseconds))

    fake_gui = types.SimpleNamespace(
        NOTIFICATION_ERROR="error",
        NOTIFICATION_INFO="info",
        Dialog=Dialog,
    )
    monkeypatch.setattr(kodi_module, "xbmcgui", fake_gui)
    context = kodi_module.KodiContext.__new__(kodi_module.KodiContext)
    context.name = "MyPicsDB 3"
    context.settings = types.SimpleNamespace(show_notifications=False)

    context.notify("ordinary")
    context.notify("database busy", milliseconds=5000, force=True)

    assert shown == [("MyPicsDB 3", "database busy", "info", 5000)]


class FakeMonitor:
    def __init__(self, abort_on_wait=False):
        self.abort_on_wait = abort_on_wait
        self.aborted = False
        self.wait_calls = []

    def abortRequested(self):
        return self.aborted

    def waitForAbort(self, timeout):
        self.wait_calls.append(timeout)
        if self.abort_on_wait:
            self.aborted = True
        return self.aborted


class FakeServiceKodi:
    def __init__(self):
        self.log = FakeLog()


def test_service_retries_locked_migration_then_continues(monkeypatch):
    monitor = FakeMonitor()
    loop = ServiceLoop(FakeServiceKodi(), monitor=monitor)
    attempts = {"count": 0}
    expected = (object(), object(), object())

    def runtime_parts():
        attempts["count"] += 1
        if attempts["count"] < 3:
            raise MigrationLockError("another process is migrating")
        return expected

    monkeypatch.setattr(loop, "_runtime_parts", runtime_parts)

    assert loop._runtime_parts_when_ready() is expected
    assert attempts["count"] == 3
    assert monitor.wait_calls == [
        DATABASE_BUSY_RETRY_SECONDS,
        DATABASE_BUSY_RETRY_SECONDS,
    ]
    assert loop.kodi.log.messages == [
        (
            "info",
            "Database initialization is busy; retrying shortly: "
            "another process is migrating",
        )
    ]


def test_service_stops_retrying_when_kodi_shuts_down(monkeypatch):
    monitor = FakeMonitor(abort_on_wait=True)
    loop = ServiceLoop(FakeServiceKodi(), monitor=monitor)
    attempts = {"count": 0}

    def runtime_parts():
        attempts["count"] += 1
        raise MigrationLockError("another process is migrating")

    monkeypatch.setattr(loop, "_runtime_parts", runtime_parts)

    assert loop._runtime_parts_when_ready() is None
    assert attempts["count"] == 1
    assert monitor.wait_calls == [DATABASE_BUSY_RETRY_SECONDS]


def test_service_does_not_retry_other_migration_failures(monkeypatch):
    monitor = FakeMonitor()
    loop = ServiceLoop(FakeServiceKodi(), monitor=monitor)

    def runtime_parts():
        raise MigrationError("schema history is invalid")

    monkeypatch.setattr(loop, "_runtime_parts", runtime_parts)

    with pytest.raises(MigrationError, match="schema history is invalid"):
        loop._runtime_parts_when_ready()

    assert monitor.wait_calls == []
