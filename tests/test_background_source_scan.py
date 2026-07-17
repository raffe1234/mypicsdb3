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


class FakeMonitor:
    def __init__(self, kodi):
        self.kodi = kodi
        self.wait_calls = 0

    def abortRequested(self):
        return False

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
        self.log = types.SimpleNamespace(
            info=lambda message, *args: self.log_messages.append(
                message % args if args else message
            ),
            warning=lambda *args: None,
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
    xbmcgui.DialogProgress = object
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
        ):
            captured["cancelled"] = cancelled
            captured["progress"] = progress

        def scan_sources(self, source_ids=None):
            captured["source_ids"] = source_ids
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
    assert "Scan paused during playback" in messages
    assert "Scan resumed" in messages
    assert dialog.closed is True
    assert executed[-1] == "Container.Refresh"
    assert runtime.kodi.notifications[-1][0] == "Pictures found: 1, Errors: 0"
