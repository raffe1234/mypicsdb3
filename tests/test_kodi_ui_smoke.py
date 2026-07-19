from __future__ import annotations

import importlib
import sys
import types
from dataclasses import dataclass


class FakeListItem:
    def __init__(self, label="", path=""):
        self.label = label
        self.path = path
        self.art = {}
        self.properties = {}
        self.context = []
        self.info = {}

    def setArt(self, art):
        self.art.update(art)

    def setProperty(self, key, value):
        self.properties[key] = value

    def addContextMenuItems(self, items):
        self.context.extend(items)

    def setInfo(self, media_type, info):
        self.info[media_type] = info


class FakeDialog:
    responses = []

    def yesno(self, heading, message):
        return self.__class__.responses.pop(0)


@dataclass
class Calls:
    category: str | None = None
    content: str | None = None
    items: list | None = None
    ended: bool = False


def load_views(monkeypatch):
    calls = Calls()
    xbmc = types.ModuleType("xbmc")
    xbmc.executebuiltin = lambda command: None
    xbmcgui = types.ModuleType("xbmcgui")
    xbmcgui.ListItem = FakeListItem
    xbmcgui.Dialog = FakeDialog
    xbmcgui.DialogProgress = object
    xbmcplugin = types.ModuleType("xbmcplugin")
    xbmcplugin.setPluginCategory = lambda handle, category: setattr(calls, "category", category)
    xbmcplugin.setContent = lambda handle, content: setattr(calls, "content", content)
    xbmcplugin.addDirectoryItems = lambda handle, items, total: setattr(calls, "items", items) or True
    xbmcplugin.endOfDirectory = lambda handle, succeeded=True, cacheToDisc=False: setattr(calls, "ended", True)
    monkeypatch.setitem(sys.modules, "xbmc", xbmc)
    monkeypatch.setitem(sys.modules, "xbmcgui", xbmcgui)
    monkeypatch.setitem(sys.modules, "xbmcplugin", xbmcplugin)
    sys.modules.pop("mypicsdb3.views", None)
    return importlib.import_module("mypicsdb3.views"), calls


class FakeAddon:
    def getAddonInfo(self, key):
        return {"icon": "icon.png", "fanart": "fanart.jpg"}[key]


class FakeKodi:
    def __init__(self):
        self.addon = FakeAddon()
        self.settings = types.SimpleNamespace(widget_limit=15, browser_page_size=100)
        self.log = types.SimpleNamespace(warning=lambda *args: None)

    def localize(self, string_id, fallback):
        return fallback

    def kodi_picture_sources(self):
        return []


class FakeCatalog:
    def __init__(self):
        self.deleted_sources = []

    def sync_sources(self, sources):
        return []

    def get_sources(self):
        return [types.SimpleNamespace(id=7, label="FotonTest", enabled=False)]

    def delete_source(self, source_id):
        self.deleted_sources.append(source_id)
        return True

    def recent_taken(self, limit, offset=0):
        return [{
            "id": 1,
            "folder_id": 2,
            "uri": "smb://server/photos/image.jpg",
            "thumb_uri": "smb://server/photos/image.jpg",
            "filename": "image.jpg",
            "taken_at": "2020-07-17 12:00:00",
            "discovered_at": "2026-07-17 09:00:00",
            "width": 1920,
            "height": 1080,
            "camera_make": "Canon",
            "camera_model": "EOS R6",
            "folder_name": "Summer",
            "source_label": "Photos",
            "rating": 5,
        }]


class FakeRuntime:
    def __init__(self):
        self.kodi = FakeKodi()
        self.catalog = FakeCatalog()
        self.filesystem = object()


def test_root_and_picture_widget_return_valid_directory_items(monkeypatch) -> None:
    views, calls = load_views(monkeypatch)
    ui = views.PluginUI(FakeRuntime(), "plugin://plugin.image.mypicsdb3", 7)

    ui.root()
    assert calls.ended is True
    assert calls.content == "files"
    assert calls.category == "MyPicsDB 3"
    assert len(calls.items) == 16
    assert calls.items[0][0].endswith("/sources")

    calls.ended = False
    ui.dispatch(views.Request("recent-taken", {"limit": "15"}))
    assert calls.ended is True
    assert calls.content == "images"
    assert len(calls.items) == 1
    url, item, is_folder = calls.items[0]
    assert url == "smb://server/photos/image.jpg"
    assert item.art["thumb"] == url
    assert item.properties["MyPicsDB3.Camera"] == "Canon EOS R6"
    assert is_folder is False


def test_source_toggle_uses_plugin_root_from_nested_route(monkeypatch) -> None:
    views, calls = load_views(monkeypatch)
    ui = views.PluginUI(FakeRuntime(), "plugin://plugin.image.mypicsdb3/sources", 7)

    ui.sources()

    assert calls.ended is True
    assert len(calls.items) == 2
    url, item, is_folder = calls.items[1]
    assert url == "plugin://plugin.image.mypicsdb3/action/toggle-source?id=7"
    assert is_folder is False
    assert item.context[0] == (
        "Enable source",
        "RunPlugin(plugin://plugin.image.mypicsdb3/action/toggle-source?id=7)",
    )


def test_refresh_sources_asks_before_deleting_missing_source(monkeypatch) -> None:
    views, _calls = load_views(monkeypatch)
    runtime = FakeRuntime()
    runtime.catalog.sync_sources = lambda _sources: [
        types.SimpleNamespace(id=9, label="Old photos", available=False)
    ]
    ui = views.PluginUI(runtime, "plugin://plugin.image.mypicsdb3", 7)

    FakeDialog.responses = [False]
    ui.action("action/refresh-sources", {})
    assert runtime.catalog.deleted_sources == []

    FakeDialog.responses = [True]
    ui.action("action/refresh-sources", {})
    assert runtime.catalog.deleted_sources == [9]
