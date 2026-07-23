from __future__ import annotations

import importlib
import sys
import types
from dataclasses import dataclass, field


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
    select_responses = []

    def yesno(self, heading, message):
        return self.__class__.responses.pop(0)

    def select(self, heading, options, preselect=-1):
        return self.__class__.select_responses.pop(0)


@dataclass
class Calls:
    category: str | None = None
    content: str | None = None
    items: list | None = None
    ended: bool = False
    builtins: list[str] = field(default_factory=list)


def load_views(monkeypatch):
    calls = Calls()
    xbmc = types.ModuleType("xbmc")
    xbmc.executebuiltin = calls.builtins.append
    xbmc.getInfoLabel = lambda label: ""
    xbmcgui = types.ModuleType("xbmcgui")
    xbmcgui.ListItem = FakeListItem
    xbmcgui.Dialog = FakeDialog
    xbmcgui.DialogProgress = object
    xbmcgui.getCurrentWindowId = lambda: 10002
    xbmcgui.Window = lambda window_id: types.SimpleNamespace(getFocusId=lambda: 55)
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
    def __init__(self):
        self.settings = {}

    def getAddonInfo(self, key):
        return {"icon": "icon.png", "fanart": "fanart.jpg"}[key]

    def getSetting(self, key):
        return self.settings.get(key, "")

    def setSetting(self, key, value):
        self.settings[key] = value


class FakeKodi:
    def __init__(self):
        self.addon = FakeAddon()
        self.settings = types.SimpleNamespace(
            widget_limit=15,
            browser_page_size=100,
            album_view_mode=55,
        )
        self.log = types.SimpleNamespace(warning=lambda *args: None)
        self.notifications = []

    def localize(self, string_id, fallback):
        return fallback

    def kodi_picture_sources(self):
        return []

    def notify(self, message, error=False, milliseconds=4000):
        self.notifications.append((message, error))

    def refresh_settings(self):
        value = self.addon.getSetting("album_view_mode")
        if value:
            self.settings.album_view_mode = int(value)
        return self.settings


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

    def get_folder(self, folder_id):
        return {"id": folder_id, "source_id": 4, "uri": "smb://server/photos/Summer/", "name": "Summer"}

    def child_folders(self, source_id, uri):
        return []

    def pictures_in_folder(self, folder_id, limit, offset):
        return self.recent_taken(limit, offset)

    def years(self):
        return [{
            "year": 2020,
            "picture_count": 1,
            "uri": "smb://server/photos/image.jpg",
            "thumb_uri": "smb://server/photos/image.jpg",
        }]

    def undated_summary(self):
        return {
            "picture_count": 1,
            "uri": "smb://server/photos/undated.jpg",
            "thumb_uri": "smb://server/photos/undated.jpg",
        }

    def months_for_year(self, year):
        assert year == 2020
        return [{
            "month": 7,
            "picture_count": 1,
            "uri": "smb://server/photos/image.jpg",
            "thumb_uri": "smb://server/photos/image.jpg",
        }]

    def days_for_month(self, year, month):
        assert (year, month) == (2020, 7)
        return [{
            "day": 17,
            "picture_count": 1,
            "uri": "smb://server/photos/image.jpg",
            "thumb_uri": "smb://server/photos/image.jpg",
        }]

    def pictures_for_day(self, year, month, day, limit, offset):
        assert (year, month, day) == (2020, 7, 17)
        return self.recent_taken(limit, offset)

    def pictures_without_date(self, limit, offset=0):
        row = dict(self.recent_taken(limit, offset)[0])
        row["taken_at"] = None
        row["filename"] = "undated.jpg"
        row["uri"] = "smb://server/photos/undated.jpg"
        row["thumb_uri"] = row["uri"]
        return [row]


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


def test_home_widget_uses_configured_limit_without_browser_pagination(monkeypatch) -> None:
    views, calls = load_views(monkeypatch)
    runtime = FakeRuntime()
    runtime.kodi.settings.widget_limit = 37
    requested = []

    def recent_taken(limit, offset=0):
        requested.append((limit, offset))
        return []

    runtime.catalog.recent_taken = recent_taken
    ui = views.PluginUI(runtime, "plugin://plugin.image.mypicsdb3", 7)

    ui.dispatch(views.Request("recent-taken", {"widget": "1"}))

    assert requested == [(37, 0)]
    assert calls.items == []
    assert calls.ended is True


def test_date_browser_drills_from_year_to_day_and_preserves_pagination(monkeypatch) -> None:
    views, calls = load_views(monkeypatch)
    runtime = FakeRuntime()
    runtime.kodi.settings.browser_page_size = 1
    ui = views.PluginUI(runtime, "plugin://plugin.image.mypicsdb3", 7)

    ui.dispatch(views.Request("years", {}))
    assert [item[0] for item in calls.items] == [
        "plugin://plugin.image.mypicsdb3/year?year=2020",
        "plugin://plugin.image.mypicsdb3/no-date",
    ]

    ui.dispatch(views.Request("year", {"year": "2020"}))
    assert calls.category == "2020"
    assert calls.items[0][0] == "plugin://plugin.image.mypicsdb3/month?year=2020&month=7"

    ui.dispatch(views.Request("month", {"year": "2020", "month": "7"}))
    assert calls.category == "July 2020"
    assert calls.items[0][0] == "plugin://plugin.image.mypicsdb3/day?year=2020&month=7&day=17"

    ui.dispatch(
        views.Request(
            "day",
            {"year": "2020", "month": "7", "day": "17"},
        )
    )
    assert calls.category == "2020-07-17"
    assert len(calls.items) == 2
    assert calls.items[1][0] == (
        "plugin://plugin.image.mypicsdb3/day?offset=1&limit=1&year=2020&month=7&day=17"
    )

    ui.dispatch(views.Request("no-date", {}))
    assert calls.category == "No date"
    assert calls.items[0][1].label == "undated.jpg"


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


def test_album_uses_default_view(monkeypatch) -> None:
    views, calls = load_views(monkeypatch)
    runtime = FakeRuntime()
    runtime.kodi.settings.album_view_mode = 54
    ui = views.PluginUI(runtime, "plugin://plugin.image.mypicsdb3", 7)

    ui.folder(3, {})

    assert "Container.SetViewMode(54)" in calls.builtins
    assert len(calls.items) == 1


def test_current_album_view_can_be_saved(monkeypatch) -> None:
    views, _calls = load_views(monkeypatch)
    runtime = FakeRuntime()
    ui = views.PluginUI(runtime, "plugin://plugin.image.mypicsdb3", 7)

    views.xbmcgui.Window = lambda window_id: types.SimpleNamespace(getFocusId=lambda: 500)
    ui.action("action/save-album-view", {})

    assert runtime.kodi.addon.settings["album_view_mode"] == "500"
    assert runtime.kodi.settings.album_view_mode == 500
    assert runtime.kodi.notifications[-1] == ("Album default view saved: Wall", False)


def test_home_screen_editor_enables_a_hidden_row(monkeypatch) -> None:
    views, calls = load_views(monkeypatch)
    runtime = FakeRuntime()
    ui = views.PluginUI(runtime, "plugin://plugin.image.mypicsdb3", 7)

    monkeypatch.setattr(
        views,
        "show_home_layout_editor",
        lambda order, enabled, labels, text: (tuple(order), frozenset(set(enabled) | {"favorites"})),
    )
    ui.action("action/configure-home", {})

    assert runtime.kodi.addon.settings["home_row_7"] == "favorites"
    assert "favorites" in runtime.kodi.addon.settings["home_layout"]
    assert "ReloadSkin()" in calls.builtins


def test_album_items_expose_save_default_view_context_action(monkeypatch) -> None:
    views, calls = load_views(monkeypatch)
    ui = views.PluginUI(FakeRuntime(), "plugin://plugin.image.mypicsdb3", 7)

    ui.folder(2, {})

    assert calls.items
    _, picture, _ = calls.items[0]
    assert (
        "Save current view as album default",
        "RunPlugin(plugin://plugin.image.mypicsdb3/action/save-album-view)",
    ) in picture.context
