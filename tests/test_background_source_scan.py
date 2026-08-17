from __future__ import annotations

import importlib
import sys
import types


class FakeBackgroundDialog:
    instances = []

    def __init__(self):
        self.created = []
        self.updates = []
        self.closed = False
        self.__class__.instances.append(self)

    def create(self, heading, message=""):
        self.created.append((heading, message))

    def update(self, percent=0, heading="", message=""):
        self.updates.append((percent, heading, message))

    def close(self):
        self.closed = True


class FakeForegroundDialog:
    instances = []

    def __init__(self):
        self.created = []
        self.updates = []
        self.closed = False
        self.iscancelled_calls = 0
        self.__class__.instances.append(self)

    def create(self, heading, message=""):
        self.created.append((heading, message))

    def update(self, percent=0, message=""):
        self.updates.append((percent, message))

    def iscancelled(self):
        self.iscancelled_calls += 1
        return False

    def close(self):
        self.closed = True


class FakeMonitor:
    def __init__(self, kodi):
        self.kodi = kodi
        self.wait_calls = 0
        self.abort_requested = False

    def abortRequested(self):
        return self.abort_requested

    def waitForAbort(self, timeout):
        self.wait_calls += 1
        self.kodi.playing = False
        return False


class FakeAddon:
    def getAddonInfo(self, key):
        return {"icon": "icon.png", "fanart": "fanart.jpg"}[key]


class FakeKodi:
    def __init__(self):
        self.addon = FakeAddon()
        self.settings = types.SimpleNamespace(
            pause_during_playback=True,
            widget_limit=15,
            browser_page_size=100,
        )
        self.playing = True
        self.monitor = FakeMonitor(self)
        self.notifications = []
        self.log_messages = []
        self.scan_state = {}
        self.cancel_token = ""
        self.log = types.SimpleNamespace(
            info=lambda message, *args: self.log_messages.append(
                message % args if args else message
            ),
            warning=lambda message, *args: self.log_messages.append(
                message % args if args else message
            ),
            error=lambda message, *args: self.log_messages.append(
                message % args if args else message
            ),
        )

    def localize(self, string_id, fallback):
        return fallback

    def abort_monitor(self):
        return self.monitor

    def refresh_settings(self):
        return self.settings

    def is_playing(self):
        return self.playing

    def notify(self, message, **kwargs):
        self.notifications.append((message, kwargs))

    def scan_status(self):
        return dict(self.scan_state)

    def begin_scan_status(self, token, kind):
        self.scan_state = {
            "token": token,
            "kind": kind,
            "state": "running",
            "pictures_seen": 0,
        }

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
        if self.scan_state.get("token") == token:
            self.scan_state.update(
                source=source,
                path=path,
                pictures_seen=pictures_seen,
                pictures_unchanged=pictures_unchanged,
                metadata_reads=metadata_reads,
                pictures_added=pictures_added,
                pictures_updated=pictures_updated,
                errors=errors,
            )

    def scan_cancel_requested(self, token):
        return self.cancel_token == token

    def finish_scan_status(self, token):
        if self.scan_state.get("token") == token:
            self.scan_state = {}


class FakeRuntime:
    def __init__(self):
        self.kodi = FakeKodi()
        self.catalog = object()
        self.filesystem = object()


def load_views(monkeypatch):
    executed = []

    xbmc = types.ModuleType("xbmc")
    xbmc.executebuiltin = executed.append

    xbmcgui = types.ModuleType("xbmcgui")
    xbmcgui.ListItem = object
    xbmcgui.DialogProgress = FakeForegroundDialog
    xbmcgui.DialogProgressBG = FakeBackgroundDialog

    xbmcplugin = types.ModuleType("xbmcplugin")

    monkeypatch.setitem(sys.modules, "xbmc", xbmc)
    monkeypatch.setitem(sys.modules, "xbmcgui", xbmcgui)
    monkeypatch.setitem(sys.modules, "xbmcplugin", xbmcplugin)
    sys.modules.pop("mypicsdb3.views", None)

    return importlib.import_module("mypicsdb3.views"), executed


def test_selected_source_scan_runs_in_background_and_pauses(monkeypatch):
    FakeBackgroundDialog.instances.clear()
    views, executed = load_views(monkeypatch)
    captured = {}

    class FakeScanner:
        def __init__(
            self,
            catalog,
            filesystem,
            settings,
            logger,
            cancelled,
            progress,
            started,
        ):
            captured["cancelled"] = cancelled
            captured["progress"] = progress
            captured["started"] = started

        def scan_sources(self, source_ids=None):
            captured["source_ids"] = source_ids
            captured["started"](types.SimpleNamespace())
            assert captured["cancelled"]() is False
            captured["progress"](
                types.SimpleNamespace(label="Photographs"),
                "smb://nas/photos/image.jpg",
                types.SimpleNamespace(pictures_seen=1),
            )
            return types.SimpleNamespace(
                cancelled=False,
                pictures_seen=1,
                errors=0,
            )

    monkeypatch.setattr(views, "Scanner", FakeScanner)

    runtime = FakeRuntime()
    ui = views.PluginUI(
        runtime,
        "plugin://plugin.image.mypicsdb3",
        7,
    )
    ui._manual_scan("12")

    dialog = FakeBackgroundDialog.instances[-1]
    messages = [update[2] for update in dialog.updates]

    assert captured["source_ids"] == [12]
    assert runtime.kodi.monitor.wait_calls == 1
    assert all("Scan paused during playback" not in message for message in messages)
    assert all("Scan resumed" not in message for message in messages)
    assert "Manual scan paused during playback" in runtime.kodi.log_messages
    assert "Manual scan resumed after playback" in runtime.kodi.log_messages
    assert dialog.closed is True
    assert executed == []
    assert runtime.kodi.notifications[-1][0] == "Pictures found: 1, Errors: 0"


def test_full_scan_runs_in_background(monkeypatch):
    FakeBackgroundDialog.instances.clear()
    views, executed = load_views(monkeypatch)
    captured = {}

    class FakeScanner:
        def __init__(self, catalog, filesystem, settings, logger, cancelled, progress, started):
            captured["cancelled"] = cancelled
            captured["progress"] = progress
            captured["started"] = started

        def scan_sources(self, source_ids=None):
            captured["source_ids"] = source_ids
            captured["started"](types.SimpleNamespace())
            return types.SimpleNamespace(cancelled=False, pictures_seen=4, errors=0)

    monkeypatch.setattr(views, "Scanner", FakeScanner)
    runtime = FakeRuntime()
    runtime.kodi.playing = False
    ui = views.PluginUI(runtime, "plugin://plugin.image.mypicsdb3", 7)

    ui._manual_scan(None)

    dialog = FakeBackgroundDialog.instances[-1]
    assert captured["source_ids"] is None
    assert dialog.created == [("MyPicsDB 3", "Scanning started")]
    assert dialog.closed is True
    assert executed == []
    assert runtime.kodi.notifications[-1][0] == "Pictures found: 4, Errors: 0"


def test_full_scan_stops_without_gui_calls_when_kodi_aborts(monkeypatch):
    FakeBackgroundDialog.instances.clear()
    views, executed = load_views(monkeypatch)
    captured = {}
    runtime = FakeRuntime()
    runtime.kodi.playing = False

    class FakeScanner:
        def __init__(
            self,
            catalog,
            filesystem,
            settings,
            logger,
            cancelled,
            progress,
            started,
        ):
            captured["cancelled"] = cancelled
            captured["progress"] = progress
            captured["started"] = started

        def scan_sources(self, source_ids=None):
            captured["source_ids"] = source_ids
            runtime.kodi.monitor.abort_requested = True
            assert captured["cancelled"]() is True
            captured["progress"](
                types.SimpleNamespace(label="Photographs"),
                "smb://nas/photos/image.jpg",
                types.SimpleNamespace(pictures_seen=1),
            )
            return types.SimpleNamespace(
                cancelled=True,
                pictures_seen=1,
                errors=0,
            )

    monkeypatch.setattr(views, "Scanner", FakeScanner)

    ui = views.PluginUI(
        runtime,
        "plugin://plugin.image.mypicsdb3",
        7,
    )
    ui._manual_scan(None)

    assert captured["source_ids"] is None
    assert FakeBackgroundDialog.instances == []
    assert executed == []
    assert runtime.kodi.notifications == []


def test_selected_source_scan_stops_without_gui_calls_when_kodi_aborts(monkeypatch):
    FakeBackgroundDialog.instances.clear()
    views, executed = load_views(monkeypatch)
    captured = {}
    runtime = FakeRuntime()
    runtime.kodi.playing = False

    class FakeScanner:
        def __init__(
            self,
            catalog,
            filesystem,
            settings,
            logger,
            cancelled,
            progress,
            started,
        ):
            captured["cancelled"] = cancelled
            captured["progress"] = progress
            captured["started"] = started

        def scan_sources(self, source_ids=None):
            runtime.kodi.monitor.abort_requested = True
            assert captured["cancelled"]() is True
            captured["progress"](
                types.SimpleNamespace(label="Photographs"),
                "smb://nas/photos/image.jpg",
                types.SimpleNamespace(pictures_seen=1),
            )
            return types.SimpleNamespace(
                cancelled=True,
                pictures_seen=1,
                errors=0,
            )

    monkeypatch.setattr(views, "Scanner", FakeScanner)

    ui = views.PluginUI(
        runtime,
        "plugin://plugin.image.mypicsdb3",
        7,
    )
    ui._manual_scan("12")

    assert FakeBackgroundDialog.instances == []
    assert executed == []
    assert runtime.kodi.notifications == []


def test_user_cancel_closes_dialog_without_refreshing_container(monkeypatch):
    FakeBackgroundDialog.instances.clear()
    views, executed = load_views(monkeypatch)
    runtime = FakeRuntime()
    runtime.kodi.playing = False

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

        def scan_sources(self, source_ids=None):
            self.started(types.SimpleNamespace())
            runtime.kodi.cancel_token = runtime.kodi.scan_state["token"]
            assert self.cancelled() is True
            return types.SimpleNamespace(cancelled=True, pictures_seen=7, errors=0)

    monkeypatch.setattr(views, "Scanner", CancelledScanner)
    ui = views.PluginUI(runtime, "plugin://plugin.image.mypicsdb3", 7)

    ui._manual_scan(None)

    assert FakeBackgroundDialog.instances[-1].closed is True
    assert runtime.kodi.scan_state == {}
    assert executed == []
    assert runtime.kodi.notifications[-1][0] == "Scan cancelled"


def test_unexpected_scan_failure_closes_dialog_and_clears_status(monkeypatch):
    FakeBackgroundDialog.instances.clear()
    views, executed = load_views(monkeypatch)
    runtime = FakeRuntime()
    runtime.kodi.playing = False

    class FailingScanner:
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
            self.started = started

        def scan_sources(self, source_ids=None):
            self.started(types.SimpleNamespace())
            raise ValueError("broken metadata")

    monkeypatch.setattr(views, "Scanner", FailingScanner)
    ui = views.PluginUI(runtime, "plugin://plugin.image.mypicsdb3", 7)

    ui._manual_scan(None)

    assert FakeBackgroundDialog.instances[-1].closed is True
    assert runtime.kodi.scan_state == {}
    assert executed == []
    assert "Manual scan failed: broken metadata" in runtime.kodi.log_messages
    assert runtime.kodi.notifications[-1][0] == "Scanning failed: broken metadata"


def test_scanner_constructor_failure_is_reported_without_gui_refresh(monkeypatch):
    FakeBackgroundDialog.instances.clear()
    views, executed = load_views(monkeypatch)
    runtime = FakeRuntime()
    runtime.kodi.playing = False

    class BrokenScanner:
        def __init__(self, *_args, **_kwargs):
            raise ValueError("scanner setup failed")

    monkeypatch.setattr(views, "Scanner", BrokenScanner)
    ui = views.PluginUI(runtime, "plugin://plugin.image.mypicsdb3", 7)

    ui._manual_scan(None)

    assert FakeBackgroundDialog.instances == []
    assert runtime.kodi.scan_state == {}
    assert executed == []
    assert "Manual scan failed: scanner setup failed" in runtime.kodi.log_messages
    assert runtime.kodi.notifications[-1][0] == "Scanning failed: scanner setup failed"


def test_scan_setting_failure_is_reported_without_starting_scanner(monkeypatch):
    FakeBackgroundDialog.instances.clear()
    views, executed = load_views(monkeypatch)
    runtime = FakeRuntime()
    runtime.kodi.playing = False
    runtime.kodi.refresh_settings = lambda: (_ for _ in ()).throw(
        ValueError("invalid settings")
    )
    ui = views.PluginUI(runtime, "plugin://plugin.image.mypicsdb3", 7)

    ui._manual_scan(None)

    assert FakeBackgroundDialog.instances == []
    assert executed == []
    assert "Could not load scan settings: invalid settings" in runtime.kodi.log_messages
    assert runtime.kodi.notifications[-1][0] == "Scanning failed: invalid settings"
