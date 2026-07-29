from __future__ import annotations

import calendar
import sys
import time
import uuid
from datetime import datetime
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence, Tuple

import xbmc  # type: ignore
import xbmcgui  # type: ignore
import xbmcplugin  # type: ignore

from .album_view import save_current_album_view
from .home_layout_editor import HomeLayoutEditorText, show_home_layout_editor
from .preferences import (
    DEFAULT_HOME_ROWS,
    HOME_VIEW_BY_KEY,
    MAIN_MENU_NODES,
    normalize_home_layout,
    parse_hidden_main_menu_nodes,
    parse_persisted_home_layout,
    serialize_hidden_main_menu_nodes,
    serialize_home_layout,
    serialize_persisted_home_layout,
)
from .rating_policy import (
    RATING_POLICY_ALL,
    normalize_rating_policy,
    rating_policy_label,
)
from .router import Request
from .search import build_global_search_request
from .saved_searches import SavedSearchValidationError
from .scanner import Scanner
from .slideshow import (
    SlideshowError,
    SlideshowPlayerMismatchError,
    start_mixed_slideshow,
    start_native_folder_slideshow,
    start_video_playlist,
    stop_active_media_players,
)
from .utils import (
    extension_of,
    kodi_generated_video_thumbnail_uri,
    parse_bool,
    plugin_url,
    safe_limit,
)
from .view_mode import set_view_mode_when_container_ready


MAX_SLIDESHOW_ITEMS = 5000


class PluginUI:
    def __init__(self, runtime, base_url: str, handle: int):
        self.runtime = runtime
        self.kodi = runtime.kodi
        self.catalog = runtime.catalog
        self.base_url = base_url
        self.handle = handle
        self.icon = self.kodi.addon.getAddonInfo("icon")
        self.fanart = self.kodi.addon.getAddonInfo("fanart")

    def text(self, string_id: int, fallback: str) -> str:
        return self.kodi.localize(string_id, fallback)

    def _scan_status(self) -> Dict[str, Any]:
        getter = getattr(self.kodi, "scan_status", None)
        if not callable(getter):
            return {}
        try:
            value = getter()
        except Exception as exc:
            self.kodi.log.warning("Could not read scan status: %s", exc)
            return {}
        return value if isinstance(value, dict) else {}

    def url(self, route: str, **params: Any) -> str:
        return plugin_url(self.base_url, route, **params)

    def _configured_rating_policy(self) -> str:
        return normalize_rating_policy(
            getattr(self.kodi.settings, "minimum_rating_policy", RATING_POLICY_ALL)
        )

    def _effective_rating_policy(self, params: Optional[Dict[str, str]] = None) -> str:
        configured = self._configured_rating_policy()
        if configured != RATING_POLICY_ALL and (params or {}).get("rating_policy") == RATING_POLICY_ALL:
            return RATING_POLICY_ALL
        return configured

    def _rating_route_params(self, params: Optional[Dict[str, str]] = None) -> Dict[str, str]:
        configured = self._configured_rating_policy()
        if configured != RATING_POLICY_ALL and self._effective_rating_policy(params) == RATING_POLICY_ALL:
            return {"rating_policy": RATING_POLICY_ALL}
        return {}

    def _rating_label(self, policy: str) -> str:
        normalized = normalize_rating_policy(policy)
        if normalized == RATING_POLICY_ALL:
            return self.text(30053, "All pictures")
        if normalized == "rated_and_unrated":
            return self.text(32401, "Rated and unrated (exclude rating 0)")
        return rating_policy_label(normalized)

    def _rating_category(self, category: str, params: Optional[Dict[str, str]] = None) -> str:
        configured = self._configured_rating_policy()
        if configured == RATING_POLICY_ALL:
            return category
        effective = self._effective_rating_policy(params)
        if effective == RATING_POLICY_ALL:
            policy = self.text(30072, "Temporary: all pictures")
        else:
            policy = self.text(30069, "Minimum rating: %s") % self._rating_label(effective)
        return "%s  [COLOR=grey](%s)[/COLOR]" % (category, policy)

    def _media_art_uri(
        self,
        uri: Any,
        thumb_uri: Any = None,
        media_type: Any = None,
    ) -> str:
        media_uri = str(uri or "")
        thumbnail = str(thumb_uri or "")
        configured_video_extensions = tuple(
            getattr(self.kodi.settings, "video_extensions", ()) or ()
        )
        is_video = str(media_type or "") == "video" or (
            bool(media_uri)
            and extension_of(media_uri) in configured_video_extensions
        )
        if is_video and (not thumbnail or thumbnail == media_uri):
            return kodi_generated_video_thumbnail_uri(media_uri)
        return thumbnail or media_uri

    def _item(self, label: str, art: Optional[str] = None, path: Optional[str] = None) -> xbmcgui.ListItem:
        item = xbmcgui.ListItem(label=label, path=path or "")
        image = art or self.icon
        item.setArt({"thumb": image, "icon": image, "fanart": self.fanart})
        return item

    def add_folder(self, label: str, route: str, art: Optional[str] = None, context: Optional[List[Tuple[str, str]]] = None, **params: Any):
        item = self._item(label, art)
        if context:
            item.addContextMenuItems(context)
        return (self.url(route, **params), item, True)

    def add_action(self, label: str, route: str, art: Optional[str] = None, context: Optional[List[Tuple[str, str]]] = None, **params: Any):
        item = self._item(label, art)
        item.setProperty("IsPlayable", "false")
        if context:
            item.addContextMenuItems(context)
        return (self.url(route, **params), item, False)

    def finish(
        self,
        items: Sequence[Tuple[str, xbmcgui.ListItem, bool]],
        content: str = "images",
        cache: bool = False,
        category: Optional[str] = None,
        view_mode: int = 0,
    ):
        if category:
            xbmcplugin.setPluginCategory(self.handle, category)
        xbmcplugin.setContent(self.handle, content)
        xbmcplugin.addDirectoryItems(self.handle, list(items), len(items))
        xbmcplugin.endOfDirectory(self.handle, succeeded=True, cacheToDisc=cache)
        if view_mode and category and items:
            set_view_mode_when_container_ready(
                xbmc,
                xbmcgui,
                view_mode,
                expected_category=category,
                expected_content=content,
                logger=self.kodi.log,
            )

    def _browser_view_mode(self, params: Optional[Dict[str, str]] = None) -> int:
        if parse_bool((params or {}).get("widget"), False):
            return 0
        return int(self.kodi.settings.album_view_mode or 0)

    def root(self, params: Optional[Dict[str, str]] = None):
        params = params or {}
        rating_params = self._rating_route_params(params)
        items = [
            self.add_folder(self.text(32500, "Search"), "search", **rating_params),
            self.add_folder(self.text(32700, "Saved searches"), "saved-searches", **rating_params),
            self.add_folder(self.text(30000, "Picture sources"), "sources", **rating_params),
        ]
        hidden_nodes = parse_hidden_main_menu_nodes(
            self.kodi.addon.getSetting("hidden_main_menu_nodes")
        )
        items.extend(
            self.add_folder(
                self.text(node.string_id, node.fallback),
                node.route,
                **rating_params,
            )
            for node in MAIN_MENU_NODES
            if node.key not in hidden_nodes
            and (node.key != "videos" or self.kodi.settings.include_videos)
        )
        scan_status = self._scan_status()
        scan_action = (
            self.add_action(self.text(32726, "Stop scan"), "action/stop-scan")
            if scan_status
            else self.add_action(self.text(30013, "Scan now"), "action/scan")
        )
        items.extend(
            [
                scan_action,
                self.add_folder(self.text(30014, "Scan status"), "status"),
                self.add_action(self.text(30015, "Settings"), "action/settings"),
            ]
        )
        configured = self._configured_rating_policy()
        if configured != RATING_POLICY_ALL:
            effective = self._effective_rating_policy(params)
            status = self.text(30069, "Minimum rating: %s") % self._rating_label(configured)
            items.insert(0, self.add_action(status, "action/settings"))
            if effective == RATING_POLICY_ALL:
                items.insert(1, self.add_folder(self.text(30071, "Use configured rating filter"), ""))
            else:
                items.insert(
                    1,
                    self.add_folder(
                        self.text(30070, "Show all pictures temporarily"),
                        "",
                        rating_policy=RATING_POLICY_ALL,
                    ),
                )
        self.finish(items, content="files", category=self.text(30056, "MyPicsDB 3"))

    def search(self, params: Optional[Dict[str, str]] = None):
        search_params = dict(params or {})
        raw_text = search_params.get("q", "")
        if not raw_text:
            raw_text = xbmcgui.Dialog().input(self.text(32501, "Search pictures"))
        if not raw_text:
            return self.finish(
                [],
                content="images",
                cache=False,
                category=self.text(32500, "Search"),
            )
        try:
            request = build_global_search_request(raw_text)
        except ValueError as exc:
            self.kodi.notify(
                "%s: %s" % (self.text(32503, "Invalid search"), exc),
                error=True,
            )
            return self.finish(
                [],
                content="images",
                cache=False,
                category=self.text(32500, "Search"),
            )
        search_params["q"] = request.text
        category = self.text(32502, "Search results: %s") % request.text
        save_item = self.add_action(
            self.text(32701, "Save this search"),
            "action/save-search",
            q=request.text,
        )
        return self.pictures(
            "search",
            lambda limit, offset: self.catalog.query_pictures(
                request.query,
                limit,
                offset,
            ),
            search_params,
            category,
            prefix_items=[save_item],
        )

    def saved_searches(self, params: Optional[Dict[str, str]] = None):
        params = params or {}
        rating_params = self._rating_route_params(params)
        items = []
        for row in self.catalog.list_saved_searches():
            saved_id = int(row["id"])
            rename = "RunPlugin(%s)" % self.url(
                "action/rename-saved-search", id=saved_id
            )
            delete = "RunPlugin(%s)" % self.url(
                "action/delete-saved-search", id=saved_id
            )
            context = [
                (self.text(32705, "Rename saved search"), rename),
                (self.text(32706, "Delete saved search"), delete),
            ]
            items.append(
                self.add_folder(
                    str(row["name"]),
                    "saved-search",
                    context=context,
                    id=saved_id,
                    **rating_params,
                )
            )
        self.finish(
            items,
            content="files",
            category=self._rating_category(
                self.text(32700, "Saved searches"), params
            ),
        )

    def saved_search(self, saved_search_id: int, params: Dict[str, str]):
        try:
            saved = self.catalog.get_saved_search(saved_search_id)
        except SavedSearchValidationError as exc:
            self.kodi.notify(
                "%s: %s" % (self.text(32710, "Invalid saved search"), exc),
                error=True,
            )
            return self.finish(
                [],
                content="images",
                cache=False,
                category=self.text(32700, "Saved searches"),
            )
        if saved is None:
            self.kodi.notify(self.text(32709, "Saved search was not found"), error=True)
            return self.finish(
                [],
                content="images",
                cache=False,
                category=self.text(32700, "Saved searches"),
            )
        saved_params = dict(params)
        saved_params["id"] = str(saved.id)
        return self.pictures(
            "saved-search",
            lambda limit, offset: self.catalog.query_pictures(
                saved.query,
                limit,
                offset,
            ),
            saved_params,
            saved.name,
        )

    def sources(self, params: Optional[Dict[str, str]] = None):
        params = params or {}
        rating_params = self._rating_route_params(params)
        try:
            self.catalog.sync_sources(self.kodi.kodi_picture_sources())
        except Exception as exc:
            self.kodi.log.warning("Could not refresh Kodi picture sources: %s", exc)
        sources = self.catalog.get_sources()
        items = [self.add_action(self.text(30020, "Refresh Kodi sources"), "action/refresh-sources")]
        for source in sources:
            state = self.text(30018, "Enabled") if source.enabled else self.text(30019, "Disabled")
            label = "%s  [COLOR=grey](%s)[/COLOR]" % (source.label, state)
            toggle = "RunPlugin(%s)" % self.url("action/toggle-source", id=source.id)
            scan = "RunPlugin(%s)" % self.url("action/scan", source=source.id)
            toggle_label = self.text(30064, "Disable source") if source.enabled else self.text(30063, "Enable source")
            context = [(toggle_label, toggle), (self.text(30021, "Scan selected source"), scan)]
            if source.enabled:
                items.append(self.add_folder(label, "source", art=self.icon, context=context, id=source.id, **rating_params))
            else:
                items.append(self.add_action(label, "action/toggle-source", context=context, id=source.id))
        self.finish(items, content="files", category=self._rating_category(self.text(30000, "Picture sources"), params))

    def source(self, source_id: int, params: Optional[Dict[str, str]] = None):
        params = params or {}
        source = self.catalog.get_source(source_id)
        if not source:
            self.finish([], category=self.text(30000, "Picture sources"))
            return
        folders = self.catalog.source_root_folders(source_id)
        items = [self._folder_item(folder, browse_params=params) for folder in folders]
        self.finish(
            items,
            content="images",
            category=self._rating_category(source.label, params),
            view_mode=self._browser_view_mode(params),
        )

    @staticmethod
    def _set_video_info(item, title: str, date_added: str) -> None:
        """Set video metadata without Kodi's deprecated ListItem.setInfo path."""

        getter = getattr(item, "getVideoInfoTag", None)
        if callable(getter):
            tag = getter()
            tag.setTitle(str(title or ""))
            if date_added:
                tag.setDateAdded(str(date_added))
            return
        item.setInfo("video", {"title": title, "dateadded": date_added})

    def _media_item(
        self,
        row: Dict[str, Any],
        extra_context: Optional[List[Tuple[str, str]]] = None,
        browse_params: Optional[Dict[str, str]] = None,
        slideshow_route: Optional[str] = None,
    ) -> Tuple[str, xbmcgui.ListItem, bool]:
        date_text = str(row.get("taken_at") or row.get("discovered_at") or "")
        label = row.get("filename") or date_text or self.text(30031, "Picture")
        media_type = str(row.get("media_type") or "picture")
        media_uri = str(row.get("uri") or "")
        art_uri = self._media_art_uri(
            media_uri, row.get("thumb_uri"), media_type
        )
        item = self._item(label, art_uri, media_uri)
        info: Dict[str, Any] = {"title": label, "picturepath": media_uri, "date": date_text}
        if row.get("width") and row.get("height"):
            info["resolution"] = "%sx%s" % (row["width"], row["height"])
        if row.get("camera_make"):
            info["cameramake"] = row["camera_make"]
        if row.get("camera_model"):
            info["cameramodel"] = row["camera_model"]
        if row.get("caption"):
            info["exifcomment"] = row["caption"]
        try:
            if media_type == "video":
                self._set_video_info(item, str(label), date_text)
                item.setProperty("IsPlayable", "true")
                if row.get("mime_type") and hasattr(item, "setMimeType"):
                    item.setMimeType(str(row["mime_type"]))
            else:
                item.setInfo("pictures", info)
        except Exception:
            pass
        item.setProperty("MyPicsDB3.MediaType", media_type)
        item.setProperty("MyPicsDB3.PictureId", str(row.get("id", "")))
        item.setProperty("MyPicsDB3.TakenAt", date_text)
        item.setProperty("MyPicsDB3.Camera", " ".join(filter(None, [row.get("camera_make"), row.get("camera_model")])))
        item.setProperty("MyPicsDB3.Folder", str(row.get("folder_name") or ""))
        item.setProperty("MyPicsDB3.Source", str(row.get("source_label") or ""))
        if row.get("rating") is not None:
            item.setProperty("MyPicsDB3.Rating", str(row["rating"]))
        toggle = "RunPlugin(%s)" % self.url("action/toggle-favorite", id=row.get("id"))
        context = [(self.text(30022, "Toggle favorite"), toggle)]
        if slideshow_route:
            slideshow_params = {
                key: value
                for key, value in (browse_params or {}).items()
                if key not in {"offset", "limit", "widget"}
            }
            slideshow_params.update(
                {"scope": slideshow_route, "start": row.get("id")}
            )
            context.append(
                (
                    self.text(32603, "Play slideshow from here"),
                    "RunPlugin(%s)" % self.url(
                        "action/start-slideshow",
                        **slideshow_params,
                    ),
                )
            )
        if row.get("folder_id"):
            context.append((self.text(30023, "Open containing album"), "ActivateWindow(Pictures,%s,return)" % self.url("folder", id=row["folder_id"], **self._rating_route_params(browse_params))))
        if extra_context:
            context.extend(extra_context)
        item.addContextMenuItems(context)
        return (str(row.get("uri") or ""), item, False)

    def _folder_item(
        self,
        row: Dict[str, Any],
        extra_context: Optional[List[Tuple[str, str]]] = None,
        browse_params: Optional[Dict[str, str]] = None,
    ) -> Tuple[str, xbmcgui.ListItem, bool]:
        count = int(row.get("picture_count") or 0)
        label = "%s  [COLOR=grey](%d)[/COLOR]" % (row.get("name") or self.text(30032, "Album"), count)
        art = self._media_art_uri(
            row.get("representative_uri"), row.get("representative_thumb")
        ) or self.icon
        context = [(self.text(30021, "Scan selected source"), "RunPlugin(%s)" % self.url("action/scan", source=row.get("source_id")))]
        if row.get("id"):
            context.append(
                (
                    self.text(32602, "Play mixed slideshow"),
                    "RunPlugin(%s)" % self.url(
                        "action/start-slideshow",
                        scope="folder-tree",
                        id=row["id"],
                    ),
                )
            )
        if extra_context:
            context.extend(extra_context)
        return self.add_folder(
            label,
            "folder",
            art=art,
            context=context,
            id=row["id"],
            **self._rating_route_params(browse_params),
        )

    def _next_page_item(
        self,
        route: str,
        offset: int,
        limit: int,
        context: Optional[List[Tuple[str, str]]] = None,
        **params: Any,
    ):
        return self.add_folder(
            self.text(30024, "Next page"),
            route,
            context=context,
            offset=offset + limit,
            limit=limit,
            **params,
        )

    def pictures(
        self,
        route: str,
        getter: Callable[[int, int], List[Dict[str, Any]]],
        params: Dict[str, str],
        category: str,
        random_view: bool = False,
        prefix_items: Optional[Sequence[Tuple[str, xbmcgui.ListItem, bool]]] = None,
    ):
        is_widget = parse_bool(params.get("widget"), False)
        default_limit = (
            self.kodi.settings.widget_limit
            if is_widget
            else self.kodi.settings.browser_page_size
        )
        limit = safe_limit(params.get("limit"), default_limit)
        offset = int(params.get("offset", "0") or 0)
        rows = getter(limit, offset)
        items = list(prefix_items or ())
        items.extend(
            self._media_item(row, browse_params=params, slideshow_route=route)
            for row in rows
        )
        if not random_view and len(rows) == limit and not is_widget and "limit" not in params:
            page_params = {
                key: value
                for key, value in params.items()
                if key not in {"offset", "limit", "widget"}
            }
            items.append(self._next_page_item(route, offset, limit, **page_params))
        self.finish(
            items,
            content="images",
            cache=False,
            category=self._rating_category(category, params),
            view_mode=self._browser_view_mode(params),
        )

    def folder(self, folder_id: int, params: Dict[str, str]):
        folder = self.catalog.get_folder(folder_id)
        if not folder:
            self.finish([], category=self.text(30032, "Albums"))
            return
        child_folders = self.catalog.child_folders(int(folder["source_id"]), folder["uri"])
        limit = safe_limit(params.get("limit"), self.kodi.settings.browser_page_size)
        offset = int(params.get("offset", "0") or 0)
        pictures = self.catalog.pictures_in_folder(folder_id, limit, offset)
        items = [
            self._folder_item(row, browse_params=params)
            for row in child_folders
        ]
        items.extend(
            self._media_item(row, browse_params=params, slideshow_route="folder")
            for row in pictures
        )
        if len(pictures) == limit:
            items.append(
                self._next_page_item(
                    "folder",
                    offset,
                    limit,
                    id=folder_id,
                )
            )
        self.finish(
            items,
            content="images",
            category=self._rating_category(
                folder.get("name") or self.text(30032, "Albums"),
                params,
            ),
            view_mode=self._browser_view_mode(params),
        )

    def folders(self, route: str, rows: List[Dict[str, Any]], category: str, params: Optional[Dict[str, str]] = None):
        params = params or {}
        self.finish(
            [self._folder_item(row, browse_params=params) for row in rows],
            content="images",
            category=self._rating_category(category, params),
            view_mode=self._browser_view_mode(params),
        )

    def years(self, params: Optional[Dict[str, str]] = None):
        params = params or {}
        rating_params = self._rating_route_params(params)
        items = []
        for row in self.catalog.years():
            label = "%s  [COLOR=grey](%s)[/COLOR]" % (row["year"], row["picture_count"])
            items.append(
                self.add_folder(
                    label,
                    "year",
                    art=self._media_art_uri(row.get("uri"), row.get("thumb_uri")),
                    year=row["year"],
                    **rating_params,
                )
            )
        undated = self.catalog.undated_summary()
        if undated:
            label = "%s  [COLOR=grey](%s)[/COLOR]" % (
                self.text(30034, "No date"),
                undated["picture_count"],
            )
            items.append(
                self.add_folder(
                    label,
                    "no-date",
                    art=self._media_art_uri(undated.get("uri"), undated.get("thumb_uri")),
                    **rating_params,
                )
            )
        self.finish(
            items,
            content="images",
            category=self._rating_category(self.text(30007, "Years"), params),
            view_mode=self._browser_view_mode(params),
        )

    def months(self, year: int, params: Optional[Dict[str, str]] = None):
        params = params or {}
        rating_params = self._rating_route_params(params)
        items = []
        for row in self.catalog.months_for_year(year):
            month = int(row["month"])
            name = calendar.month_name[month] if 1 <= month <= 12 else str(month)
            label = "%s  [COLOR=grey](%s)[/COLOR]" % (name, row["picture_count"])
            items.append(
                self.add_folder(
                    label,
                    "month",
                    art=self._media_art_uri(row.get("uri"), row.get("thumb_uri")),
                    year=year,
                    month=month,
                    **rating_params,
                )
            )
        self.finish(
            items,
            content="images",
            category=self._rating_category(str(year), params),
            view_mode=self._browser_view_mode(params),
        )

    def days(self, year: int, month: int, params: Optional[Dict[str, str]] = None):
        params = params or {}
        rating_params = self._rating_route_params(params)
        items = []
        month_name = calendar.month_name[month] if 1 <= month <= 12 else str(month)
        for row in self.catalog.days_for_month(year, month):
            day = int(row["day"])
            label = "%d  [COLOR=grey](%s)[/COLOR]" % (day, row["picture_count"])
            items.append(
                self.add_folder(
                    label,
                    "day",
                    art=self._media_art_uri(row.get("uri"), row.get("thumb_uri")),
                    year=year,
                    month=month,
                    day=day,
                    **rating_params,
                )
            )
        self.finish(
            items,
            content="images",
            category=self._rating_category("%s %d" % (month_name, year), params),
            view_mode=self._browser_view_mode(params),
        )

    def cameras(self, params: Optional[Dict[str, str]] = None):
        params = params or {}
        rating_params = self._rating_route_params(params)
        items = []
        for row in self.catalog.cameras():
            name = " ".join(filter(None, [row.get("camera_make"), row.get("camera_model")])) or self.text(30033, "Unknown camera")
            label = "%s  [COLOR=grey](%s)[/COLOR]" % (name, row["picture_count"])
            items.append(self.add_folder(label, "camera", art=self._media_art_uri(row.get("uri"), row.get("thumb_uri")), make=row.get("camera_make", ""), model=row.get("camera_model", ""), **rating_params))
        self.finish(
            items,
            content="images",
            category=self._rating_category(self.text(30008, "Cameras"), params),
            view_mode=self._browser_view_mode(params),
        )

    def keywords(self, params: Optional[Dict[str, str]] = None):
        params = params or {}
        rating_params = self._rating_route_params(params)
        items = []
        for row in self.catalog.tags():
            label = "%s  [COLOR=grey](%s)[/COLOR]" % (row["name"], row["picture_count"])
            items.append(self.add_folder(label, "tag", art=self._media_art_uri(row.get("uri"), row.get("thumb_uri")), id=row["id"], **rating_params))
        self.finish(
            items,
            content="images",
            category=self._rating_category(self.text(30009, "Keywords"), params),
            view_mode=self._browser_view_mode(params),
        )

    def _configure_home_screen(self) -> None:
        persisted_layout = parse_persisted_home_layout(
            self.kodi.addon.getSetting("home_layout")
        )
        if persisted_layout is None:
            saved_rows = [
                self.kodi.addon.getSetting("home_row_%d" % position)
                or DEFAULT_HOME_ROWS[position - 1]
                for position in range(1, 10)
            ]
            order, enabled = normalize_home_layout(saved_rows)
        else:
            order, enabled = persisted_layout

        result = show_home_layout_editor(
            order,
            enabled,
            {
                key: self.text(view.string_id, view.fallback)
                for key, view in HOME_VIEW_BY_KEY.items()
            },
            HomeLayoutEditorText(
                heading=self.text(32208, "Configure home-screen rows"),
                view_heading=self.text(32220, "View"),
                visible_heading=self.text(32221, "Shown"),
                order_heading=self.text(32222, "Order"),
                on=self.text(32223, "On"),
                off=self.text(32224, "Off"),
                move_up=self.text(32211, "Move up"),
                move_down=self.text(32212, "Move down"),
                save=self.text(32225, "Save"),
                cancel=self.text(32226, "Cancel"),
                defaults=self.text(32227, "Defaults"),
            ),
        )
        if result is None:
            return

        order, enabled = result
        for position, value in enumerate(
            serialize_home_layout(order, enabled),
            start=1,
        ):
            self.kodi.addon.setSetting("home_row_%d" % position, value)
        self.kodi.addon.setSetting(
            "home_layout",
            serialize_persisted_home_layout(order, enabled),
        )
        self.kodi.notify(self.text(32214, "Home-screen layout saved"))
        xbmc.executebuiltin("ReloadSkin()")

    def _configure_main_menu(self) -> None:
        hidden = parse_hidden_main_menu_nodes(
            self.kodi.addon.getSetting("hidden_main_menu_nodes")
        )
        selected = xbmcgui.Dialog().multiselect(
            self.text(32228, "Configure add-on menu"),
            [self.text(node.string_id, node.fallback) for node in MAIN_MENU_NODES],
            preselect=[
                index
                for index, node in enumerate(MAIN_MENU_NODES)
                if node.key not in hidden
            ],
        )
        if selected is None:
            return
        visible_indexes = {int(index) for index in selected}
        hidden = {
            node.key
            for index, node in enumerate(MAIN_MENU_NODES)
            if index not in visible_indexes
        }
        self.kodi.addon.setSetting(
            "hidden_main_menu_nodes",
            serialize_hidden_main_menu_nodes(hidden),
        )
        self.kodi.notify(self.text(32229, "Add-on menu saved"))
        xbmc.executebuiltin("Container.Refresh")

    def _save_current_album_view(self) -> None:
        save_current_album_view(self.kodi, self.text, xbmc, xbmcgui)

    def _slideshow_rows(self, params: Dict[str, str]) -> List[Dict[str, Any]]:
        scope = params.get("scope", "")
        limit = MAX_SLIDESHOW_ITEMS
        if scope == "folder":
            return self.catalog.pictures_in_folder(int(params["id"]), limit, 0)
        if scope == "folder-tree":
            return self.catalog.media_in_folder_tree(int(params["id"]), limit)
        if scope == "recent-taken":
            return self.catalog.recent_taken(limit, 0)
        if scope == "recent-added":
            return self.catalog.recent_added(limit, 0)
        if scope == "random":
            return self.catalog.random_pictures(
                safe_limit(params.get("limit"), self.kodi.settings.widget_limit)
            )
        if scope == "on-this-day":
            now = datetime.now()
            return self.catalog.on_this_day(now.month, now.day, now.year, limit, 0)
        if scope == "on-this-day-random":
            now = datetime.now()
            return self.catalog.random_on_this_day(now.month, now.day, now.year, limit)
        if scope == "year":
            return self.catalog.pictures_for_year(int(params["year"]), limit, 0)
        if scope == "day":
            return self.catalog.pictures_for_day(
                int(params["year"]),
                int(params["month"]),
                int(params["day"]),
                limit,
                0,
            )
        if scope == "no-date":
            return self.catalog.pictures_without_date(limit, 0)
        if scope == "camera":
            return self.catalog.pictures_for_camera(
                params.get("make", ""), params.get("model", ""), limit, 0
            )
        if scope == "tag":
            return self.catalog.pictures_for_tag(int(params["id"]), limit, 0)
        if scope == "favorites":
            return self.catalog.favorites(limit, 0)
        if scope == "rated":
            return self.catalog.rated(limit, 0)
        if scope == "geotagged":
            return self.catalog.geotagged(limit, 0)
        if scope == "videos":
            return self.catalog.videos(limit, 0)
        if scope == "search":
            request = build_global_search_request(params.get("q", ""))
            return self.catalog.query_pictures(request.query, limit, 0)
        if scope == "saved-search":
            saved = self.catalog.get_saved_search(int(params["id"]))
            return (
                self.catalog.query_pictures(saved.query, limit, 0)
                if saved is not None
                else []
            )
        return []

    @staticmethod
    def _database_slideshow_playlist(
        rows: Sequence[Dict[str, Any]],
        start_id: int,
    ) -> Tuple[List[str], int, bool, Optional[int], Optional[int], bool]:
        """Prepare a stable playlist after dropping empty and duplicate URIs."""

        uris: List[str] = []
        positions: Dict[str, int] = {}
        start_position = 0
        start_found = False
        has_video = False
        first_picture_position: Optional[int] = None
        first_video_position: Optional[int] = None
        media_type_by_position: Dict[int, str] = {}
        for row in rows:
            uri = str(row.get("uri") or "")
            if not uri.strip():
                continue
            position = positions.get(uri)
            if position is None:
                position = len(uris)
                positions[uri] = position
                uris.append(uri)
            is_video = str(row.get("media_type") or "") == "video"
            if position not in media_type_by_position:
                media_type_by_position[position] = "video" if is_video else "picture"
            if is_video:
                has_video = True
                if first_video_position is None:
                    first_video_position = position
            elif first_picture_position is None:
                first_picture_position = position
            if not start_found and int(row.get("id") or 0) == start_id:
                start_position = position
                start_found = True
        start_is_picture = media_type_by_position.get(start_position) != "video"
        return (
            uris,
            start_position,
            has_video,
            first_picture_position,
            first_video_position,
            start_is_picture,
        )

    def _start_native_mixed_fallback(
        self,
        folder: Dict[str, Any],
        folder_id: str,
        reason: str,
    ) -> None:
        self.kodi.log.info(
            "Slideshow route=native-mixed-fallback scope=folder-tree "
            "folder_id=%s reason=%s",
            folder_id,
            reason,
        )
        stop_active_media_players(xbmc, logger=self.kodi.log)
        start_native_folder_slideshow(
            xbmc,
            str(folder.get("uri") or ""),
            recursive=True,
            logger=self.kodi.log,
        )

    def _notify_cross_folder_slideshow_unsupported(self) -> None:
        self.kodi.notify(
            self.text(
                32724,
                "This Kodi installation cannot play a cross-folder picture "
                "slideshow. Open an album and start the slideshow there.",
            ),
            error=True,
        )

    def _start_slideshow(self, params: Dict[str, str]) -> None:
        acquire = getattr(self.kodi, "acquire_slideshow_start", None)
        release = getattr(self.kodi, "release_slideshow_start", None)
        token = acquire() if callable(acquire) else ""
        if callable(acquire) and not token:
            self.kodi.notify(
                self.text(32725, "A slideshow is already being prepared"),
                error=False,
            )
            return
        try:
            self._start_slideshow_unlocked(params)
        finally:
            if token and callable(release):
                release(token)

    def _start_slideshow_unlocked(self, params: Dict[str, str]) -> None:
        scope = params.get("scope", "")
        folder = None
        if scope == "folder-tree":
            folder = self.catalog.get_folder(int(params["id"]))
            folder_uri = str((folder or {}).get("uri") or "")
            if not folder_uri:
                self.kodi.notify(self.text(32604, "No media to play"))
                return

        try:
            rows = self._slideshow_rows(params)
        except SavedSearchValidationError as exc:
            self.kodi.notify(
                "%s: %s" % (self.text(32710, "Invalid saved search"), exc),
                error=True,
            )
            return
        if not rows:
            self.kodi.notify(self.text(32604, "No media to play"))
            return
        start_id = int(params.get("start", "0") or 0)
        (
            uris,
            start_position,
            has_video,
            first_picture_position,
            first_video_position,
            start_is_picture,
        ) = self._database_slideshow_playlist(rows, start_id)
        picture_count = sum(
            1 for row in rows if str(row.get("media_type") or "picture") != "video"
        )
        video_count = sum(
            1 for row in rows if str(row.get("media_type") or "") == "video"
        )
        empty_count = sum(1 for row in rows if not str(row.get("uri") or "").strip())
        duplicate_count = max(0, len(rows) - empty_count - len(uris))

        if scope == "folder-tree" and not has_video:
            self.kodi.log.info(
                "Slideshow route=native-picture scope=folder-tree folder_id=%s "
                "rows=%d pictures=%d videos=0 empty=%d duplicates=%d",
                params.get("id", ""),
                len(rows),
                picture_count,
                empty_count,
                duplicate_count,
            )
            try:
                self.kodi.set_mixed_slideshow_active(False)
                stop_active_media_players(xbmc, logger=self.kodi.log)
                start_native_folder_slideshow(
                    xbmc,
                    str(folder.get("uri") or ""),
                    recursive=True,
                    logger=self.kodi.log,
                )
            except SlideshowError as exc:
                self.kodi.notify(
                    "%s: %s" % (self.text(32605, "Could not start slideshow"), exc),
                    error=True,
                )
            return

        if picture_count and not video_count:
            self.kodi.log.info(
                "Slideshow route=picture-playlist scope=%s folder_id=%s rows=%d "
                "pictures=%d videos=0 unique=%d empty=%d duplicates=%d start=%d",
                scope,
                params.get("id", ""),
                len(rows),
                picture_count,
                len(uris),
                empty_count,
                duplicate_count,
                start_position,
            )
            self.kodi.set_mixed_slideshow_active(False)
            try:
                stop_active_media_players(xbmc, logger=self.kodi.log)
                started = start_mixed_slideshow(
                    xbmc,
                    uris,
                    start_position,
                    logger=self.kodi.log,
                )
                if not started:
                    self.kodi.notify(self.text(32604, "No media to play"))
            except SlideshowError as exc:
                self.kodi.notify(
                    "%s: %s" % (self.text(32605, "Could not start slideshow"), exc),
                    error=True,
                )
            return

        if video_count and not picture_count:
            self.kodi.log.info(
                "Slideshow route=video-playlist scope=%s folder_id=%s rows=%d "
                "pictures=0 videos=%d unique=%d empty=%d duplicates=%d start=%d",
                scope,
                params.get("id", ""),
                len(rows),
                video_count,
                len(uris),
                empty_count,
                duplicate_count,
                start_position,
            )
            self.kodi.set_mixed_slideshow_active(False)
            try:
                stop_active_media_players(xbmc, logger=self.kodi.log)
                started = start_video_playlist(
                    xbmc, uris, start_position, logger=self.kodi.log
                )
                if not started:
                    self.kodi.notify(self.text(32604, "No media to play"))
            except SlideshowError as exc:
                self.kodi.notify(
                    "%s: %s" % (self.text(32605, "Could not start slideshow"), exc),
                    error=True,
                )
            return

        compatibility_getter = getattr(
            self.kodi, "picture_playlist_compatibility", None
        )
        compatibility = (
            compatibility_getter() if callable(compatibility_getter) else None
        )
        if compatibility is False:
            self.kodi.set_mixed_slideshow_active(False)
            if scope == "folder-tree" and folder is not None:
                try:
                    self._start_native_mixed_fallback(
                        folder,
                        params.get("id", ""),
                        "cached-picture-playlist-incompatible",
                    )
                except SlideshowError as exc:
                    self.kodi.notify(
                        "%s: %s"
                        % (self.text(32605, "Could not start slideshow"), exc),
                        error=True,
                    )
            else:
                self._notify_cross_folder_slideshow_unsupported()
            return

        self.kodi.log.info(
            "Slideshow route=mixed-playlist scope=%s folder_id=%s rows=%d "
            "pictures=%d videos=%d unique=%d empty=%d duplicates=%d start=%d",
            scope,
            params.get("id", ""),
            len(rows),
            picture_count,
            video_count,
            len(uris),
            empty_count,
            duplicate_count,
            start_position,
        )
        self.kodi.set_mixed_slideshow_active(False)
        probe_picture_position = (
            first_picture_position if compatibility is not True else None
        )
        probe_video_position = (
            first_video_position if compatibility is not True else None
        )
        verify_picture_position = start_position if start_is_picture else None
        try:
            stop_active_media_players(xbmc, logger=self.kodi.log)
            started = start_mixed_slideshow(
                xbmc,
                uris,
                start_position,
                probe_picture_position=probe_picture_position,
                probe_video_position=probe_video_position,
                verify_picture_position=verify_picture_position,
                logger=self.kodi.log,
            )
            if not started:
                self.kodi.notify(self.text(32604, "No media to play"))
                return
            if probe_picture_position is not None:
                setter = getattr(
                    self.kodi, "set_picture_playlist_compatibility", None
                )
                if callable(setter):
                    setter(True)
            if has_video:
                self.kodi.set_mixed_slideshow_active(True)
        except SlideshowPlayerMismatchError as exc:
            self.kodi.set_mixed_slideshow_active(False)
            setter = getattr(self.kodi, "set_picture_playlist_compatibility", None)
            if callable(setter):
                setter(False)
            mismatch_reason = (
                "picture-playlist-unconfirmed"
                if "did not confirm" in str(exc).casefold()
                else "picture-playlist-opened-as-video"
            )
            if scope == "folder-tree" and folder is not None:
                try:
                    self._start_native_mixed_fallback(
                        folder,
                        params.get("id", ""),
                        mismatch_reason,
                    )
                except SlideshowError as exc:
                    self.kodi.notify(
                        "%s: %s"
                        % (self.text(32605, "Could not start slideshow"), exc),
                        error=True,
                    )
                return
            self._notify_cross_folder_slideshow_unsupported()
        except SlideshowError as exc:
            self.kodi.notify(
                "%s: %s" % (self.text(32605, "Could not start slideshow"), exc),
                error=True,
            )

    def status(self):
        overview = self.catalog.overview()
        latest = self.catalog.latest_scan()
        active = self._scan_status()
        values = [
            "%s: %s" % (self.text(30041, "Database backend"), overview["backend"]),
            "%s: %s" % (self.text(30038, "Indexed media"), overview["pictures"]),
            "%s: %s" % (self.text(32601, "Indexed videos"), overview["videos"]),
            "%s: %s" % (self.text(30039, "Missing media"), overview["missing"]),
            "%s: %s" % (self.text(30040, "Indexed albums"), overview["folders"]),
            "%s: %s" % (self.text(30036, "Last scan"), latest.get("finished_at") if latest else self.text(30037, "Never")),
        ]
        if active:
            kind = (
                self.text(32731, "Automatic scan")
                if active.get("kind") == "automatic"
                else self.text(32732, "Manual scan")
            )
            state = (
                self.text(32735, "Stopping scan")
                if active.get("state") == "cancelling"
                else self.text(32733, "Scan in progress")
            )
            values.extend(
                [
                    "%s: %s" % (state, kind),
                    "%s: %s" % (
                        self.text(30047, "Pictures found"),
                        int(active.get("pictures_seen") or 0),
                    ),
                ]
            )
            if active.get("source"):
                values.append(
                    "%s: %s"
                    % (self.text(32734, "Current source"), active.get("source"))
                )
            if active.get("path"):
                values.append(
                    "%s: %s"
                    % (self.text(32736, "Current file"), active.get("path"))
                )
        if latest:
            values.extend([
                "Status: %s" % latest.get("status"),
                "%s: %s" % (self.text(30047, "Pictures found"), latest.get("pictures_seen", 0)),
                "%s: %s" % (self.text(30048, "Pictures updated"), int(latest.get("pictures_added", 0)) + int(latest.get("pictures_updated", 0))),
                "%s: %s" % (self.text(30049, "Pictures unchanged"), latest.get("pictures_unchanged", 0)),
                "%s: %s" % (self.text(30050, "Errors"), latest.get("errors", 0)),
            ])
        items = [("", self._item(value), False) for value in values]
        if active:
            items.append(self.add_action(self.text(32726, "Stop scan"), "action/stop-scan"))
        items.append(self.add_action(self.text(30060, "Test database connection"), "action/test-db"))
        items.append(self.add_action(self.text(30061, "Clean missing records"), "action/cleanup"))
        self.finish(items, content="files", category=self.text(30014, "Scan status"))

    def action(self, route: str, params: Dict[str, str]):
        if route == "action/settings":
            self.kodi.open_settings()
            return
        if route == "action/start-slideshow":
            self._start_slideshow(params)
            return
        if route == "action/configure-home":
            self._configure_home_screen()
            return
        if route == "action/configure-menu":
            self._configure_main_menu()
            return
        if route == "action/save-album-view":
            self._save_current_album_view()
            return
        if route == "action/save-search":
            try:
                request = build_global_search_request(params.get("q", ""))
                name = xbmcgui.Dialog().input(
                    self.text(32702, "Saved-search name"),
                    defaultt=request.text,
                )
                if not name:
                    return
                self.catalog.create_saved_search(name, request.query)
                self.kodi.notify(self.text(32703, "Search saved"))
            except (ValueError, SavedSearchValidationError) as exc:
                self.kodi.notify(
                    "%s: %s" % (self.text(32704, "Could not save search"), exc),
                    error=True,
                )
            return
        if route == "action/rename-saved-search":
            try:
                saved = self.catalog.get_saved_search_summary(int(params["id"]))
                if saved is None:
                    self.kodi.notify(
                        self.text(32709, "Saved search was not found"),
                        error=True,
                    )
                    return
                current_name = str(saved["name"])
                name = xbmcgui.Dialog().input(
                    self.text(32705, "Rename saved search"),
                    defaultt=current_name,
                )
                if not name or name.strip() == current_name:
                    return
                self.catalog.rename_saved_search(int(saved["id"]), name)
                self.kodi.notify(self.text(32707, "Saved search renamed"))
                xbmc.executebuiltin("Container.Refresh")
            except SavedSearchValidationError as exc:
                self.kodi.notify(
                    "%s: %s" % (self.text(32711, "Could not rename saved search"), exc),
                    error=True,
                )
            return
        if route == "action/delete-saved-search":
            try:
                saved = self.catalog.get_saved_search_summary(int(params["id"]))
                if saved is None:
                    self.kodi.notify(
                        self.text(32709, "Saved search was not found"),
                        error=True,
                    )
                    return
                confirmed = xbmcgui.Dialog().yesno(
                    self.text(32706, "Delete saved search"),
                    self.text(32712, "Delete '%s'?") % str(saved["name"]),
                )
                if not confirmed:
                    return
                self.catalog.delete_saved_search(int(saved["id"]))
                self.kodi.notify(self.text(32708, "Saved search deleted"))
                xbmc.executebuiltin("Container.Refresh")
            except SavedSearchValidationError as exc:
                self.kodi.notify(
                    "%s: %s" % (self.text(32710, "Invalid saved search"), exc),
                    error=True,
                )
            return
        if route == "action/refresh-sources":
            sources = self.catalog.sync_sources(self.kodi.kodi_picture_sources())
            missing_sources = [source for source in sources if not source.available]
            dialog = xbmcgui.Dialog()
            for source in missing_sources:
                message = self.text(
                    30068,
                    "This source is no longer configured in Kodi. Remove it and all of its indexed pictures from MyPicsDB 3?",
                )
                if dialog.yesno(self.text(30067, "Remove missing source?"), "%s\n\n%s" % (source.label, message)):
                    self.catalog.delete_source(source.id)
            xbmc.executebuiltin("Container.Refresh")
            return
        if route == "action/toggle-source":
            source = self.catalog.get_source(int(params["id"]))
            if source:
                self.catalog.set_source_enabled(source.id, not source.enabled)
                self.kodi.notify(self.text(30043, "Source enabled") if not source.enabled else self.text(30044, "Source disabled"))
            xbmc.executebuiltin("Container.Refresh")
            return
        if route == "action/toggle-favorite":
            self.catalog.toggle_favorite(int(params["id"]))
            xbmc.executebuiltin("Container.Refresh")
            return
        if route == "action/test-db":
            try:
                self.catalog.test_connection()
                self.kodi.notify(self.text(30058, "Database connection succeeded"))
            except Exception as exc:
                self.kodi.notify("%s: %s" % (self.text(30059, "Database connection failed"), exc), error=True, milliseconds=7000)
            return
        if route == "action/cleanup":
            count = self.catalog.cleanup_missing(self.kodi.settings.missing_retention_days)
            self.kodi.notify("%s: %d" % (self.text(30062, "Missing records cleaned"), count))
            xbmc.executebuiltin("Container.Refresh")
            return
        if route == "action/stop-scan":
            active = self._scan_status()
            if not active:
                self.kodi.notify(self.text(32730, "No scan is running"))
                xbmc.executebuiltin("Container.Refresh")
                return
            confirmed = xbmcgui.Dialog().yesno(
                self.text(32727, "Stop scan?"),
                self.text(
                    32728,
                    "A scan is currently running. Are you sure you want to stop it?",
                ),
            )
            if not confirmed:
                return
            requester = getattr(self.kodi, "request_scan_cancel", None)
            requested = bool(callable(requester) and requester())
            self.kodi.notify(
                self.text(32729, "Stopping scan")
                if requested
                else self.text(32730, "No scan is running")
            )
            xbmc.executebuiltin("Container.Refresh")
            return
        if route == "action/scan":
            self._manual_scan(params.get("source"))
            return

    def _manual_scan(self, source_id: Optional[str]):
        source_ids = [int(source_id)] if source_id else None
        self._background_scan(source_ids)

    def _background_scan(self, source_ids: Optional[List[int]] = None):
        heading = self.text(30056, "MyPicsDB 3")
        scanning_message = self.text(30026, "Scanning started")
        paused_message = self.text(30065, "Scan paused during playback")
        resumed_message = self.text(30066, "Scan resumed")
        monitor = self.kodi.abort_monitor()
        scan_token = uuid.uuid4().hex
        scan_started = False
        last_progress_at = 0.0

        def abort_requested() -> bool:
            return bool(monitor and monitor.abortRequested())

        if abort_requested():
            return

        dialog = xbmcgui.DialogProgressBG()
        dialog.create(heading, scanning_message)

        settings = self.kodi.refresh_settings()
        paused = False

        def begin_status(_stats) -> None:
            nonlocal scan_started
            scan_started = True
            publisher = getattr(self.kodi, "begin_scan_status", None)
            if callable(publisher):
                publisher(scan_token, "manual")
            if not abort_requested():
                xbmc.executebuiltin("Container.Refresh")

        def update_dialog(percent: int, message: str) -> None:
            if abort_requested():
                return
            try:
                dialog.update(percent, heading, message)
            except Exception:
                if not abort_requested():
                    raise

        def cancelled() -> bool:
            nonlocal paused
            stop_requested = getattr(self.kodi, "scan_cancel_requested", None)

            def soft_cancelled() -> bool:
                return bool(
                    callable(stop_requested) and stop_requested(scan_token)
                )

            if soft_cancelled():
                return True
            while (
                not abort_requested()
                and not soft_cancelled()
                and settings.pause_during_playback
                and self.kodi.is_playing()
            ):
                if not paused:
                    paused = True
                    update_dialog(0, paused_message)
                    self.kodi.log.info("Manual scan paused during playback")
                if monitor.waitForAbort(1):
                    return True

            if paused and not abort_requested() and not soft_cancelled():
                paused = False
                update_dialog(0, resumed_message)
                self.kodi.log.info("Manual scan resumed after playback")

            return bool(abort_requested() or soft_cancelled())

        def progress(source, path, stats):
            nonlocal last_progress_at
            now = time.monotonic()
            if now - last_progress_at < 0.5 and int(stats.pictures_seen or 0) % 100:
                return
            last_progress_at = now
            message = "%s\n%s\n%s: %d" % (
                source.label,
                path,
                self.text(30047, "Pictures found"),
                stats.pictures_seen,
            )
            publisher = getattr(self.kodi, "update_scan_status", None)
            if callable(publisher):
                publisher(scan_token, source.label, path, stats.pictures_seen)
            update_dialog(0, message)

        scanner = Scanner(
            self.catalog,
            self.runtime.filesystem,
            settings,
            self.kodi.log,
            cancelled=cancelled,
            progress=progress,
            started=begin_status,
        )
        try:
            stats = scanner.scan_sources(source_ids)
            if abort_requested():
                return
            if stats.cancelled:
                self.kodi.notify(self.text(30042, "Scan cancelled"))
            else:
                message = "%s: %d, %s: %d" % (
                    self.text(30047, "Pictures found"),
                    stats.pictures_seen,
                    self.text(30050, "Errors"),
                    stats.errors,
                )
                self.kodi.notify(message, error=stats.errors > 0, milliseconds=6000)
        except RuntimeError as exc:
            if not abort_requested():
                self.kodi.notify(str(exc), error=True)
        finally:
            if scan_started:
                finisher = getattr(self.kodi, "finish_scan_status", None)
                if callable(finisher):
                    finisher(scan_token)
            if not abort_requested():
                dialog.close()
                xbmc.executebuiltin("Container.Refresh")

    def dispatch(self, request: Request):
        route = request.route
        params = request.params
        if hasattr(self.catalog, "set_rating_policy"):
            self.catalog.set_rating_policy(self._effective_rating_policy(params))
        if not route:
            return self.root(params)
        if route.startswith("action/"):
            return self.action(route, params)
        if route == "search":
            return self.search(params)
        if route == "saved-searches":
            return self.saved_searches(params)
        if route == "saved-search":
            return self.saved_search(int(params["id"]), params)
        if route == "sources":
            return self.sources(params)
        if route == "source":
            return self.source(int(params["id"]), params)
        if route == "folder":
            raw_folder_id = params.get("id")
            try:
                folder_id = int(raw_folder_id) if raw_folder_id is not None else 0
            except (TypeError, ValueError):
                folder_id = 0
            if folder_id <= 0:
                self.kodi.log.warning(
                    "Folder route ignored because its id is missing or invalid"
                )
                self.kodi.notify(
                    self.text(32737, "The album could not be opened"),
                    error=True,
                )
                return self.finish(
                    [],
                    content="images",
                    cache=False,
                    category=self.text(30054, "Root album"),
                )
            return self.folder(folder_id, params)
        if route == "recent-taken":
            return self.pictures(route, self.catalog.recent_taken, params, self.text(30001, "Recently taken"))
        if route == "recent-added":
            return self.pictures(route, self.catalog.recent_added, params, self.text(30002, "Recently added"))
        if route == "random":
            limit = safe_limit(params.get("limit"), self.kodi.settings.widget_limit)
            return self.finish(
                [self._media_item(row, browse_params=params) for row in self.catalog.random_pictures(limit)],
                category=self._rating_category(self.text(30003, "Random memories"), params),
                view_mode=self._browser_view_mode(params),
            )
        if route == "recent-folders":
            default_limit = (
                self.kodi.settings.widget_limit
                if parse_bool(params.get("widget"), False)
                else self.kodi.settings.browser_page_size
            )
            limit = safe_limit(params.get("limit"), default_limit)
            return self.folders(route, self.catalog.recent_folders(limit), self.text(30004, "Recent albums"), params)
        if route == "random-folders":
            limit = safe_limit(params.get("limit"), self.kodi.settings.widget_limit)
            return self.folders(route, self.catalog.random_folders(limit), self.text(30005, "Random albums"), params)
        if route == "on-this-day":
            now = datetime.now()
            getter = lambda limit, offset: self.catalog.on_this_day(now.month, now.day, now.year, limit, offset)
            return self.pictures(route, getter, params, self.text(30006, "On this day"))
        if route == "on-this-day-random":
            now = datetime.now()
            limit = safe_limit(params.get("limit"), self.kodi.settings.widget_limit)
            rows = self.catalog.random_on_this_day(now.month, now.day, now.year, limit)
            return self.finish(
                [
                    self._media_item(
                        row,
                        browse_params=params,
                        slideshow_route=route,
                    )
                    for row in rows
                ],
                category=self._rating_category(
                    self.text(32606, "On this day - random"),
                    params,
                ),
                view_mode=self._browser_view_mode(params),
            )
        if route == "videos":
            return self.pictures(route, self.catalog.videos, params, self.text(32600, "Videos"))
        if route == "years":
            return self.years(params)
        if route == "year":
            return self.months(int(params["year"]), params)
        if route == "month":
            return self.days(int(params["year"]), int(params["month"]), params)
        if route == "day":
            year = int(params["year"])
            month = int(params["month"])
            day = int(params["day"])
            category = "%04d-%02d-%02d" % (year, month, day)
            getter = lambda limit, offset: self.catalog.pictures_for_day(
                year, month, day, limit, offset
            )
            return self.pictures(route, getter, params, category)
        if route == "no-date":
            return self.pictures(
                route,
                self.catalog.pictures_without_date,
                params,
                self.text(30034, "No date"),
            )
        if route == "cameras":
            return self.cameras(params)
        if route == "camera":
            make, model = params.get("make", ""), params.get("model", "")
            title = " ".join(filter(None, [make, model])) or self.text(30033, "Unknown camera")
            return self.pictures(route, lambda limit, offset: self.catalog.pictures_for_camera(make, model, limit, offset), params, title)
        if route == "keywords":
            return self.keywords(params)
        if route == "tag":
            tag_id = int(params["id"])
            return self.pictures(route, lambda limit, offset: self.catalog.pictures_for_tag(tag_id, limit, offset), params, self.text(30009, "Keywords"))
        if route == "favorites":
            return self.pictures(route, self.catalog.favorites, params, self.text(30010, "Favorites"))
        if route == "rated":
            return self.pictures(route, self.catalog.rated, params, self.text(30011, "Rated pictures"))
        if route == "geotagged":
            return self.pictures(route, self.catalog.geotagged, params, self.text(30012, "Geotagged pictures"))
        if route == "status":
            return self.status()
        self.kodi.log.warning("Unknown route: %s", route)
        return self.root(params)
