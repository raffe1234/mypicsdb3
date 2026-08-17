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


class FakeDialog:
    def yesno(self, heading, message):
        return True

    def select(self, heading, options, preselect=-1):
        return 0


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
        self.settings = types.SimpleNamespace(pause_during_playback=True)
        self.playing = True
        self.monitor = FakeMonitor(self)
        self.notifications = []
        self.log_messages = []
        self.refresh_state = {}
        self.cancel_token = ""
        self.invalidations = []
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

    def refresh_settings(self):
        return self.settings

    def abort_monitor(self):
        return self.monitor

    def is_playing(self):
        return self.playing

    def notify(self, message, **kwargs):
        self.notifications.append((message, kwargs))

    def begin_metadata_refresh_status(self, token, processed, total):
        self.refresh_state = {
            "token": token,
            "state": "running",
            "processed": processed,
            "total": total,
        }

    def update_metadata_refresh_status(self, token, processed, total, filename=""):
        if self.refresh_state.get("token") == token:
            self.refresh_state.update(
                processed=processed,
                total=total,
                filename=filename,
            )

    def metadata_refresh_cancel_requested(self, token):
        return self.cancel_token == token

    def finish_metadata_refresh_status(self, token):
        if self.refresh_state.get("token") == token:
            self.refresh_state = {}

    def invalidate_home_widgets(self, reason):
        self.invalidations.append(reason)


class FakeCatalog:
    def metadata_refresh_picture_horizon(self, max_picture_id=None):
        return (2, 2)


class FakeRuntime:
    def __init__(self):
        self.kodi = FakeKodi()
        self.catalog = FakeCatalog()
        self.filesystem = object()


def load_views(monkeypatch):
    executed = []
    sleeps = []

    xbmc = types.ModuleType("xbmc")
    xbmc.executebuiltin = executed.append
    xbmc.sleep = sleeps.append

    xbmcgui = types.ModuleType("xbmcgui")
    xbmcgui.ListItem = object
    xbmcgui.Dialog = FakeDialog
    xbmcgui.DialogProgressBG = FakeBackgroundDialog

    xbmcplugin = types.ModuleType("xbmcplugin")

    monkeypatch.setitem(sys.modules, "xbmc", xbmc)
    monkeypatch.setitem(sys.modules, "xbmcgui", xbmcgui)
    monkeypatch.setitem(sys.modules, "xbmcplugin", xbmcplugin)
    sys.modules.pop("mypicsdb3.views", None)

    return importlib.import_module("mypicsdb3.views"), executed, sleeps


def test_whole_library_metadata_refresh_pauses_during_playback_and_resumes(monkeypatch):
    FakeBackgroundDialog.instances.clear()
    views, executed, sleeps = load_views(monkeypatch)
    runtime = FakeRuntime()
    captured = {}

    class FakeRefresher:
        def all_refresh_checkpoint(self):
            return None

        def refresh_all(self, cancelled=None, progress=None, restart=False):
            assert restart is False
            captured["token"] = runtime.kodi.refresh_state["token"]
            assert cancelled() is False
            progress(1, 2, "one.jpg")
            progress(2, 2, "two.jpg")
            return types.SimpleNamespace(
                refreshed=2,
                failed=0,
                processed=2,
                requested=2,
                completed=True,
            )

    ui = views.PluginUI(runtime, "plugin://plugin.image.mypicsdb3", 7)
    monkeypatch.setattr(ui, "_metadata_refresher", lambda: FakeRefresher())

    ui._refresh_all_picture_metadata()

    assert runtime.kodi.monitor.wait_calls == 1
    assert "Whole-library metadata refresh paused during playback" in runtime.kodi.log_messages
    assert "Whole-library metadata refresh resumed after playback" in runtime.kodi.log_messages
    assert runtime.kodi.refresh_state == {}
    assert runtime.kodi.invalidations == ["whole-library metadata refreshed"]
    assert sleeps == []
    assert executed[-1] == "Container.Refresh"

    dialog = FakeBackgroundDialog.instances[-1]
    assert dialog.created == [("MyPicsDB 3", "Reading indexed picture metadata")]
    assert dialog.updates[-1] == (100, "MyPicsDB 3", "2 / 2\ntwo.jpg")
    assert dialog.closed is True
    assert runtime.kodi.notifications[-1][0] == "All metadata refresh complete: 2 refreshed, 0 failed"


def test_whole_library_metadata_refresh_honours_shared_soft_cancel(monkeypatch):
    FakeBackgroundDialog.instances.clear()
    views, _executed, _sleeps = load_views(monkeypatch)
    runtime = FakeRuntime()

    class FakeRefresher:
        def all_refresh_checkpoint(self):
            return None

        def refresh_all(self, cancelled=None, progress=None, restart=False):
            runtime.kodi.cancel_token = runtime.kodi.refresh_state["token"]
            assert cancelled() is True
            return types.SimpleNamespace(
                refreshed=0,
                failed=0,
                processed=0,
                requested=2,
                completed=False,
            )

    runtime.kodi.playing = False
    ui = views.PluginUI(runtime, "plugin://plugin.image.mypicsdb3", 7)
    monkeypatch.setattr(ui, "_metadata_refresher", lambda: FakeRefresher())

    ui._refresh_all_picture_metadata()

    assert runtime.kodi.refresh_state == {}
    assert runtime.kodi.notifications[-1][0] == (
        "Metadata refresh paused at 0 / 2. Run it again to resume."
    )
