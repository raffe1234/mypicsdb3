from __future__ import annotations

import importlib
import json
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
    multiselect_responses = []
    input_responses = []
    browse_responses = []
    browse_calls = []

    def yesno(self, heading, message):
        return self.__class__.responses.pop(0)

    def select(self, heading, options, preselect=-1):
        return self.__class__.select_responses.pop(0)

    def multiselect(self, heading, options, preselect=None):
        return self.__class__.multiselect_responses.pop(0)

    def input(self, heading, defaultt=""):
        return self.__class__.input_responses.pop(0)

    def browseSingle(
        self, type, heading, shares, mask="", useThumbs=False,
        treatAsFolder=False, defaultt=""
    ):
        self.__class__.browse_calls.append(
            (type, heading, shares, mask, useThumbs, treatAsFolder, defaultt)
        )
        return self.__class__.browse_responses.pop(0)


@dataclass
class Calls:
    category: str | None = None
    content: str | None = None
    items: list | None = None
    ended: bool = False
    builtins: list[str] = field(default_factory=list)
    focus_id: int = 55
    rpc_requests: list[dict] = field(default_factory=list)
    sleeps: list[int] = field(default_factory=list)
    info_label_sequences: dict[str, list[str]] = field(default_factory=dict)
    resolved_urls: list[tuple[int, bool, object]] = field(default_factory=list)
    music_playlist_uri: str = ""
    music_playlist_items: list[str] = field(default_factory=list)
    player_calls: list[tuple[object, int]] = field(default_factory=list)


def load_views(monkeypatch):
    calls = Calls()
    xbmc = types.ModuleType("xbmc")

    def execute_builtin(command, _block=False):
        calls.builtins.append(command)
        if command.startswith("Container.SetViewMode("):
            calls.focus_id = int(command.rsplit("(", 1)[1].rstrip(")"))

    xbmc.executebuiltin = execute_builtin
    xbmc.sleep = calls.sleeps.append

    xbmc.PLAYLIST_MUSIC = 0

    class FakePlayList:
        def __init__(self, playlist_type):
            self.playlist_type = playlist_type

        def load(self, uri):
            calls.music_playlist_uri = str(uri)
            calls.music_playlist_items = [
                "smb://server/music/one.mp3",
                "smb://server/music/two.mp3",
            ]
            return True

        def size(self):
            return len(calls.music_playlist_items)

    class FakePlayer:
        def play(self, playlist, startpos=0):
            calls.player_calls.append((playlist, int(startpos)))

    xbmc.PlayList = FakePlayList
    xbmc.Player = FakePlayer

    def execute_jsonrpc(payload):
        request = json.loads(payload)
        calls.rpc_requests.append(request)
        if request["method"] == "Player.GetActivePlayers":
            result = [{"playerid": 2, "type": "picture"}]
        elif request["method"] == "Playlist.GetItems":
            result = {
                "items": [{"file": item} for item in calls.music_playlist_items],
                "limits": {"total": len(calls.music_playlist_items)},
            }
        else:
            result = "OK"
        return json.dumps({"jsonrpc": "2.0", "id": 1, "result": result})

    xbmc.executeJSONRPC = execute_jsonrpc

    def get_info_label(label):
        sequence = calls.info_label_sequences.get(label)
        if sequence:
            return sequence.pop(0)
        if label == "Container.PluginCategory":
            return calls.category or ""
        if label == "Container.Content":
            return calls.content or ""
        return ""

    xbmc.getInfoLabel = get_info_label
    xbmcgui = types.ModuleType("xbmcgui")
    xbmcgui.ListItem = FakeListItem
    xbmcgui.Dialog = FakeDialog
    xbmcgui.DialogProgress = object
    xbmcgui.getCurrentWindowId = lambda: 10002
    xbmcgui.Window = lambda window_id: types.SimpleNamespace(
        getFocusId=lambda: calls.focus_id
    )
    xbmcplugin = types.ModuleType("xbmcplugin")
    xbmcplugin.setPluginCategory = lambda handle, category: setattr(calls, "category", category)
    xbmcplugin.setContent = lambda handle, content: setattr(calls, "content", content)
    xbmcplugin.addDirectoryItems = lambda handle, items, total: setattr(calls, "items", items) or True
    xbmcplugin.endOfDirectory = lambda handle, succeeded=True, cacheToDisc=False: setattr(calls, "ended", True)
    xbmcplugin.setResolvedUrl = lambda handle, succeeded, item: calls.resolved_urls.append(
        (handle, bool(succeeded), item)
    )
    monkeypatch.setitem(sys.modules, "xbmc", xbmc)
    monkeypatch.setitem(sys.modules, "xbmcgui", xbmcgui)
    monkeypatch.setitem(sys.modules, "xbmcplugin", xbmcplugin)
    sys.modules.pop("mypicsdb3.views", None)
    return importlib.import_module("mypicsdb3.views"), calls


class FakeAddon:
    def __init__(self):
        self.settings = {}

    def getAddonInfo(self, key):
        return {
            "icon": "icon.png",
            "fanart": "fanart.jpg",
            "version": "0.8.18",
        }[key]

    def getSetting(self, key):
        return self.settings.get(key, "")

    def setSetting(self, key, value):
        self.settings[key] = value


class FakeKodi:
    def __init__(self):
        self.addon = FakeAddon()
        self.settings = types.SimpleNamespace(
            widget_limit=15,
            home_widget_limit=10,
            browser_page_size=100,
            album_view_mode=55,
            minimum_rating_policy="all",
            extensions=("jpg", "jpeg", "png", "nef"),
            include_videos=False,
            video_extensions=("mp4", "mov", "m4v", "mkv", "avi"),
            exclude_fragments=("@eadir", "#recycle"),
            exclude_hidden=True,
            random_home_refresh_hours=2,
            debug_logging=False,
        )
        self.debug_messages = []
        self.info_messages = []
        self.log = types.SimpleNamespace(
            warning=lambda *args: None,
            debug=lambda message, *args: self.debug_messages.append(
                message % args if args else message
            ),
            info=lambda message, *args: self.info_messages.append(
                message % args if args else message
            ),
        )
        self.notifications = []
        self.mixed_slideshow_updates = []
        self.picture_playlist_compatibility_value = True
        self.picture_playlist_compatibility_updates = []
        self.scan_state = {}
        self.scan_cancel_requests = 0
        self.random_refreshes = 0
        self.random_invalidations = []
        self.home_invalidations = []
        self.home_generations = {"content": 7, "random": 3}
        self.random_home_session_token = "test-session-a"
        self.music_session = {}
        self.music_fingerprint = "test-music-fingerprint"

    def localize(self, string_id, fallback):
        return fallback

    def installed_addon_version(self, addon_id):
        return {
            "screensaver.mypicsdb3": "0.7.0",
            "repository.mypicsdb3": "0.2.26",
            "skin.estuary.mypicsdb3": "21.3.16",
        }.get(addon_id, "")

    def current_skin_id(self):
        return "skin.estuary.mypicsdb3"

    def kodi_picture_sources(self):
        return []

    def notify(self, message, error=False, milliseconds=4000, force=False):
        self.notifications.append((message, error))

    def refresh_settings(self):
        value = self.addon.getSetting("album_view_mode")
        if value:
            self.settings.album_view_mode = int(value)
        return self.settings

    def set_mixed_slideshow_active(self, active):
        self.mixed_slideshow_updates.append(bool(active))

    def picture_playlist_compatibility(self):
        return self.picture_playlist_compatibility_value

    def set_picture_playlist_compatibility(self, compatible):
        self.picture_playlist_compatibility_value = compatible
        self.picture_playlist_compatibility_updates.append(compatible)

    def scan_status(self):
        return dict(self.scan_state)

    def request_scan_cancel(self):
        if not self.scan_state:
            return False
        self.scan_cancel_requests += 1
        self.scan_state["state"] = "cancelling"
        return True

    def refresh_random_views(self):
        self.random_refreshes += 1

    def invalidate_random_home_widgets(self, reason):
        self.random_invalidations.append(reason)
        return len(self.random_invalidations)

    def invalidate_home_widgets(self, reason):
        self.home_invalidations.append(reason)
        return len(self.home_invalidations)

    def home_widget_generations(self):
        return dict(self.home_generations)

    def random_home_widget_session_token(self):
        return self.random_home_session_token

    def is_playing(self):
        return False

    def music_playlist_fingerprint(self):
        return self.music_fingerprint

    def set_music_slideshow_session(self, token, playlist_fingerprint):
        self.music_session = {
            "token": token,
            "playlist_fingerprint": playlist_fingerprint,
        }

    def music_slideshow_session(self):
        return dict(self.music_session)

    def clear_music_slideshow_session(self, token=""):
        if not token or self.music_session.get("token") == token:
            self.music_session = {}


class FakeCatalog:
    def __init__(self):
        self.deleted_sources = []
        self.rating_policy = "all"
        self.query_requests = []
        self.saved_search_rows = []
        self.saved_search_objects = {}
        self.created_saved_searches = []
        self.renamed_saved_searches = []
        self.deleted_saved_searches = []
        self.collection_rows = []
        self.collection_objects = {}
        self.created_collections = []
        self.collection_snapshots = []
        self.renamed_collections = []
        self.deleted_collections = []
        self.added_collection_items = []
        self.removed_collection_items = []
        self.moved_collection_items = []
        self.collection_requests = []
        self.music_playlists = {}
        self.music_playlist_updates = []
        self.music_playlist_clears = []
        self.source_scan_policies = {}
        self.metadata_mapping_overrides = []
        self.facet_requests = []

    def set_rating_policy(self, rating_policy):
        self.rating_policy = rating_policy

    def sync_sources(self, sources):
        return []

    def overview(self):
        return {
            "backend": "sqlite",
            "pictures": 20,
            "videos": 2,
            "missing": 1,
            "folders": 4,
            "sources": 3,
            "enabled_sources": 2,
        }

    def latest_scan(self):
        return {
            "started_at": "2026-08-05 12:00:00.000000",
            "finished_at": "2026-08-05 12:04:18.000000",
            "status": "completed",
            "pictures_seen": 20,
            "pictures_added": 3,
            "pictures_updated": 2,
            "pictures_unchanged": 15,
            "errors": 0,
        }

    def get_sources(self):
        return [types.SimpleNamespace(id=7, label="FotonTest", enabled=False, available=True)]

    def get_source(self, source_id):
        if int(source_id) != 7:
            return None
        return types.SimpleNamespace(id=7, label="FotonTest", enabled=False, available=True)

    def get_source_scan_policy(self, source_id):
        return self.source_scan_policies.get(int(source_id))

    def set_source_scan_policy(self, source_id, policy):
        self.source_scan_policies[int(source_id)] = policy

    def clear_source_scan_policy(self, source_id):
        return self.source_scan_policies.pop(int(source_id), None) is not None

    def list_metadata_mapping_overrides(self):
        return list(self.metadata_mapping_overrides)

    def set_metadata_mapping_rule(self, rule):
        self.metadata_mapping_overrides = [
            existing for existing in self.metadata_mapping_overrides
            if not (
                existing.source_type == rule.source_type
                and existing.source_tag.casefold() == rule.source_tag.casefold()
            )
        ]
        self.metadata_mapping_overrides.append(rule)

    def clear_metadata_mapping_rule(self, source_type, source_tag):
        before = len(self.metadata_mapping_overrides)
        self.metadata_mapping_overrides = [
            rule for rule in self.metadata_mapping_overrides
            if not (
                rule.source_type == str(source_type).casefold()
                and rule.source_tag.casefold() == str(source_tag).casefold()
            )
        ]
        return len(self.metadata_mapping_overrides) != before

    def clear_metadata_mapping_rules(self):
        count = len(self.metadata_mapping_overrides)
        self.metadata_mapping_overrides = []
        return count

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
            "media_type": "picture",
        }]


    def on_this_day(self, month, day, current_year, limit, offset=0):
        return self.recent_taken(limit, offset)

    def random_on_this_day(self, month, day, current_year, limit):
        return self.recent_taken(limit, 0)

    def query_pictures(self, query, limit, offset=0):
        self.query_requests.append((query, limit, offset))
        return self.recent_taken(limit, offset)

    def count_query_pictures(self, query):
        self.query_requests.append((query, "count", 0))
        return 1

    def ordered_query_picture_ids(self, query):
        self.query_requests.append((query, "export-ids", 0))
        return [1]

    def ordered_collection_picture_ids(self, collection_id):
        self.collection_requests.append(("export-ids", int(collection_id)))
        return [1]

    def media_for_export(self, picture_ids):
        return [
            {
                "id": int(picture_id),
                "uri": "smb://server/photos/image.jpg",
                "filename": "image.jpg",
                "media_type": "picture",
                "file_size": 123,
                "file_mtime": 1000.0,
                "source_label": "Photos",
            }
            for picture_id in picture_ids
        ]

    def query_facet_counts(self, query, field, limit=100, offset=0):
        self.facet_requests.append((query, field, limit, offset))
        values = {
            "camera_make": [("Canon", 12), ("Nikon", 8)],
            "camera_model": [("EOS R6", 7)],
            "country": [("Sweden", 10), ("Spain", 5)],
            "state": [("Stockholm", 4)],
            "city": [("Stockholm", 4)],
            "sublocation": [("Old Town", 2)],
            "taken_year": [(2024, 20), (2023, 15)],
            "extension": [("jpg", 18), ("png", 2)],
            "mime_type": [("image/jpeg", 18)],
            "aspect": [("landscape", 11), ("portrait", 9)],
            "rating": [(5, 6), (4, 4)],
            "keyword": [("Family", 9), ("Summer", 5)],
        }.get(field, [])
        return [
            {"value": value, "picture_count": count}
            for value, count in values[offset:offset + limit]
        ]

    def list_saved_searches(self):
        return list(self.saved_search_rows)

    def get_saved_search(self, saved_search_id):
        return self.saved_search_objects.get(saved_search_id)

    def get_saved_search_summary(self, saved_search_id):
        saved = self.saved_search_objects.get(saved_search_id)
        if saved is None:
            return None
        return {"id": saved.id, "name": saved.name, "query_version": 1}

    def create_saved_search(self, name, query):
        self.created_saved_searches.append((name, query))
        return 1

    def rename_saved_search(self, saved_search_id, name):
        self.renamed_saved_searches.append((saved_search_id, name))
        return True

    def delete_saved_search(self, saved_search_id):
        self.deleted_saved_searches.append(saved_search_id)
        return True

    def get_music_playlist(self, collection_type, collection_id):
        return self.music_playlists.get((str(collection_type), int(collection_id)), "")

    def set_music_playlist(self, collection_type, collection_id, playlist_uri):
        key = (str(collection_type), int(collection_id))
        target_exists = (
            int(collection_id) in self.saved_search_objects
            if str(collection_type) == "smart"
            else int(collection_id) in self.collection_objects
        )
        if not target_exists:
            return False
        self.music_playlists[key] = str(playlist_uri)
        rows = (
            self.saved_search_rows
            if str(collection_type) == "smart"
            else self.collection_rows
        )
        for row in rows:
            if int(row.get("id") or 0) == int(collection_id):
                row["music_playlist_uri"] = str(playlist_uri)
        self.music_playlist_updates.append((*key, str(playlist_uri)))
        return True

    def clear_music_playlist(self, collection_type, collection_id):
        key = (str(collection_type), int(collection_id))
        self.music_playlists.pop(key, None)
        rows = (
            self.saved_search_rows
            if str(collection_type) == "smart"
            else self.collection_rows
        )
        for row in rows:
            if int(row.get("id") or 0) == int(collection_id):
                row.pop("music_playlist_uri", None)
        self.music_playlist_clears.append(key)
        return True

    def list_collections(self):
        return list(self.collection_rows)

    def get_collection(self, collection_id):
        return self.collection_objects.get(collection_id)

    def create_collection(self, name):
        collection_id = max(self.collection_objects, default=0) + 1
        collection = types.SimpleNamespace(id=collection_id, name=name.strip())
        self.collection_objects[collection_id] = collection
        self.created_collections.append(name)
        return collection_id

    def create_collection_snapshot(self, name, query):
        collection_id = max(self.collection_objects, default=0) + 1
        collection = types.SimpleNamespace(id=collection_id, name=name.strip())
        self.collection_objects[collection_id] = collection
        self.collection_snapshots.append((name, query))
        return collection_id, 1

    def rename_collection(self, collection_id, name):
        self.renamed_collections.append((collection_id, name))
        collection = self.collection_objects.get(collection_id)
        if collection is not None:
            collection.name = name.strip()
        for row in self.collection_rows:
            if int(row.get("id") or 0) == int(collection_id):
                row["name"] = name.strip()
        return True

    def delete_collection(self, collection_id):
        self.deleted_collections.append(collection_id)
        self.collection_objects.pop(collection_id, None)
        self.collection_rows = [
            row
            for row in self.collection_rows
            if int(row.get("id") or 0) != int(collection_id)
        ]
        return True

    def add_picture_to_collection(self, collection_id, picture_id):
        item = (collection_id, picture_id)
        if item in self.added_collection_items:
            return False
        self.added_collection_items.append(item)
        return True

    def remove_picture_from_collection(self, collection_id, picture_id):
        self.removed_collection_items.append((collection_id, picture_id))
        return True

    def pictures_in_collection(self, collection_id, limit, offset=0):
        self.collection_requests.append((collection_id, limit, offset))
        return self.recent_taken(limit, offset)

    def collection_available_count(self, collection_id):
        return len(self.pictures_in_collection(collection_id, 5000, 0))

    def move_picture_in_collection(self, collection_id, picture_id, direction):
        self.moved_collection_items.append((collection_id, picture_id, direction))
        return True

    def get_folder(self, folder_id):
        return {"id": folder_id, "source_id": 4, "uri": "smb://server/photos/Summer/", "name": "Summer"}

    def child_folders(self, source_id, uri):
        return []

    def pictures_in_folder(self, folder_id, limit, offset):
        return self.recent_taken(limit, offset)

    def media_in_folder_tree(self, folder_id, limit):
        return self.recent_taken(limit, 0)

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
    assert len(calls.items) == 26
    assert calls.items[0][0].endswith("/search")
    assert calls.items[1][0].endswith("/saved-searches")
    assert calls.items[2][0].endswith("/collections")
    assert calls.items[3][0].endswith("/action/create-smart-collection")
    assert calls.items[4][0].endswith("/sources")
    assert any(url.endswith("/metadata-mapping") for url, _item, _folder in calls.items)
    assert any(url.endswith("/metadata-browser") for url, _item, _folder in calls.items)
    assert any(url.endswith("/needs-attention") for url, _item, _folder in calls.items)

    calls.ended = False
    ui.dispatch(views.Request("recent-taken", {"limit": "15"}))
    assert calls.ended is True
    assert calls.content == "images"
    assert len(calls.items) == 1
    url, item, is_folder = calls.items[0]
    assert url == "smb://server/photos/image.jpg"
    assert item.art["thumb"] == "smb://server/photos/image.jpg"
    assert item.properties["MyPicsDB3.Camera"] == "Canon EOS R6"
    assert is_folder is False


def test_root_hides_only_configured_browsing_nodes(monkeypatch) -> None:
    views, calls = load_views(monkeypatch)
    runtime = FakeRuntime()
    runtime.kodi.addon.settings["hidden_main_menu_nodes"] = (
        "recent_taken|years|favorites"
    )
    ui = views.PluginUI(runtime, "plugin://plugin.image.mypicsdb3", 7)

    ui.root()

    urls = [url for url, _item, _is_folder in calls.items]
    assert len(urls) == 23
    assert "plugin://plugin.image.mypicsdb3/recent-taken" not in urls
    assert "plugin://plugin.image.mypicsdb3/years" not in urls
    assert "plugin://plugin.image.mypicsdb3/favorites" not in urls
    assert "plugin://plugin.image.mypicsdb3/search" in urls
    assert "plugin://plugin.image.mypicsdb3/saved-searches" in urls
    assert "plugin://plugin.image.mypicsdb3/collections" in urls
    assert "plugin://plugin.image.mypicsdb3/action/create-smart-collection" in urls
    assert "plugin://plugin.image.mypicsdb3/sources" in urls
    assert "plugin://plugin.image.mypicsdb3/metadata-mapping" in urls
    assert "plugin://plugin.image.mypicsdb3/metadata-browser" in urls
    assert "plugin://plugin.image.mypicsdb3/needs-attention" in urls
    assert "plugin://plugin.image.mypicsdb3/action/refresh-random" in urls
    assert "plugin://plugin.image.mypicsdb3/action/scan" in urls
    assert "plugin://plugin.image.mypicsdb3/status" in urls
    assert "plugin://plugin.image.mypicsdb3/diagnostics" in urls
    assert "plugin://plugin.image.mypicsdb3/action/settings" in urls


def test_metadata_browser_uses_curated_facets_and_query_model_results(monkeypatch) -> None:
    views, calls = load_views(monkeypatch)
    runtime = FakeRuntime()
    ui = views.PluginUI(runtime, "plugin://plugin.image.mypicsdb3", 7)

    ui.dispatch(views.Request("metadata-browser", {}))
    assert calls.category == "Browse metadata"
    assert [item.label for _url, item, _folder in calls.items] == [
        "Camera", "Location", "Capture", "Image", "Keywords"
    ]

    calls.items.clear()
    ui.dispatch(views.Request("metadata-category", {"category": "location"}))
    assert calls.category == "Location"
    assert [item.label for _url, item, _folder in calls.items] == [
        "Country", "State or region", "City", "Sublocation"
    ]

    calls.items.clear()
    ui.dispatch(views.Request("metadata-values", {"field": "country"}))
    assert calls.category == "Country"
    assert [item.label for _url, item, _folder in calls.items] == [
        "Sweden  [COLOR=grey](10)[/COLOR]",
        "Spain  [COLOR=grey](5)[/COLOR]",
    ]
    query, field, limit, offset = runtime.catalog.facet_requests[-1]
    assert field == "country"
    assert limit == runtime.kodi.settings.browser_page_size + 1
    assert offset == 0
    assert query.root.children[0].field == "media_type"

    calls.items.clear()
    runtime.catalog.query_requests.clear()
    ui.dispatch(
        views.Request(
            "metadata-result",
            {"field": "camera_make", "value": "Canon"},
        )
    )
    assert calls.category == "Camera make: Canon"
    query, limit, offset = runtime.catalog.query_requests[0]
    assert (limit, offset) == (runtime.kodi.settings.browser_page_size, 0)
    assert query.root.children[1].field == "camera"
    assert query.root.children[1].value.make == "Canon"


def test_needs_attention_uses_query_model_presets_and_opens_results(monkeypatch) -> None:
    views, calls = load_views(monkeypatch)
    runtime = FakeRuntime()
    ui = views.PluginUI(runtime, "plugin://plugin.image.mypicsdb3", 7)

    ui.dispatch(views.Request("needs-attention", {}))

    assert calls.category == "Needs attention"
    assert [item.label for _url, item, _folder in calls.items] == [
        "Pictures without date  [COLOR=grey](1)[/COLOR]",
        "Pictures without camera  [COLOR=grey](1)[/COLOR]",
        "Pictures without location  [COLOR=grey](1)[/COLOR]",
        "Pictures without keywords  [COLOR=grey](1)[/COLOR]",
    ]
    assert len(runtime.catalog.query_requests) == 4

    calls.items.clear()
    calls.ended = False
    runtime.catalog.query_requests.clear()
    ui.dispatch(views.Request("needs-attention-result", {"kind": "missing-location"}))

    assert calls.ended is True
    assert calls.category == "Pictures without location"
    assert len(calls.items) == 3
    assert calls.items[0][0].endswith(
        "/action/snapshot-results?scope=needs-attention&kind=missing-location"
    )
    assert calls.items[1][0].endswith(
        "/action/export-results?scope=needs-attention&kind=missing-location"
    )
    query, limit, offset = runtime.catalog.query_requests[0]
    assert (limit, offset) == (runtime.kodi.settings.browser_page_size, 0)
    assert [child.field for child in query.root.children] == [
        "media_type",
        "country",
        "state",
        "city",
        "sublocation",
    ]


def test_root_replaces_scan_now_with_stop_scan_while_scan_is_active(monkeypatch) -> None:
    views, calls = load_views(monkeypatch)
    runtime = FakeRuntime()
    runtime.kodi.scan_state = {
        "token": "scan-1",
        "kind": "automatic",
        "state": "running",
        "pictures_seen": 123,
    }
    ui = views.PluginUI(runtime, "plugin://plugin.image.mypicsdb3", 7)

    ui.root()

    urls = [url for url, _item, _is_folder in calls.items]
    labels = [item.label for _url, item, _is_folder in calls.items]
    assert "plugin://plugin.image.mypicsdb3/action/scan" not in urls
    assert "plugin://plugin.image.mypicsdb3/action/stop-scan" in urls
    assert "Stop scan" in labels



def test_scan_status_shows_completed_duration_and_active_elapsed_time(monkeypatch) -> None:
    views, calls = load_views(monkeypatch)
    runtime = FakeRuntime()
    runtime.kodi.scan_state = {
        "token": "scan-1",
        "kind": "manual",
        "state": "running",
        "pictures_seen": 12,
        "started_at": 1000.0,
    }
    monkeypatch.setattr(views.time, "time", lambda: 1125.0)
    ui = views.PluginUI(runtime, "plugin://plugin.image.mypicsdb3", 7)

    ui.status()

    labels = [item.label for _url, item, _is_folder in calls.items]
    assert "Scan duration: 4 min 18 sec" in labels
    assert "Elapsed time: 2 min 5 sec" in labels


def test_diagnostics_view_is_privacy_safe_and_read_only(monkeypatch) -> None:
    views, calls = load_views(monkeypatch)
    runtime = FakeRuntime()
    runtime.kodi.settings.debug_logging = True
    runtime.kodi.settings.include_videos = True
    runtime.kodi.home_generations = {"content": 17, "random": 6}
    runtime.kodi.picture_playlist_compatibility_value = False
    runtime.kodi.music_session = {
        "token": "private-ui-token",
        "playlist_fingerprint": "private-ui-fingerprint",
    }
    runtime.kodi.scan_state = {
        "token": "scan-1",
        "kind": "automatic",
        "state": "running",
        "pictures_seen": 12,
        "started_at": 1000.0,
        "source": "Private photos",
        "path": "smb://secret-user:secret-pass@server/private/image.jpg",
    }
    monkeypatch.setattr(views.time, "time", lambda: 1125.0)
    ui = views.PluginUI(runtime, "plugin://plugin.image.mypicsdb3", 7)

    ui.dispatch(views.Request("diagnostics", {}))

    labels = [item.label for _url, item, _is_folder in calls.items]
    joined = "\n".join(labels)
    assert calls.category == "Diagnostics"
    assert calls.content == "files"
    assert "MyPicsDB 3 version: 0.8.18" in labels
    assert "Screensaver version: 0.7.0" in labels
    assert "Repository version: 0.2.26" in labels
    assert "Current skin: skin.estuary.mypicsdb3 21.3.16" in labels
    assert "Database schema: 9" in labels
    assert "Query Model version: 1" in labels
    assert "Sources: 3" in labels
    assert "Enabled sources: 2" in labels
    assert "Active scan: Automatic scan - Scan in progress" in labels
    assert "Elapsed time: 2 min 5 sec" in labels
    assert "Home widget generation: 17" in labels
    assert "Random Home generation: 6" in labels
    assert "Picture playlist compatibility: Incompatible" in labels
    assert "Music slideshow session: Active" in labels
    assert "Music playlist ownership marker: Present" in labels
    assert "Include videos: On" in labels
    assert "Debug logging: On" in labels
    assert (
        "Support bundle folder: Kodi userdata > addon_data > "
        "plugin.image.mypicsdb3 > support-bundles"
    ) in labels
    assert "smb://" not in joined
    assert "secret-pass" not in joined
    assert "Private photos" not in joined
    assert "private-ui-token" not in joined
    assert "private-ui-fingerprint" not in joined
    for url, item, is_folder in calls.items[:-2]:
        assert url == ""
        assert item.properties["IsPlayable"] == "false"
        assert item.properties["MyPicsDB3.MediaType"] == "info"
        assert is_folder is False
    assert calls.items[-2][0].endswith("/action/log-diagnostic")
    assert calls.items[-1][0].endswith("/action/export-support-bundle")


def test_export_support_bundle_action_reports_generated_filename(monkeypatch) -> None:
    views, _calls = load_views(monkeypatch)
    runtime = FakeRuntime()
    ui = views.PluginUI(runtime, "plugin://plugin.image.mypicsdb3", 7)
    monkeypatch.setattr(
        views,
        "write_support_bundle",
        lambda _runtime: "/private/profile/support-bundles/mypicsdb3-support-test-v0.8.14.zip",
    )

    ui.dispatch(views.Request("action/export-support-bundle", {}))

    assert runtime.kodi.notifications[-1] == (
        "Support bundle saved: mypicsdb3-support-test-v0.8.14.zip\n"
        "Support bundle folder: Kodi userdata > addon_data > "
        "plugin.image.mypicsdb3 > support-bundles",
        False,
    )
    assert runtime.kodi.info_messages[-1] == (
        "Privacy-safe support bundle exported: mypicsdb3-support-test-v0.8.14.zip"
    )


def test_export_support_bundle_action_reports_failure(monkeypatch) -> None:
    views, _calls = load_views(monkeypatch)
    runtime = FakeRuntime()
    ui = views.PluginUI(runtime, "plugin://plugin.image.mypicsdb3", 7)

    def fail(_runtime):
        raise OSError("disk full")

    monkeypatch.setattr(views, "write_support_bundle", fail)
    ui.dispatch(views.Request("action/export-support-bundle", {}))

    assert runtime.kodi.notifications[-1] == (
        "Could not export support bundle: disk full",
        True,
    )



def test_refresh_random_selections_refreshes_widgets_without_scanning(monkeypatch) -> None:
    views, _calls = load_views(monkeypatch)
    runtime = FakeRuntime()
    ui = views.PluginUI(runtime, "plugin://plugin.image.mypicsdb3", 7)

    ui.dispatch(views.Request("action/refresh-random", {}))

    assert runtime.kodi.random_refreshes == 1
    assert runtime.kodi.random_invalidations == ["manual random refresh"]
    assert runtime.kodi.notifications[-1] == ("Random selections refreshed", False)


def test_stop_scan_requires_confirmation_and_requests_soft_cancel(monkeypatch) -> None:
    views, calls = load_views(monkeypatch)
    runtime = FakeRuntime()
    runtime.kodi.scan_state = {
        "token": "scan-1",
        "kind": "manual",
        "state": "running",
        "pictures_seen": 12,
    }
    FakeDialog.responses = [True]
    ui = views.PluginUI(runtime, "plugin://plugin.image.mypicsdb3", 7)

    ui.dispatch(views.Request("action/stop-scan", {}))

    assert runtime.kodi.scan_cancel_requests == 1
    assert runtime.kodi.notifications[-1] == ("Stopping scan", False)
    assert calls.builtins == []


def test_folder_route_without_id_finishes_cleanly(monkeypatch) -> None:
    views, calls = load_views(monkeypatch)
    runtime = FakeRuntime()
    ui = views.PluginUI(runtime, "plugin://plugin.image.mypicsdb3", 7)

    ui.dispatch(views.Request("folder", {}))

    assert calls.ended is True
    assert calls.content == "images"
    assert calls.items == []
    assert runtime.kodi.notifications[-1] == (
        "The album could not be opened",
        True,
    )


def test_main_menu_editor_persists_hidden_nodes(monkeypatch) -> None:
    views, calls = load_views(monkeypatch)
    runtime = FakeRuntime()
    FakeDialog.multiselect_responses = [[0, 8]]
    ui = views.PluginUI(runtime, "plugin://plugin.image.mypicsdb3", 7)

    ui.dispatch(views.Request("action/configure-menu", {}))

    assert runtime.kodi.addon.getSetting("hidden_main_menu_nodes") == (
        "recent_added|random_memories|recent_albums|random_albums|on_this_day|"
        "on_this_day_random|videos|cameras|keywords|favorites|rated|geotagged"
    )
    assert runtime.kodi.notifications == [("Add-on menu saved", False)]
    assert calls.builtins[-1] == "Container.Refresh"


def test_rating_policy_is_visible_and_can_be_temporarily_bypassed(monkeypatch) -> None:
    views, calls = load_views(monkeypatch)
    runtime = FakeRuntime()
    runtime.kodi.settings.minimum_rating_policy = "3"
    ui = views.PluginUI(runtime, "plugin://plugin.image.mypicsdb3", 7)

    ui.dispatch(views.Request("", {}))

    assert runtime.catalog.rating_policy == "3"
    assert calls.items[0][1].label == "Minimum rating: 3+"
    assert calls.items[1][1].label == "Show all pictures temporarily"
    assert calls.items[1][0] == "plugin://plugin.image.mypicsdb3/?rating_policy=all"
    assert any(
        url == "plugin://plugin.image.mypicsdb3/recent-taken"
        for url, _item, _is_folder in calls.items
    )

    ui.dispatch(views.Request("", {"rating_policy": "all"}))

    assert runtime.catalog.rating_policy == "all"
    assert calls.items[1][1].label == "Use configured rating filter"
    assert calls.items[1][0] == "plugin://plugin.image.mypicsdb3/"
    assert any(
        url == "plugin://plugin.image.mypicsdb3/recent-taken?rating_policy=all"
        for url, _item, _is_folder in calls.items
    )

    ui.dispatch(views.Request("recent-taken", {"rating_policy": "all"}))
    assert calls.category == "Recently taken  [COLOR=grey](Temporary: all pictures)[/COLOR]"


def test_snapshot_action_preserves_temporary_all_pictures_rating_policy(monkeypatch) -> None:
    views, calls = load_views(monkeypatch)
    runtime = FakeRuntime()
    runtime.kodi.settings.minimum_rating_policy = "3"
    ui = views.PluginUI(runtime, "plugin://plugin.image.mypicsdb3", 7)

    ui.dispatch(
        views.Request(
            "search",
            {"q": "summer", "rating_policy": "all"},
        )
    )

    snapshot_urls = [
        url for url, item, _folder in calls.items
        if item.label == "Save current results as collection"
    ]
    assert snapshot_urls == [
        "plugin://plugin.image.mypicsdb3/action/snapshot-results?"
        "scope=search&q=summer&rating_policy=all"
    ]


def test_export_action_preserves_temporary_all_pictures_rating_policy(monkeypatch) -> None:
    views, calls = load_views(monkeypatch)
    runtime = FakeRuntime()
    runtime.kodi.settings.minimum_rating_policy = "3"
    ui = views.PluginUI(runtime, "plugin://plugin.image.mypicsdb3", 7)

    ui.dispatch(
        views.Request(
            "search",
            {"q": "summer", "rating_policy": "all"},
        )
    )

    export_urls = [
        url for url, item, _folder in calls.items
        if item.label == "Export current results"
    ]
    assert export_urls == [
        "plugin://plugin.image.mypicsdb3/action/export-results?"
        "scope=search&q=summer&rating_policy=all"
    ]


def test_global_search_prompts_normalizes_and_preserves_pagination(monkeypatch) -> None:
    views, calls = load_views(monkeypatch)
    runtime = FakeRuntime()
    runtime.kodi.settings.browser_page_size = 1
    FakeDialog.input_responses = [" ÅLAND  Sommar! "]
    ui = views.PluginUI(runtime, "plugin://plugin.image.mypicsdb3", 7)

    ui.dispatch(views.Request("search", {}))

    assert calls.category == "Search results: åland sommar"
    assert calls.content == "images"
    assert len(runtime.catalog.query_requests) == 1
    query, limit, offset = runtime.catalog.query_requests[0]
    assert (limit, offset) == (1, 0)
    assert query.root.children[0].field == "text"
    assert query.root.children[0].operator == "contains_tokens"
    assert query.root.children[0].value.tokens == ("åland", "sommar")
    assert calls.items[0][0] == (
        "plugin://plugin.image.mypicsdb3/action/save-search?q=%C3%A5land+sommar"
    )
    assert calls.items[1][0] == (
        "plugin://plugin.image.mypicsdb3/action/snapshot-results?"
        "scope=search&q=%C3%A5land+sommar"
    )
    assert calls.items[2][0] == (
        "plugin://plugin.image.mypicsdb3/action/export-results?"
        "scope=search&q=%C3%A5land+sommar"
    )
    assert calls.items[4][0] == (
        "plugin://plugin.image.mypicsdb3/search?offset=1&limit=1&q=%C3%A5land+sommar"
    )

    FakeDialog.input_responses = []
    ui.dispatch(
        views.Request(
            "search",
            {"q": "åland sommar", "offset": "1", "limit": "1"},
        )
    )
    assert len(runtime.catalog.query_requests) == 2
    assert runtime.catalog.query_requests[1][1:] == (1, 1)


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


def test_browser_views_use_default_view_but_widgets_keep_skin_layout(monkeypatch) -> None:
    views, calls = load_views(monkeypatch)
    runtime = FakeRuntime()
    runtime.kodi.settings.album_view_mode = 54
    ui = views.PluginUI(runtime, "plugin://plugin.image.mypicsdb3", 7)

    ui.dispatch(views.Request("recent-taken", {}))
    assert calls.builtins.count("Container.SetViewMode(54)") == 1

    calls.builtins.clear()
    ui.folder(3, {})
    assert calls.focus_id == 54
    assert calls.builtins.count("Container.SetViewMode(54)") <= 1
    assert len(calls.items) == 1

    calls.builtins.clear()
    ui.dispatch(views.Request("recent-taken", {"widget": "1"}))
    assert calls.builtins == []


def test_empty_picture_result_does_not_force_a_view_mode(monkeypatch) -> None:
    views, calls = load_views(monkeypatch)
    runtime = FakeRuntime()
    runtime.kodi.settings.album_view_mode = 500
    ui = views.PluginUI(runtime, "plugin://plugin.image.mypicsdb3", 7)

    ui.finish([], content="images", category="Empty album", view_mode=500)

    assert calls.builtins == []
    assert calls.sleeps == []


def test_search_waits_for_picture_container_before_setting_view(monkeypatch) -> None:
    views, calls = load_views(monkeypatch)
    runtime = FakeRuntime()
    runtime.kodi.settings.album_view_mode = 500
    ui = views.PluginUI(runtime, "plugin://plugin.image.mypicsdb3", 7)

    calls.info_label_sequences = {
        "Container.PluginCategory": [
            "MyPicsDB 3",
            "MyPicsDB 3",
            "Search results: torrevieja",
        ],
        "Container.Content": ["files", "files", "images"],
    }
    ui.dispatch(views.Request("search", {"q": "torrevieja"}))

    assert calls.builtins == ["Container.SetViewMode(500)"]
    assert calls.sleeps and all(value == 50 for value in calls.sleeps)

    calls.builtins.clear()
    calls.sleeps.clear()
    ui.dispatch(views.Request("", {}))
    assert calls.category == "MyPicsDB 3"
    assert calls.content == "files"
    assert calls.builtins == []
    assert calls.sleeps == []


def test_home_random_seed_stays_stable_until_a_generation_changes(
    monkeypatch,
) -> None:
    views, _calls = load_views(monkeypatch)
    runtime = FakeRuntime()
    ui = views.PluginUI(runtime, "plugin://plugin.image.mypicsdb3", 7)
    params = {
        "widget": "1",
        "home": "1",
        "generation": "12",
        "random_generation": "7",
    }

    seed = ui._home_random_seed(params, "on-this-day-random")

    assert seed == ui._home_random_seed(params, "on-this-day-random")
    assert seed != ui._home_random_seed(
        {**params, "random_generation": "8"}, "on-this-day-random"
    )
    assert seed != ui._home_random_seed(
        {**params, "generation": "13"}, "on-this-day-random"
    )
    runtime.kodi.random_home_session_token = "test-session-b"
    assert seed != ui._home_random_seed(params, "on-this-day-random")
    assert ui._home_random_seed({"widget": "1"}, "on-this-day-random") is None


def test_random_on_this_day_route_uses_random_catalog_query(monkeypatch) -> None:
    views, calls = load_views(monkeypatch)
    runtime = FakeRuntime()
    requested = []
    runtime.catalog.random_on_this_day = (
        lambda month, day, current_year, limit: requested.append(
            (month, day, current_year, limit)
        ) or runtime.catalog.recent_taken(limit, 0)
    )
    ui = views.PluginUI(runtime, "plugin://plugin.image.mypicsdb3", 7)

    ui.dispatch(views.Request("on-this-day-random", {"widget": "1", "limit": "9"}))

    assert requested and requested[0][3] == 9
    assert calls.category == "On this day - random"
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

    def enable_favorites(
        items, _labels, _saved_names, _text, collection_names=None
    ):
        from mypicsdb3.preferences import HomeLayoutItem

        return tuple(
            HomeLayoutItem(
                kind=item.kind,
                key=item.key,
                saved_search_id=item.saved_search_id,
                enabled=item.enabled or item.key == "favorites",
                mode=item.mode,
            )
            for item in items
        )

    monkeypatch.setattr(views, "show_smart_home_layout_editor", enable_favorites)
    ui.action("action/configure-home", {})

    assert runtime.kodi.addon.settings["home_row_7"] == "favorites"
    assert "favorites" in runtime.kodi.addon.settings["home_layout"]
    assert "ReloadSkin()" not in calls.builtins


def test_album_items_do_not_duplicate_global_save_view_context_action(monkeypatch) -> None:
    views, calls = load_views(monkeypatch)
    ui = views.PluginUI(FakeRuntime(), "plugin://plugin.image.mypicsdb3", 7)

    ui.folder(2, {})

    assert calls.items
    _, picture, _ = calls.items[0]
    assert all(
        label != "Save current view as album default"
        for label, _command in picture.context
    )



def test_picture_widget_item_exposes_direct_show_picture_path(monkeypatch) -> None:
    views, calls = load_views(monkeypatch)
    runtime = FakeRuntime()
    ui = views.PluginUI(runtime, "plugin://plugin.image.mypicsdb3", 7)

    ui.dispatch(views.Request("recent-taken", {"widget": "1"}))

    url, item, is_folder = calls.items[0]
    assert url == "smb://server/photos/image.jpg"
    assert item.properties["MyPicsDB3.MediaType"] == "picture"
    assert item.properties["MyPicsDB3.WidgetPath"] == url
    assert is_folder is False

def test_video_node_and_video_list_item_are_playable_when_enabled(monkeypatch) -> None:
    views, calls = load_views(monkeypatch)
    runtime = FakeRuntime()
    runtime.kodi.settings.include_videos = True
    video = dict(runtime.catalog.recent_taken(1)[0])
    video.update(
        {
            "id": 9,
            "uri": "smb://server/photos/clip.mp4",
            "thumb_uri": "smb://server/photos/clip.mp4",
            "filename": "clip.mp4",
            "media_type": "video",
            "mime_type": "video/mp4",
        }
    )
    runtime.catalog.videos = lambda limit, offset=0: [video]
    ui = views.PluginUI(runtime, "plugin://plugin.image.mypicsdb3", 7)

    ui.root()
    urls = [url for url, _item, _folder in calls.items]
    assert "plugin://plugin.image.mypicsdb3/videos" in urls

    ui.dispatch(views.Request("videos", {}))
    url, item, is_folder = calls.items[0]
    assert url.endswith("clip.mp4")
    assert item.properties["IsPlayable"] == "true"
    assert item.properties["MyPicsDB3.MediaType"] == "video"
    assert item.properties["MyPicsDB3.WidgetPath"] == "smb://server/photos/clip.mp4"
    assert item.art["thumb"] == (
        "image://video@smb%3A%2F%2Fserver%2Fphotos%2Fclip.mp4/"
    )
    assert item.art["icon"] == item.art["thumb"]
    assert "video" in item.info
    assert is_folder is False



def test_video_item_keeps_explicit_image_thumbnail(monkeypatch) -> None:
    views, calls = load_views(monkeypatch)
    runtime = FakeRuntime()
    runtime.kodi.settings.include_videos = True
    video = dict(runtime.catalog.recent_taken(1)[0])
    video.update(
        {
            "id": 9,
            "uri": "smb://server/photos/clip.mp4",
            "thumb_uri": "smb://server/photos/clip-thumb.jpg",
            "filename": "clip.mp4",
            "media_type": "video",
            "mime_type": "video/mp4",
        }
    )
    runtime.catalog.videos = lambda limit, offset=0: [video]
    ui = views.PluginUI(runtime, "plugin://plugin.image.mypicsdb3", 7)

    ui.dispatch(views.Request("videos", {}))

    _url, item, _is_folder = calls.items[0]
    assert item.art["thumb"] == "image://smb%3A%2F%2Fserver%2Fphotos%2Fclip-thumb.jpg/"



def test_video_only_folder_uses_generated_frame_art(monkeypatch) -> None:
    views, _calls = load_views(monkeypatch)
    runtime = FakeRuntime()
    runtime.kodi.settings.include_videos = True
    ui = views.PluginUI(runtime, "plugin://plugin.image.mypicsdb3", 7)

    _url, item, is_folder = ui._folder_item(
        {
            "id": 12,
            "source_id": 7,
            "name": "Home videos",
            "picture_count": 3,
            "representative_uri": "nfs://nas/Home videos/clip.vcamera",
            "representative_thumb": "nfs://nas/Home videos/clip.vcamera",
            "representative_media_type": "video",
        }
    )

    assert item.art["thumb"] == (
        "image://video@nfs%3A%2F%2Fnas%2FHome%20videos%2Fclip.vcamera/"
    )
    assert item.art["poster"] == item.art["thumb"]
    assert item.art["landscape"] == item.art["thumb"]
    assert item.properties["MyPicsDB3.MediaType"] == "folder"
    assert item.properties["MyPicsDB3.WidgetPath"] == (
        "plugin://plugin.image.mypicsdb3/folder?id=12"
    )
    assert is_folder is True


def test_widget_items_publish_titles_for_estuary_poster_rows(monkeypatch) -> None:
    views, calls = load_views(monkeypatch)

    class WidgetVideoTag:
        def __init__(self):
            self.title = None

        def setTitle(self, value):
            self.title = value

        def setDateAdded(self, _value):
            pass

    class WidgetListItem(FakeListItem):
        def __init__(self, label="", path=""):
            super().__init__(label, path)
            self.video_tag = WidgetVideoTag()
            self.video_tag_requests = 0

        def getVideoInfoTag(self):
            self.video_tag_requests += 1
            return self.video_tag

    views.xbmcgui.ListItem = WidgetListItem
    runtime = FakeRuntime()
    ui = views.PluginUI(runtime, "plugin://plugin.image.mypicsdb3", 7)

    ui.dispatch(views.Request("recent-taken", {}))

    _url, picture, _is_folder = calls.items[0]
    assert picture.video_tag_requests == 0
    assert picture.video_tag.title is None
    assert picture.properties["MyPicsDB3.WidgetLabel"] == "image.jpg"

    _url, album, is_folder = ui._folder_item(
        {
            "id": 12,
            "source_id": 7,
            "name": "Summer album",
            "picture_count": 3,
            "representative_uri": "smb://server/photos/cover.jpg",
            "representative_thumb": "smb://server/photos/cover.jpg",
            "representative_media_type": "picture",
        }
    )
    assert album.video_tag_requests == 1
    assert album.video_tag.title == "Summer album  [COLOR=grey](3)[/COLOR]"
    assert album.properties["MyPicsDB3.WidgetLabel"] == album.label
    assert is_folder is True


def test_info_rows_do_not_publish_video_info_tags(monkeypatch) -> None:
    views, _calls = load_views(monkeypatch)

    class InfoVideoTag:
        def setTitle(self, _value):
            raise AssertionError("information rows must not create a VideoInfoTag")

    class InfoListItem(FakeListItem):
        def __init__(self, label="", path=""):
            super().__init__(label, path)
            self.video_tag_requests = 0

        def getVideoInfoTag(self):
            self.video_tag_requests += 1
            return InfoVideoTag()

    views.xbmcgui.ListItem = InfoListItem
    ui = views.PluginUI(FakeRuntime(), "plugin://plugin.image.mypicsdb3", 7)

    url, item, is_folder = ui.add_info("MyPicsDB 3 version: 0.8.14")

    assert url == ""
    assert item.video_tag_requests == 0
    assert item.properties["IsPlayable"] == "false"
    assert item.properties["MyPicsDB3.MediaType"] == "info"
    assert item.properties["MyPicsDB3.WidgetLabel"] == "MyPicsDB 3 version: 0.8.14"
    assert is_folder is False


def test_action_rows_do_not_publish_video_info_tags(monkeypatch) -> None:
    views, _calls = load_views(monkeypatch)

    class ActionVideoTag:
        def setTitle(self, _value):
            raise AssertionError("action rows must not create a VideoInfoTag")

    class ActionListItem(FakeListItem):
        def __init__(self, label="", path=""):
            super().__init__(label, path)
            self.video_tag_requests = 0

        def getVideoInfoTag(self):
            self.video_tag_requests += 1
            return ActionVideoTag()

    views.xbmcgui.ListItem = ActionListItem
    ui = views.PluginUI(FakeRuntime(), "plugin://plugin.image.mypicsdb3", 7)

    _url, item, is_folder = ui.add_action(
        "Play collection slideshow",
        "action/start-slideshow",
        scope="collection",
        id=9,
    )

    assert item.video_tag_requests == 0
    assert item.properties["IsPlayable"] == "false"
    assert item.properties["MyPicsDB3.WidgetLabel"] == "Play collection slideshow"
    assert is_folder is False


def test_video_items_prefer_info_tag_video_setters(monkeypatch) -> None:
    views, calls = load_views(monkeypatch)

    class FakeVideoTag:
        def __init__(self):
            self.title = None
            self.date_added = None

        def setTitle(self, value):
            self.title = value

        def setDateAdded(self, value):
            self.date_added = value

    class ModernListItem(FakeListItem):
        def __init__(self, label="", path=""):
            super().__init__(label, path)
            self.video_tag = FakeVideoTag()

        def getVideoInfoTag(self):
            return self.video_tag

        def setInfo(self, media_type, info):
            if media_type == "video":
                raise AssertionError("deprecated video setInfo must not be used")
            super().setInfo(media_type, info)

    views.xbmcgui.ListItem = ModernListItem
    runtime = FakeRuntime()
    runtime.kodi.settings.include_videos = True
    video = dict(runtime.catalog.recent_taken(1)[0])
    video.update(
        {
            "id": 2,
            "uri": "smb://server/photos/clip.mp4",
            "filename": "clip.mp4",
            "media_type": "video",
            "taken_at": "2026-07-28 10:00:00",
        }
    )
    runtime.catalog.videos = lambda limit, offset=0: [video]
    ui = views.PluginUI(runtime, "plugin://plugin.image.mypicsdb3", 7)

    ui.dispatch(views.Request("videos", {}))

    _url, item, _is_folder = calls.items[0]
    assert item.video_tag.title == "clip.mp4"
    assert item.video_tag.date_added == "2026-07-28 10:00:00"



def test_direct_slideshow_action_releases_media_request_before_work(monkeypatch) -> None:
    views, calls = load_views(monkeypatch)
    runtime = FakeRuntime()
    runtime.catalog.pictures_in_collection = lambda collection_id, limit, offset=0: []
    ui = views.PluginUI(runtime, "plugin://plugin.image.mypicsdb3", 7)

    ui.dispatch(
        views.Request(
            "action/start-slideshow",
            {"scope": "collection", "id": "9"},
        )
    )

    assert len(calls.resolved_urls) == 1
    handle, succeeded, item = calls.resolved_urls[0]
    assert handle == 7
    assert succeeded is False
    assert isinstance(item, FakeListItem)
    assert runtime.kodi.notifications[-1] == ("No media to play", False)


def test_runplugin_slideshow_action_does_not_resolve_negative_handle(monkeypatch) -> None:
    views, calls = load_views(monkeypatch)
    runtime = FakeRuntime()
    runtime.catalog.pictures_in_collection = lambda collection_id, limit, offset=0: []
    ui = views.PluginUI(runtime, "plugin://plugin.image.mypicsdb3", -1)

    ui.dispatch(
        views.Request(
            "action/start-slideshow",
            {"scope": "collection", "id": "9"},
        )
    )

    assert calls.resolved_urls == []


def test_parallel_slideshow_start_is_rejected_before_playlist_work(monkeypatch) -> None:
    views, calls = load_views(monkeypatch)
    runtime = FakeRuntime()
    runtime.kodi.acquire_slideshow_start = lambda: None
    released = []
    runtime.kodi.release_slideshow_start = released.append
    ui = views.PluginUI(runtime, "plugin://plugin.image.mypicsdb3", 7)

    ui.dispatch(
        views.Request(
            "action/start-slideshow",
            {"scope": "folder-tree", "id": "12"},
        )
    )

    assert calls.rpc_requests == []
    assert calls.builtins == []
    assert released == []
    assert runtime.kodi.notifications == [
        ("A slideshow is already being prepared", False)
    ]

def test_picture_only_folder_tree_uses_kodi_native_recursive_slideshow(monkeypatch) -> None:
    views, calls = load_views(monkeypatch)
    runtime = FakeRuntime()
    runtime.catalog.get_folder = lambda folder_id: {
        "id": folder_id,
        "source_id": 4,
        "uri": "smb://server/photos/Trip, summer/",
        "name": "Trip, summer",
    }
    ui = views.PluginUI(runtime, "plugin://plugin.image.mypicsdb3", 7)

    ui.dispatch(
        views.Request(
            "action/start-slideshow",
            {"scope": "folder-tree", "id": "12"},
        )
    )

    assert calls.builtins == [
        'SlideShow("smb://server/photos/Trip, summer/",recursive,notrandom)'
    ]
    assert runtime.kodi.mixed_slideshow_updates == [False]
    assert any(
        "route=native-picture" in message
        for message in runtime.kodi.info_messages
    )


def test_folder_tree_with_video_uses_explicit_mixed_playlist(monkeypatch) -> None:
    views, calls = load_views(monkeypatch)
    runtime = FakeRuntime()

    def confirmed_picture_player(payload):
        request = json.loads(payload)
        calls.rpc_requests.append(request)
        method = request["method"]
        if method == "Player.GetActivePlayers":
            result = [{"playerid": 2, "type": "picture"}]
        elif method == "Player.GetItem":
            result = {"item": {"file": "smb://server/photos/image.jpg"}}
        else:
            result = "OK"
        return json.dumps({"jsonrpc": "2.0", "id": 1, "result": result})

    views.xbmc.executeJSONRPC = confirmed_picture_player
    rows = runtime.catalog.recent_taken(10)
    rows.append(
        {
            "id": 2,
            "uri": "smb://server/photos/Trip/clip.mp4",
            "media_type": "video",
        }
    )
    runtime.catalog.media_in_folder_tree = lambda folder_id, limit: rows
    ui = views.PluginUI(runtime, "plugin://plugin.image.mypicsdb3", 7)

    ui.dispatch(
        views.Request(
            "action/start-slideshow",
            {"scope": "folder-tree", "id": "12"},
        )
    )

    assert calls.builtins == []
    add_request = next(
        request for request in calls.rpc_requests if request["method"] == "Playlist.Add"
    )
    assert add_request["params"]["item"][-1] == {
        "file": "smb://server/photos/Trip/clip.mp4"
    }
    assert runtime.kodi.mixed_slideshow_updates == [False, True]
    assert any(
        "route=mixed-playlist" in message and "videos=1" in message
        for message in runtime.kodi.info_messages
    )


def test_photo_only_database_slideshow_keeps_video_monitor_inactive(monkeypatch) -> None:
    views, _calls = load_views(monkeypatch)
    runtime = FakeRuntime()
    ui = views.PluginUI(runtime, "plugin://plugin.image.mypicsdb3", 7)

    ui.dispatch(
        views.Request(
            "action/start-slideshow",
            {"scope": "recent-taken", "start": "1"},
        )
    )

    assert runtime.kodi.mixed_slideshow_updates == [False]


def test_database_slideshow_with_video_arms_video_monitor(monkeypatch) -> None:
    views, calls = load_views(monkeypatch)
    runtime = FakeRuntime()

    def confirmed_picture_player(payload):
        request = json.loads(payload)
        calls.rpc_requests.append(request)
        method = request["method"]
        if method == "Player.GetActivePlayers":
            result = [{"playerid": 2, "type": "picture"}]
        elif method == "Player.GetItem":
            result = {"item": {"file": "smb://server/photos/image.jpg"}}
        else:
            result = "OK"
        return json.dumps({"jsonrpc": "2.0", "id": 1, "result": result})

    views.xbmc.executeJSONRPC = confirmed_picture_player
    rows = runtime.catalog.recent_taken(10)
    rows.append(
        {
            "id": 2,
            "uri": "smb://server/photos/clip.mp4",
            "media_type": "video",
        }
    )
    runtime.catalog.recent_taken = lambda limit, offset=0: rows
    ui = views.PluginUI(runtime, "plugin://plugin.image.mypicsdb3", 7)

    ui.dispatch(
        views.Request(
            "action/start-slideshow",
            {"scope": "recent-taken", "start": "1"},
        )
    )

    assert runtime.kodi.mixed_slideshow_updates == [False, True]


def test_database_slideshow_sanitizes_rows_and_recalculates_start_position(monkeypatch) -> None:
    views, calls = load_views(monkeypatch)
    runtime = FakeRuntime()
    rows = [
        {
            "id": 1,
            "uri": "smb://server/album-a/first.jpg",
            "media_type": "picture",
        },
        {
            "id": 2,
            "uri": "",
            "media_type": "picture",
        },
        {
            "id": 3,
            "uri": "smb://server/album-a/first.jpg",
            "media_type": "picture",
        },
        {
            "id": 4,
            "uri": "smb://server/album-b/clip.mp4",
            "media_type": "video",
        },
    ]
    runtime.catalog.recent_taken = lambda limit, offset=0: rows
    ui = views.PluginUI(runtime, "plugin://plugin.image.mypicsdb3", 7)

    ui.dispatch(
        views.Request(
            "action/start-slideshow",
            {"scope": "recent-taken", "start": "4"},
        )
    )

    add_request = next(
        request for request in calls.rpc_requests if request["method"] == "Playlist.Add"
    )
    open_requests = [
        request for request in calls.rpc_requests if request["method"] == "Player.Open"
    ]
    assert add_request["params"]["item"] == [
        {"file": "smb://server/album-a/first.jpg"},
        {"file": "smb://server/album-b/clip.mp4"},
    ]
    assert [request["params"]["item"]["position"] for request in open_requests] == [1]
    assert runtime.kodi.mixed_slideshow_updates == [False, True]


def test_folder_tree_falls_back_to_native_when_picture_playlist_opens_as_video(
    monkeypatch,
) -> None:
    views, calls = load_views(monkeypatch)
    runtime = FakeRuntime()
    rows = runtime.catalog.recent_taken(10)
    rows.append(
        {
            "id": 2,
            "uri": "smb://server/photos/Trip/clip.mp4",
            "media_type": "video",
        }
    )
    runtime.catalog.media_in_folder_tree = lambda folder_id, limit: rows
    runtime.kodi.picture_playlist_compatibility_value = None

    def mismatched_player(payload):
        request = json.loads(payload)
        calls.rpc_requests.append(request)
        method = request["method"]
        if method == "Player.GetActivePlayers":
            result = [{"playerid": 1, "type": "video"}]
        elif method == "Player.GetItem":
            result = {"item": {"file": "smb://server/photos/image.jpg"}}
        else:
            result = "OK"
        return json.dumps({"jsonrpc": "2.0", "id": 1, "result": result})

    views.xbmc.executeJSONRPC = mismatched_player
    ui = views.PluginUI(runtime, "plugin://plugin.image.mypicsdb3", 7)

    ui.dispatch(
        views.Request(
            "action/start-slideshow",
            {"scope": "folder-tree", "id": "12"},
        )
    )

    assert calls.builtins == [
        'SlideShow("smb://server/photos/Summer/",recursive,notrandom)'
    ]
    assert any(
        request["method"] == "Player.Stop" for request in calls.rpc_requests
    )
    assert runtime.kodi.mixed_slideshow_updates == [False, False]
    assert any(
        "route=native-mixed-fallback" in message
        for message in runtime.kodi.info_messages
    )


def test_folder_tree_falls_back_when_picture_playlist_probe_is_inconclusive(
    monkeypatch,
) -> None:
    views, calls = load_views(monkeypatch)
    runtime = FakeRuntime()
    rows = runtime.catalog.recent_taken(10)
    rows.append(
        {
            "id": 2,
            "uri": "smb://server/photos/Trip/clip.mp4",
            "media_type": "video",
        }
    )
    runtime.catalog.media_in_folder_tree = lambda folder_id, limit: rows
    runtime.kodi.picture_playlist_compatibility_value = None

    def inconclusive_player(payload):
        request = json.loads(payload)
        calls.rpc_requests.append(request)
        result = [] if request["method"] == "Player.GetActivePlayers" else "OK"
        return json.dumps({"jsonrpc": "2.0", "id": 1, "result": result})

    views.xbmc.executeJSONRPC = inconclusive_player
    ui = views.PluginUI(runtime, "plugin://plugin.image.mypicsdb3", 7)

    ui.dispatch(
        views.Request(
            "action/start-slideshow",
            {"scope": "folder-tree", "id": "12"},
        )
    )

    assert calls.builtins == [
        'SlideShow("smb://server/photos/Summer/",recursive,notrandom)'
    ]
    assert runtime.kodi.picture_playlist_compatibility_updates == [False]
    assert any(
        "reason=picture-playlist-unconfirmed" in message
        for message in runtime.kodi.info_messages
    )
    add_requests = [
        request for request in calls.rpc_requests if request["method"] == "Playlist.Add"
    ]
    assert len(add_requests) == 1


def test_cross_folder_mixed_slideshow_falls_back_to_pictures_only(monkeypatch) -> None:
    views, calls = load_views(monkeypatch)
    runtime = FakeRuntime()
    rows = runtime.catalog.recent_taken(10)
    rows.append(
        {
            "id": 2,
            "uri": "smb://server/other/clip.mp4",
            "media_type": "video",
        }
    )
    runtime.catalog.recent_taken = lambda limit, offset=0: rows
    runtime.kodi.picture_playlist_compatibility_value = None

    def mismatched_player(payload):
        request = json.loads(payload)
        calls.rpc_requests.append(request)
        method = request["method"]
        if method == "Player.GetActivePlayers":
            result = [{"playerid": 1, "type": "video"}]
        elif method == "Player.GetItem":
            result = {"item": {"file": "smb://server/photos/image.jpg"}}
        else:
            result = "OK"
        return json.dumps({"jsonrpc": "2.0", "id": 1, "result": result})

    views.xbmc.executeJSONRPC = mismatched_player
    ui = views.PluginUI(runtime, "plugin://plugin.image.mypicsdb3", 7)

    ui.dispatch(
        views.Request(
            "action/start-slideshow",
            {"scope": "recent-taken", "start": "1"},
        )
    )

    add_requests = [
        request for request in calls.rpc_requests if request["method"] == "Playlist.Add"
    ]
    assert add_requests == [
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "Playlist.Add",
            "params": {
                "playlistid": 2,
                "item": [
                    {"file": "smb://server/photos/image.jpg"},
                    {"file": "smb://server/other/clip.mp4"},
                ],
            },
        }
    ]
    assert runtime.kodi.mixed_slideshow_updates == [False, False]
    assert runtime.kodi.picture_playlist_compatibility_updates == [False]
    assert runtime.kodi.notifications == [
        (
            "This Kodi installation cannot play a cross-folder picture "
            "slideshow. Open an album and start the slideshow there.",
            True,
        )
    ]


def test_failed_database_slideshow_does_not_leave_video_monitor_armed(monkeypatch) -> None:
    views, _calls = load_views(monkeypatch)
    runtime = FakeRuntime()
    rows = runtime.catalog.recent_taken(10)
    rows.append(
        {
            "id": 2,
            "uri": "smb://server/album-b/clip.mp4",
            "media_type": "video",
        }
    )
    runtime.catalog.recent_taken = lambda limit, offset=0: rows

    def fail_start(*args, **kwargs):
        raise views.SlideshowError("Kodi rejected playlist")

    monkeypatch.setattr(views, "start_mixed_slideshow", fail_start)
    ui = views.PluginUI(runtime, "plugin://plugin.image.mypicsdb3", 7)

    ui.dispatch(
        views.Request(
            "action/start-slideshow",
            {"scope": "recent-taken", "start": "2"},
        )
    )

    assert runtime.kodi.mixed_slideshow_updates == [False]
    assert runtime.kodi.notifications == [
        ("Could not start slideshow: Kodi rejected playlist", True)
    ]


def test_saved_search_ui_saves_lists_opens_and_paginates_by_id(monkeypatch) -> None:
    views, calls = load_views(monkeypatch)
    runtime = FakeRuntime()
    runtime.kodi.settings.browser_page_size = 1
    query = views.build_global_search_request("åland sommar").query
    saved = types.SimpleNamespace(id=42, name="Sommarresor", query=query)
    runtime.catalog.saved_search_rows = [
        {
            "id": 42,
            "name": "Sommarresor",
            "query_version": 1,
            "created_at": "2026-07-27",
            "updated_at": "2026-07-27",
        }
    ]
    runtime.catalog.saved_search_objects[42] = saved
    ui = views.PluginUI(runtime, "plugin://plugin.image.mypicsdb3", 7)

    FakeDialog.input_responses = ["Sommarresor"]
    ui.dispatch(views.Request("action/save-search", {"q": " ÅLAND Sommar! "}))
    assert runtime.catalog.created_saved_searches[0][0] == "Sommarresor"
    assert runtime.catalog.created_saved_searches[0][1].root.children[0].value.text == (
        "åland sommar"
    )
    assert runtime.kodi.notifications[-1] == ("Search saved", False)

    ui.dispatch(views.Request("saved-searches", {}))
    assert calls.category == "Saved searches"
    assert calls.items[0][0] == (
        "plugin://plugin.image.mypicsdb3/saved-search?id=42"
    )
    assert calls.items[0][1].context == [
        (
            "Rename saved search",
            "RunPlugin(plugin://plugin.image.mypicsdb3/action/rename-saved-search?id=42)",
        ),
        (
            "Delete saved search",
            "RunPlugin(plugin://plugin.image.mypicsdb3/action/delete-saved-search?id=42)",
        ),
        (
            "Assign music playlist",
            "RunPlugin(plugin://plugin.image.mypicsdb3/action/assign-music-playlist?type=smart&id=42)",
        ),
    ]
    assert not any(command.startswith("Container.SetViewMode") for command in calls.builtins)

    calls.info_label_sequences = {
        "Container.PluginCategory": ["Saved searches", "Sommarresor"],
        "Container.Content": ["files", "images"],
    }
    ui.dispatch(views.Request("saved-search", {"id": "42"}))
    assert calls.category == "Sommarresor"
    assert calls.focus_id == 55
    assert calls.builtins in ([], ["Container.SetViewMode(55)"])
    assert calls.sleeps[-1:] == [50]
    assert runtime.catalog.query_requests[-1][0] is query
    assert calls.items[0][0] == (
        "plugin://plugin.image.mypicsdb3/action/snapshot-results?"
        "scope=saved-search&id=42"
    )
    assert calls.items[1][0] == (
        "plugin://plugin.image.mypicsdb3/action/export-results?"
        "scope=saved-search&id=42"
    )
    assert calls.items[3][0] == (
        "plugin://plugin.image.mypicsdb3/saved-search?offset=1&limit=1&id=42"
    )
    assert "q=" not in calls.items[1][0]
    assert "query" not in calls.items[1][0]
    slideshow_commands = [
        command for label, command in calls.items[2][1].context
        if label == "Play slideshow from here"
    ]
    assert slideshow_commands == [
        "RunPlugin(plugin://plugin.image.mypicsdb3/action/start-slideshow?"
        "id=42&scope=saved-search&start=1)"
    ]


def test_saved_search_ui_renames_and_deletes_after_confirmation(monkeypatch) -> None:
    views, calls = load_views(monkeypatch)
    runtime = FakeRuntime()
    query = views.build_global_search_request("sommar").query
    runtime.catalog.saved_search_objects[7] = types.SimpleNamespace(
        id=7,
        name="Sommar",
        query=query,
    )
    ui = views.PluginUI(runtime, "plugin://plugin.image.mypicsdb3", 7)

    FakeDialog.input_responses = ["Semester"]
    ui.dispatch(views.Request("action/rename-saved-search", {"id": "7"}))
    assert runtime.catalog.renamed_saved_searches == [(7, "Semester")]
    assert runtime.kodi.notifications[-1] == ("Saved search renamed", False)
    assert calls.builtins[-1] == "Container.Refresh"

    FakeDialog.responses = [True]
    ui.dispatch(views.Request("action/delete-saved-search", {"id": "7"}))
    assert runtime.catalog.deleted_saved_searches == [7]
    assert runtime.kodi.notifications[-1] == ("Saved search deleted", False)
    assert calls.builtins[-1] == "Container.Refresh"


def test_video_only_slideshow_uses_video_playlist(monkeypatch) -> None:
    views, calls = load_views(monkeypatch)
    runtime = FakeRuntime()
    rows = [
        {
            "id": 7,
            "uri": "smb://server/photos/a.mp4",
            "media_type": "video",
        },
        {
            "id": 8,
            "uri": "smb://server/photos/b.mp4",
            "media_type": "video",
        },
    ]
    runtime.catalog.media_in_folder_tree = lambda folder_id, limit: rows
    ui = views.PluginUI(runtime, "plugin://plugin.image.mypicsdb3", 7)

    ui.dispatch(
        views.Request(
            "action/start-slideshow",
            {"scope": "folder-tree", "id": "12", "start": "8"},
        )
    )

    add_request = next(
        request for request in calls.rpc_requests if request["method"] == "Playlist.Add"
    )
    open_request = next(
        request for request in calls.rpc_requests if request["method"] == "Player.Open"
    )
    assert add_request["params"]["playlistid"] == 1
    assert open_request["params"]["item"] == {"playlistid": 1, "position": 1}
    assert runtime.kodi.mixed_slideshow_updates == [False]
    assert any("route=video-playlist" in message for message in runtime.kodi.info_messages)


def test_cached_incompatible_folder_tree_skips_picture_playlist_probe(monkeypatch) -> None:
    views, calls = load_views(monkeypatch)
    runtime = FakeRuntime()
    runtime.kodi.picture_playlist_compatibility_value = False
    rows = runtime.catalog.recent_taken(10)
    rows.append(
        {
            "id": 2,
            "uri": "smb://server/photos/Trip/clip.mp4",
            "media_type": "video",
        }
    )
    runtime.catalog.media_in_folder_tree = lambda folder_id, limit: rows
    ui = views.PluginUI(runtime, "plugin://plugin.image.mypicsdb3", 7)

    ui.dispatch(
        views.Request(
            "action/start-slideshow",
            {"scope": "folder-tree", "id": "12"},
        )
    )

    assert not any(
        request["method"] in {"Playlist.Clear", "Playlist.Add", "Player.Open"}
        for request in calls.rpc_requests
    )
    assert calls.builtins == [
        'SlideShow("smb://server/photos/Summer/",recursive,notrandom)'
    ]
    assert any(
        "reason=cached-picture-playlist-incompatible" in message
        for message in runtime.kodi.info_messages
    )


def test_create_smart_collection_saves_validated_query_and_opens_it(monkeypatch) -> None:
    views, calls = load_views(monkeypatch)
    runtime = FakeRuntime()
    query = views.build_global_search_request("sommar").query

    class FakeEditor:
        def __init__(self, catalog, dialog, localize):
            assert catalog is runtime.catalog

        def run(self):
            return types.SimpleNamespace(name="Sommarfavoriter", query=query)

    monkeypatch.setattr(views, "SmartFilterEditor", FakeEditor)
    ui = views.PluginUI(runtime, "plugin://plugin.image.mypicsdb3", 7)

    ui.dispatch(views.Request("action/create-smart-collection", {}))

    assert runtime.catalog.created_saved_searches == [("Sommarfavoriter", query)]
    assert runtime.kodi.notifications[-1] == ("Smart collection saved", False)
    assert calls.builtins[-1] == (
        "Container.Update(plugin://plugin.image.mypicsdb3/saved-search?id=1)"
    )


def test_home_widget_uses_small_limit_and_prioritizes_standard_stills(monkeypatch) -> None:
    views, calls = load_views(monkeypatch)
    runtime = FakeRuntime()
    requested = []
    original_recent_taken = runtime.catalog.recent_taken

    def rows(limit, offset=0):
        requested.append((limit, offset))
        base = original_recent_taken(1)[0]
        result = []
        for number, (extension, media_type) in enumerate(
            (("nef", "picture"), ("mp4", "video"), ("jpg", "picture"), ("heic", "picture")),
            start=1,
        ):
            row = dict(base)
            row.update(
                id=number,
                filename=f"item-{number}.{extension}",
                uri=f"smb://server/photos/item-{number}.{extension}",
                thumb_uri=(f"smb://server/photos/item-{number}.{extension}" if media_type == "picture" else None),
                extension=extension,
                media_type=media_type,
            )
            result.append(row)
        return result

    runtime.catalog.recent_taken = rows
    runtime.kodi.settings.home_widget_limit = 4
    ui = views.PluginUI(runtime, "plugin://plugin.image.mypicsdb3", 7)

    ui.dispatch(views.Request("recent-taken", {"widget": "1", "home": "1"}))

    assert requested == [(16, 0)]
    assert [item.label for _url, item, _folder in calls.items] == [
        "item-3.jpg",
        "item-1.nef",
        "item-4.heic",
        "item-2.mp4",
    ]


def test_home_widget_ignores_stale_url_limit_and_uses_typed_setting(monkeypatch) -> None:
    views, calls = load_views(monkeypatch)
    runtime = FakeRuntime()
    requested = []
    base = runtime.catalog.recent_taken(1)[0]

    def rows(limit, offset=0):
        requested.append((limit, offset))
        result = []
        for number in range(limit):
            row = dict(base)
            row.update(
                id=number + 1,
                filename=f"item-{number + 1}.jpg",
                uri=f"smb://server/photos/item-{number + 1}.jpg",
                thumb_uri=f"smb://server/photos/item-{number + 1}.jpg",
                extension="jpg",
                media_type="picture",
            )
            result.append(row)
        return result

    runtime.catalog.recent_taken = rows
    runtime.kodi.settings.home_widget_limit = 39
    ui = views.PluginUI(runtime, "plugin://plugin.image.mypicsdb3", 7)

    ui.dispatch(
        views.Request(
            "recent-taken",
            {"widget": "1", "home": "1", "limit": "39"},
        )
    )

    assert requested == [(156, 0)]
    assert len(calls.items) == 39
    assert ui._result_limit(
        {"widget": "1", "home": "1", "limit": "10"},
        10,
    ) == 39


def test_picture_info_uses_picture_info_tag_when_available(monkeypatch) -> None:
    views, calls = load_views(monkeypatch)

    class PictureTag:
        def __init__(self):
            self.resolution = None
            self.date = None

        def setResolution(self, width, height):
            self.resolution = (width, height)

        def setDateTimeTaken(self, value):
            self.date = value

    original = views.xbmcgui.ListItem

    class TaggedListItem(original):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self.picture_tag = PictureTag()

        def getPictureInfoTag(self):
            return self.picture_tag

    views.xbmcgui.ListItem = TaggedListItem
    ui = views.PluginUI(FakeRuntime(), "plugin://plugin.image.mypicsdb3", 7)
    ui.dispatch(views.Request("recent-taken", {}))

    item = calls.items[0][1]
    assert item.picture_tag.resolution == (1920, 1080)
    assert item.picture_tag.date == "2020-07-17 12:00:00"
    assert item.info["pictures"]["title"] == "image.jpg"
    assert "resolution" not in item.info["pictures"]


def test_home_slot_route_resolves_builtin_from_persistent_setting(monkeypatch) -> None:
    views, calls = load_views(monkeypatch)
    runtime = FakeRuntime()
    runtime.kodi.addon.setSetting("home_row_1", "recent_taken")
    ui = views.PluginUI(runtime, "plugin://plugin.image.mypicsdb3", 7)

    ui.dispatch(
        views.Request(
            "home-slot",
            {"slot": "1", "widget": "1", "home": "1", "generation": ""},
        )
    )

    assert calls.category == "Recently taken"
    assert calls.items
    assert calls.ended is True


def test_home_slot_route_resolves_smart_and_manual_slots(monkeypatch) -> None:
    views, calls = load_views(monkeypatch)
    runtime = FakeRuntime()
    query = views.build_global_search_request("spain").query
    runtime.catalog.saved_search_objects[42] = types.SimpleNamespace(id=42, name="Spain", query=query)
    runtime.catalog.collection_objects[9] = types.SimpleNamespace(id=9, name="Family picks")
    runtime.catalog.collection_rows = [{"id": 9, "name": "Family picks", "available_count": 1}]
    runtime.kodi.addon.setSetting("home_row_2", "smart")
    runtime.kodi.addon.setSetting("home_smart_id_2", "42")
    runtime.kodi.addon.setSetting("home_row_3", "collection")
    runtime.kodi.addon.setSetting("home_collection_id_3", "9")
    ui = views.PluginUI(runtime, "plugin://plugin.image.mypicsdb3", 7)

    ui.dispatch(views.Request("home-slot", {"slot": "2", "widget": "1", "home": "1"}))
    assert calls.category == "Spain"
    calls.items.clear(); calls.ended=False
    ui.dispatch(views.Request("home-slot", {"slot": "3", "widget": "1", "home": "1"}))
    assert calls.category == "Family picks"
    assert calls.ended is True


def test_home_smart_route_resolves_saved_search_id_from_slot(monkeypatch) -> None:
    views, calls = load_views(monkeypatch)
    runtime = FakeRuntime()
    query = views.build_global_search_request("spain").query
    runtime.catalog.saved_search_objects[42] = types.SimpleNamespace(
        id=42,
        name="Spain",
        query=query,
    )
    runtime.kodi.addon.setSetting("home_smart_id_8", "42")
    ui = views.PluginUI(runtime, "plugin://plugin.image.mypicsdb3", 7)

    ui.dispatch(
        views.Request(
            "home-smart",
            {"slot": "8", "widget": "1", "home": "1", "generation": "4"},
        )
    )

    assert calls.category == "Spain"
    assert runtime.catalog.query_requests[-1][0] is query
    assert calls.ended is True


def test_manual_collections_list_open_and_use_default_album_view(monkeypatch) -> None:
    views, calls = load_views(monkeypatch)
    runtime = FakeRuntime()
    runtime.kodi.settings.album_view_mode = 54
    runtime.catalog.collection_rows = [
        {
            "id": 9,
            "name": "Family picks",
            "available_count": 1,
            "item_count": 2,
            "uri": "smb://server/photos/image.jpg",
            "thumb_uri": "smb://server/photos/image.jpg",
            "media_type": "picture",
        }
    ]
    runtime.catalog.collection_objects[9] = types.SimpleNamespace(
        id=9, name="Family picks"
    )
    ui = views.PluginUI(runtime, "plugin://plugin.image.mypicsdb3", 7)

    ui.dispatch(views.Request("collections", {}))
    assert calls.category == "Collections"
    assert calls.items[0][0].endswith("/action/create-collection")
    assert calls.items[1][0] == "plugin://plugin.image.mypicsdb3/collection?id=9"
    assert calls.items[1][1].label == "Family picks  [COLOR=grey](1)[/COLOR]"
    assert calls.items[1][1].context == [
        (
            "Rename collection",
            "RunPlugin(plugin://plugin.image.mypicsdb3/action/rename-collection?id=9)",
        ),
        (
            "Delete collection",
            "RunPlugin(plugin://plugin.image.mypicsdb3/action/delete-collection?id=9)",
        ),
        (
            "Assign music playlist",
            "RunPlugin(plugin://plugin.image.mypicsdb3/action/assign-music-playlist?type=manual&id=9)",
        ),
    ]

    calls.builtins.clear()
    calls.info_label_sequences = {
        "Container.PluginCategory": ["Collections", "Family picks"],
        "Container.Content": ["files", "images"],
    }
    ui.dispatch(views.Request("collection", {"id": "9"}))
    assert calls.category == "Family picks"
    assert calls.items[0][0].startswith(
        "plugin://plugin.image.mypicsdb3/action/start-slideshow?"
    )
    assert calls.items[1][0] == (
        "plugin://plugin.image.mypicsdb3/action/export-results?scope=collection&id=9"
    )
    assert calls.items[2][0] == "smb://server/photos/image.jpg"
    labels = [label for label, _command in calls.items[2][1].context]
    assert "Add to collection" in labels
    assert "Remove from collection" in labels
    slideshow = [
        command
        for label, command in calls.items[2][1].context
        if label == "Play slideshow from here"
    ]
    assert slideshow == [
        "RunPlugin(plugin://plugin.image.mypicsdb3/action/start-slideshow?"
        "id=9&scope=collection&start=1)"
    ]
    assert calls.builtins in ([], ["Container.SetViewMode(54)"])



def test_manual_collection_home_route_is_bounded_and_has_no_action_row(monkeypatch) -> None:
    views, calls = load_views(monkeypatch)
    runtime = FakeRuntime()
    runtime.catalog.collection_objects[9] = types.SimpleNamespace(
        id=9, name="Family picks"
    )
    runtime.catalog.collection_rows = [
        {"id": 9, "name": "Family picks", "available_count": 1}
    ]
    runtime.kodi.addon.setSetting("home_collection_id_2", "9")
    ui = views.PluginUI(runtime, "plugin://plugin.image.mypicsdb3", 7)

    ui.dispatch(
        views.Request(
            "home-collection",
            {"slot": "2", "widget": "1", "home": "1", "generation": "7"},
        )
    )

    assert runtime.catalog.collection_requests[0] == (9, 10, 0)
    assert calls.category == "Family picks"
    assert len(calls.items) == 1
    assert calls.items[0][0] == "smb://server/photos/image.jpg"
    assert not calls.items[0][0].startswith(
        "plugin://plugin.image.mypicsdb3/action/start-slideshow"
    )
    labels = [label for label, _command in calls.items[0][1].context]
    assert "Add to collection" in labels
    assert "Open Collections" in labels
    assert (
        "Open Collections",
        "ActivateWindow(Pictures,plugin://plugin.image.mypicsdb3/collections,return)",
    ) in calls.items[0][1].context
    assert calls.ended is True


def test_manual_collection_context_reorders_items_and_invalidates_home(monkeypatch) -> None:
    views, calls = load_views(monkeypatch)
    runtime = FakeRuntime()
    runtime.catalog.collection_objects[9] = types.SimpleNamespace(
        id=9, name="Family picks"
    )
    first = dict(runtime.catalog.recent_taken(1)[0])
    first["id"] = 1
    second = dict(first)
    second.update({"id": 2, "filename": "clip.mp4", "media_type": "video"})
    third = dict(first)
    third.update({"id": 3, "filename": "third.jpg"})
    rows = [first, second, third]
    runtime.catalog.pictures_in_collection = (
        lambda collection_id, limit, offset=0: rows[offset : offset + limit]
    )
    runtime.catalog.collection_available_count = lambda collection_id: len(rows)
    ui = views.PluginUI(runtime, "plugin://plugin.image.mypicsdb3", 7)

    ui.dispatch(views.Request("collection", {"id": "9"}))

    first_labels = [label for label, _command in calls.items[2][1].context]
    middle_labels = [label for label, _command in calls.items[3][1].context]
    last_labels = [label for label, _command in calls.items[4][1].context]
    assert "Move up" not in first_labels
    assert "Move down" in first_labels
    assert {"Move up", "Move down", "Move to top", "Move to bottom"} <= set(
        middle_labels
    )
    assert "Move down" not in last_labels
    assert "Move up" in last_labels

    ui.action(
        "action/move-collection-item",
        {"collection": "9", "id": "2", "direction": "top"},
    )
    assert runtime.catalog.moved_collection_items == [(9, 2, "top")]
    assert runtime.kodi.home_invalidations[-1] == "manual collection order changed"
    assert calls.builtins[-1] == "Container.Refresh"


def test_mixed_manual_collection_uses_native_picture_directory(monkeypatch) -> None:
    views, calls = load_views(monkeypatch)
    runtime = FakeRuntime()
    picture = dict(runtime.catalog.recent_taken(1)[0])
    video = dict(picture)
    video.update(
        {
            "id": 2,
            "uri": "smb://server/photos/clip.mp4",
            "filename": "clip.mp4",
            "media_type": "video",
        }
    )
    runtime.catalog.pictures_in_collection = (
        lambda collection_id, limit, offset=0: [picture, video]
    )
    ui = views.PluginUI(runtime, "plugin://plugin.image.mypicsdb3", -1)
    FakeDialog.select_responses = [0]

    ui.dispatch(
        views.Request(
            "action/start-slideshow",
            {"scope": "collection", "id": "9"},
        )
    )

    assert not any(
        request["method"] == "Playlist.Add"
        for request in calls.rpc_requests
    )
    assert calls.builtins == [
        'SlideShow("plugin://plugin.image.mypicsdb3/slideshow/collection-pictures?id=9",'
        'notrandom,beginslide="smb://server/photos/image.jpg")'
    ]
    assert any(
        "split to picture slideshow" in message
        for message in runtime.kodi.info_messages
    )
    assert any(
        "route=native-collection-picture" in message
        for message in runtime.kodi.info_messages
    )


def test_native_collection_picture_directory_filters_and_orders_media(monkeypatch) -> None:
    views, calls = load_views(monkeypatch)
    runtime = FakeRuntime()
    first = dict(runtime.catalog.recent_taken(1)[0])
    first.update(
        {
            "id": 7,
            "uri": "smb://server/photos/z-last-by-name.jpg",
            "filename": "z-last-by-name.jpg",
        }
    )
    video = dict(first)
    video.update(
        {
            "id": 8,
            "uri": "smb://server/photos/clip.mp4",
            "filename": "clip.mp4",
            "media_type": "video",
        }
    )
    second = dict(first)
    second.update(
        {
            "id": 9,
            "uri": "smb://server/photos/a-first-by-name.jpg",
            "filename": "a-first-by-name.jpg",
        }
    )
    duplicate = dict(second)
    duplicate["id"] = 10
    runtime.catalog.pictures_in_collection = (
        lambda collection_id, limit, offset=0: [first, video, second, duplicate]
    )
    ui = views.PluginUI(runtime, "plugin://plugin.image.mypicsdb3", 7)

    ui.dispatch(
        views.Request(
            "slideshow/collection-pictures",
            {"id": "9"},
        )
    )

    assert [entry[0] for entry in calls.items] == [
        "smb://server/photos/z-last-by-name.jpg",
        "smb://server/photos/a-first-by-name.jpg",
    ]
    assert [entry[1].label for entry in calls.items] == [
        "000001 z-last-by-name.jpg",
        "000002 a-first-by-name.jpg",
    ]
    assert all(entry[2] is False for entry in calls.items)
    assert calls.content == "images"
    assert calls.ended is True
    assert calls.rpc_requests == []


def test_mixed_manual_collection_can_choose_video_playlist_from_video(monkeypatch) -> None:
    views, calls = load_views(monkeypatch)
    runtime = FakeRuntime()
    picture = dict(runtime.catalog.recent_taken(1)[0])
    video = dict(picture)
    video.update(
        {
            "id": 2,
            "uri": "smb://server/photos/clip.mp4",
            "filename": "clip.mp4",
            "media_type": "video",
        }
    )
    runtime.catalog.pictures_in_collection = (
        lambda collection_id, limit, offset=0: [picture, video]
    )
    ui = views.PluginUI(runtime, "plugin://plugin.image.mypicsdb3", -1)
    FakeDialog.select_responses = [1]

    ui.dispatch(
        views.Request(
            "action/start-slideshow",
            {"scope": "collection", "id": "9", "start": "2"},
        )
    )

    add_requests = [
        request for request in calls.rpc_requests if request["method"] == "Playlist.Add"
    ]
    assert len(add_requests) == 1
    assert add_requests[0]["params"] == {
        "playlistid": 1,
        "item": [{"file": "smb://server/photos/clip.mp4"}],
    }
    assert any(
        "split to video playlist" in message
        for message in runtime.kodi.info_messages
    )


def test_mixed_manual_collection_playback_can_be_cancelled(monkeypatch) -> None:
    views, calls = load_views(monkeypatch)
    runtime = FakeRuntime()
    picture = dict(runtime.catalog.recent_taken(1)[0])
    video = dict(picture)
    video.update(
        {
            "id": 2,
            "uri": "smb://server/photos/clip.mp4",
            "filename": "clip.mp4",
            "media_type": "video",
        }
    )
    runtime.catalog.pictures_in_collection = (
        lambda collection_id, limit, offset=0: [picture, video]
    )
    ui = views.PluginUI(runtime, "plugin://plugin.image.mypicsdb3", -1)
    FakeDialog.select_responses = [-1]

    ui.dispatch(
        views.Request(
            "action/start-slideshow",
            {"scope": "collection", "id": "9"},
        )
    )

    assert calls.rpc_requests == []
    assert runtime.kodi.mixed_slideshow_updates == []



def test_manual_collection_rename_and_delete_keep_home_rows_in_sync(monkeypatch) -> None:
    views, calls = load_views(monkeypatch)
    runtime = FakeRuntime()
    runtime.catalog.collection_objects[4] = types.SimpleNamespace(id=4, name="Trips")
    runtime.catalog.collection_rows = [
        {"id": 4, "name": "Trips", "available_count": 0}
    ]
    runtime.kodi.addon.setSetting(
        "home_layout_v2",
        '{"version":1,"items":[{"type":"collection","id":4,"enabled":true}]}',
    )
    runtime.kodi.addon.setSetting("home_row_1", "collection")
    runtime.kodi.addon.setSetting("home_collection_id_1", "4")
    runtime.kodi.addon.setSetting("home_collection_name_1", "Trips")
    ui = views.PluginUI(runtime, "plugin://plugin.image.mypicsdb3", 7)

    FakeDialog.input_responses = ["Journeys"]
    ui.action("action/rename-collection", {"id": "4"})
    assert runtime.kodi.addon.getSetting("home_collection_name_1") == "Journeys"
    assert runtime.kodi.home_invalidations[-1] == (
        "manual collection home rows changed"
    )
    assert calls.builtins[-1] == "ReloadSkin()"

    FakeDialog.responses = [True]
    ui.action("action/delete-collection", {"id": "4"})
    assert runtime.kodi.addon.getSetting("home_row_1") == "none"
    assert runtime.kodi.addon.getSetting("home_collection_id_1") == "0"
    assert calls.builtins[-1] == "ReloadSkin()"


def test_query_result_can_be_snapshotted_to_manual_collection(monkeypatch) -> None:
    views, calls = load_views(monkeypatch)
    runtime = FakeRuntime()
    ui = views.PluginUI(runtime, "plugin://plugin.image.mypicsdb3", 7)

    FakeDialog.input_responses = ["Summer snapshot"]
    FakeDialog.responses = [True]
    ui.action(
        "action/snapshot-results",
        {"scope": "search", "q": "summer"},
    )

    assert len(runtime.catalog.collection_snapshots) == 1
    name, query = runtime.catalog.collection_snapshots[0]
    assert name == "Summer snapshot"
    assert query.root.children[0].field == "text"
    assert runtime.kodi.notifications[-1] == (
        "Collection snapshot created (1 items)", False
    )
    assert calls.builtins[-1].startswith("Container.Update(")



def test_query_result_can_be_exported_with_writable_destination_and_progress(
    monkeypatch,
) -> None:
    views, _calls = load_views(monkeypatch)
    runtime = FakeRuntime()
    ui = views.PluginUI(runtime, "plugin://plugin.image.mypicsdb3", 7)
    captured = {}

    class FakeProgress:
        def __init__(self):
            self.updates = []
            self.closed = False

        def create(self, heading, message):
            captured["progress_create"] = (heading, message)

        def iscanceled(self):
            return False

        def update(self, percent, message):
            self.updates.append((percent, message))

        def close(self):
            self.closed = True

    class FakeSafeExporter:
        def __init__(self, catalog, filesystem, version, logger=None):
            captured["init"] = (catalog, filesystem, version, logger)

        def export_ids(
            self, ids, destination, export_name, selection_label,
            cancelled=None, progress=None,
        ):
            captured["export"] = (
                list(ids), destination, export_name, selection_label
            )
            assert cancelled() is False
            progress(1, 1, "image.jpg")
            return types.SimpleNamespace(
                cancelled=False,
                selected=1,
                copied=1,
                missing=0,
                failed=0,
                collisions=0,
                export_uri="smb://server/export/Summer/",
                manifest_uri=(
                    "smb://server/export/Summer/mypicsdb3-export-manifest.json"
                ),
            )

    monkeypatch.setattr(views, "SafeExporter", FakeSafeExporter)
    sys.modules["xbmcgui"].DialogProgress = FakeProgress
    FakeDialog.input_responses = ["Summer export"]
    FakeDialog.browse_responses = ["smb://server/export/"]
    FakeDialog.responses = [True]

    ui.action(
        "action/export-results",
        {"scope": "search", "q": "summer"},
    )

    assert captured["export"] == (
        [1], "smb://server/export/", "Summer export", "Search - summer"
    )
    assert captured["init"][2] == "0.8.18"
    assert FakeDialog.browse_calls[-1][0] == 3
    assert runtime.kodi.notifications[-1] == (
        "Export complete: 1 copied, 0 missing, 0 failed", False
    )


def test_manual_collection_actions_create_add_remove_rename_and_delete(
    monkeypatch,
) -> None:
    views, calls = load_views(monkeypatch)
    runtime = FakeRuntime()
    runtime.catalog.collection_objects[4] = types.SimpleNamespace(
        id=4, name="Trips"
    )
    runtime.catalog.collection_rows = [
        {"id": 4, "name": "Trips", "available_count": 0}
    ]
    ui = views.PluginUI(runtime, "plugin://plugin.image.mypicsdb3", 7)

    FakeDialog.input_responses = ["New collection"]
    ui.action("action/create-collection", {})
    assert runtime.catalog.created_collections == ["New collection"]
    assert runtime.kodi.notifications[-1] == ("Collection created", False)
    assert calls.builtins[-1].startswith("Container.Update(")

    FakeDialog.select_responses = [1]
    ui.action("action/add-to-collection", {"id": "1"})
    assert runtime.catalog.added_collection_items == [(4, 1)]
    assert runtime.kodi.notifications[-1] == ("Added to 'Trips'", False)

    ui.action(
        "action/remove-from-collection",
        {"collection": "4", "id": "1"},
    )
    assert runtime.catalog.removed_collection_items == [(4, 1)]
    assert runtime.kodi.notifications[-1] == ("Removed from 'Trips'", False)
    assert calls.builtins[-1] == "Container.Refresh"

    FakeDialog.input_responses = ["Journeys"]
    ui.action("action/rename-collection", {"id": "4"})
    assert runtime.catalog.renamed_collections == [(4, "Journeys")]
    assert runtime.kodi.notifications[-1] == ("Collection renamed", False)

    FakeDialog.responses = [True]
    ui.action("action/delete-collection", {"id": "4"})
    assert runtime.catalog.deleted_collections == [4]
    assert runtime.kodi.notifications[-1] == ("Collection deleted", False)


def test_manual_collection_music_playlist_can_be_assigned_changed_and_removed(
    monkeypatch,
) -> None:
    views, calls = load_views(monkeypatch)
    runtime = FakeRuntime()
    runtime.catalog.collection_objects[9] = types.SimpleNamespace(id=9, name="Trips")
    runtime.catalog.collection_rows = [
        {"id": 9, "name": "Trips", "available_count": 1}
    ]
    ui = views.PluginUI(runtime, "plugin://plugin.image.mypicsdb3", 7)

    FakeDialog.browse_calls = []
    FakeDialog.browse_responses = ["special://profile/playlists/music/trips.m3u"]
    ui.action("action/assign-music-playlist", {"type": "manual", "id": "9"})

    assert FakeDialog.browse_calls[-1] == (
        1,
        "Choose music playlist",
        "music",
        ".m3u|.m3u8|.pls|.b4s|.wpl",
        False,
        False,
        "special://profile/playlists/music/",
    )
    assert runtime.catalog.music_playlist_updates == [
        ("manual", 9, "special://profile/playlists/music/trips.m3u")
    ]
    assert runtime.kodi.notifications[-1] == ("Music playlist assigned", False)
    assert calls.builtins[-1] == "Container.Refresh"

    calls.items = []
    calls.ended = False
    ui.collections()
    context = calls.items[1][1].context
    assert (
        "Change music playlist",
        "RunPlugin(plugin://plugin.image.mypicsdb3/action/assign-music-playlist?type=manual&id=9)",
    ) in context
    assert (
        "Remove music playlist",
        "RunPlugin(plugin://plugin.image.mypicsdb3/action/remove-music-playlist?type=manual&id=9)",
    ) in context

    ui.action("action/remove-music-playlist", {"type": "manual", "id": "9"})
    assert runtime.catalog.music_playlist_clears == [("manual", 9)]
    assert runtime.kodi.notifications[-1] == ("Music playlist removed", False)


def test_manual_collection_picture_slideshow_starts_assigned_music(monkeypatch) -> None:
    views, calls = load_views(monkeypatch)
    runtime = FakeRuntime()
    runtime.catalog.collection_objects[9] = types.SimpleNamespace(id=9, name="Trips")
    runtime.catalog.music_playlists[("manual", 9)] = "special://music/trips.m3u"
    ui = views.PluginUI(runtime, "plugin://plugin.image.mypicsdb3", -1)

    ui.dispatch(
        views.Request(
            "action/start-music-slideshow",
            {"scope": "collection", "id": "9"},
        )
    )

    assert calls.music_playlist_uri == "special://music/trips.m3u"
    assert len(calls.player_calls) == 1
    assert runtime.kodi.music_session["playlist_fingerprint"] == (
        "test-music-fingerprint"
    )
    assert calls.builtins[-1] == (
        'SlideShow("plugin://plugin.image.mypicsdb3/slideshow/collection-pictures?id=9",'
        'notrandom,beginslide="smb://server/photos/image.jpg")'
    )
    assert any("Music slideshow started" in message for message in runtime.kodi.info_messages)


def test_smart_collection_music_slideshow_uses_picture_only_hidden_route(
    monkeypatch,
) -> None:
    from mypicsdb3.search import build_global_search_request

    views, calls = load_views(monkeypatch)
    runtime = FakeRuntime()
    query = build_global_search_request("summer").query
    runtime.catalog.saved_search_objects[42] = types.SimpleNamespace(
        id=42, name="Summer", query=query
    )
    runtime.catalog.music_playlists[("smart", 42)] = "smb://nas/music/summer.pls"
    picture = dict(runtime.catalog.recent_taken(1)[0])
    video = dict(picture)
    video.update(
        {
            "id": 2,
            "uri": "smb://server/photos/clip.mp4",
            "filename": "clip.mp4",
            "media_type": "video",
        }
    )
    runtime.catalog.query_pictures = lambda _query, _limit, _offset=0: [video, picture]
    ui = views.PluginUI(runtime, "plugin://plugin.image.mypicsdb3", -1)

    ui.dispatch(
        views.Request(
            "action/start-music-slideshow",
            {"scope": "saved-search", "id": "42"},
        )
    )

    assert calls.music_playlist_uri == "smb://nas/music/summer.pls"
    assert calls.builtins[-1] == (
        'SlideShow("plugin://plugin.image.mypicsdb3/slideshow/saved-search-pictures?id=42",'
        'notrandom,beginslide="smb://server/photos/image.jpg")'
    )

    calls.items = []
    calls.ended = False
    ui.dispatch(views.Request("slideshow/saved-search-pictures", {"id": "42"}))
    assert [entry[0] for entry in calls.items] == [
        "smb://server/photos/image.jpg"
    ]


def test_metadata_mapping_view_and_add_action(monkeypatch) -> None:
    views, calls = load_views(monkeypatch)
    runtime = FakeRuntime()
    runtime.catalog.metadata_mapping_overrides = [
        views.MetadataMappingRule("xmp", "CountryName", "country", 20)
    ]
    ui = views.PluginUI(runtime, "plugin://plugin.image.mypicsdb3", 7)

    ui.dispatch(views.Request("metadata-mapping", {}))

    labels = [item.label for _url, item, _is_folder in calls.items]
    assert calls.category == "Metadata mapping"
    assert labels[0] == "Add metadata mapping"
    assert labels[1] == "Reset all custom mappings"
    assert any("XMP · CountryName → Country" in label for label in labels)

    FakeDialog.select_responses = [0, 9]
    FakeDialog.input_responses = ["Image City", "40"]
    ui.action("action/add-metadata-mapping", {})

    added = next(
        rule for rule in runtime.catalog.metadata_mapping_overrides
        if rule.source_tag == "Image City"
    )
    assert added.source_type == "exif"
    assert added.target_field == "city"
    assert added.priority == 40
    assert any("Metadata mapping saved" in message for message, _error in runtime.kodi.notifications)
    assert "Container.Refresh" in calls.builtins


def test_source_scan_settings_save_and_return_to_global_defaults(monkeypatch) -> None:
    views, calls = load_views(monkeypatch)
    runtime = FakeRuntime()
    ui = views.PluginUI(runtime, "plugin://plugin.image.mypicsdb3/sources", 7)

    FakeDialog.select_responses = [1, 1, 1, 0]
    FakeDialog.responses = [True]
    FakeDialog.input_responses = ["JPG,NEF", "MP4,MOV", "#Recycle|Private"]
    ui.action("action/source-scan-settings", {"id": "7"})

    policy = runtime.catalog.source_scan_policies[7]
    assert policy.recursive is True
    assert policy.include_videos is True
    assert policy.picture_extensions == ("jpg", "nef")
    assert policy.video_extensions == ("mp4", "mov")
    assert policy.exclude_fragments == ("#recycle", "private")
    assert policy.exclude_hidden is False
    assert any("Source scan settings saved" in message for message, _error in runtime.kodi.notifications)
    assert "Container.Refresh" in calls.builtins

    calls.builtins.clear()
    FakeDialog.select_responses = [0]
    ui.action("action/source-scan-settings", {"id": "7"})

    assert runtime.catalog.source_scan_policies == {}
    assert any("global scan defaults" in message for message, _error in runtime.kodi.notifications)
    assert "Container.Refresh" in calls.builtins
