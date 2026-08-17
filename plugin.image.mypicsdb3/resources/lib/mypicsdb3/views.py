from __future__ import annotations

import calendar
import hashlib
import os
import sys
import time
import uuid
from datetime import datetime
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence, Tuple

import xbmc  # type: ignore
import xbmcgui  # type: ignore
import xbmcplugin  # type: ignore

from .album_view import save_current_album_view
from .attention import ATTENTION_PRESETS, attention_preset
from .diagnostics import collect_diagnostics, write_support_bundle
from .exporter import ExportError, SafeExporter, normalize_export_name
from .home_layout_editor import (
    SmartHomeEditorText,
    show_smart_home_layout_editor,
)
from .location import format_coordinates, location_details_from_row
from .preferences import (
    DEFAULT_HOME_ROWS,
    HOME_VIEW_BY_KEY,
    MAIN_MENU_NODES,
    home_layout_slots,
    migrate_home_layout_items,
    normalize_home_layout,
    parse_hidden_main_menu_nodes,
    parse_home_layout_v2,
    parse_persisted_home_layout,
    remove_collection_from_home_layout,
    remove_saved_search_from_home_layout,
    serialize_hidden_main_menu_nodes,
    serialize_home_layout_v2,
    serialize_persisted_home_layout,
)
from .metadata_mapping import MetadataMappingRule, SOURCE_TYPES, TARGET_FIELDS
from .metadata_refresh import (
    MetadataRefreshBusy,
    MetadataRefreshNotFound,
    MetadataRefresher,
)
from .metadata_browser import (
    CATEGORIES as METADATA_BROWSER_CATEGORIES,
    category_by_key as metadata_category_by_key,
    facet_by_key as metadata_facet_by_key,
    metadata_browser_base_query,
    metadata_value_query,
)
from .music_playlists import (
    KODI_MUSIC_PLAYLIST_DIRECTORY,
    MUSIC_PLAYLIST_MASK,
    MUSIC_TARGET_MANUAL,
    MUSIC_TARGET_SMART,
    MusicPlaylistValidationError,
    music_playlist_label,
    normalize_music_target_type,
)
from .music_slideshow import (
    MusicSlideshowError,
    start_music_playlist,
    stop_music_player,
)
from .rating_policy import (
    RATING_POLICY_ALL,
    normalize_rating_policy,
    rating_policy_label,
)
from .router import Request
from .search import build_global_search_request
from .saved_searches import SavedSearchValidationError
from .static_collections import CollectionValidationError
from .smart_filter_editor import SmartFilterEditor
from .source_scan_policy import (
    SourceScanPolicy,
    source_scan_policy_from_settings,
)
from .scanner import Scanner
from .slideshow import (
    SlideshowError,
    SlideshowPlayerMismatchError,
    start_mixed_slideshow,
    start_native_directory_slideshow,
    start_native_folder_slideshow,
    start_video_playlist,
    stop_active_media_players,
)
from .utils import (
    duration_seconds,
    extension_of,
    format_duration,
    format_rate,
    kodi_generated_video_thumbnail_uri,
    kodi_image_uri,
    parse_bool,
    plugin_url,
    safe_limit,
)
from .view_mode import set_view_mode_when_container_ready


MAX_SLIDESHOW_ITEMS = 5000
HOME_FAST_IMAGE_EXTENSIONS = frozenset(
    ("jpg", "jpeg", "png", "webp", "bmp", "gif", "tif", "tiff")
)
HOME_WIDGET_CANDIDATE_MULTIPLIER = 4
HOME_WIDGET_CANDIDATE_MAXIMUM = 160
HOME_SLOT_ROUTE_BY_KEY = {
    "recent_taken": "recent-taken",
    "recent_added": "recent-added",
    "random_memories": "random",
    "recent_albums": "recent-folders",
    "random_albums": "random-folders",
    "on_this_day": "on-this-day",
    "on_this_day_random": "on-this-day-random",
    "favorites": "favorites",
    "rated": "rated",
    "geotagged": "geotagged",
}


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
        if is_video:
            return kodi_image_uri(thumbnail)
        # Keep still-picture artwork on the original file URI, matching Kodi's
        # native Media sources browser. Explicit image:// wrapping can make
        # some older JPEGs reuse their tiny embedded EXIF preview in the
        # texture cache, which then looks soft both in Home rows and when the
        # picture is opened from that row. Kodi still caches raw artwork URIs.
        return thumbnail or media_uri

    @staticmethod
    def _is_home_widget(params: Optional[Dict[str, str]]) -> bool:
        values = params or {}
        return parse_bool(values.get("widget"), False) and parse_bool(
            values.get("home"), False
        )

    def _widget_default_limit(self, params: Optional[Dict[str, str]]) -> int:
        if self._is_home_widget(params):
            return int(getattr(self.kodi.settings, "home_widget_limit", 10))
        return int(self.kodi.settings.widget_limit)

    def _result_limit(self, params: Optional[Dict[str, str]], default: int) -> int:
        values = params or {}
        if self._is_home_widget(values):
            # The add-on setting is the single source of truth. Older cached
            # Estuary provider URLs may still carry limit=10, so a URL value
            # must never override the freshly loaded typed integer setting.
            return max(
                4,
                min(40, int(getattr(self.kodi.settings, "home_widget_limit", 10))),
            )

        return safe_limit(values.get("limit"), default)

    @staticmethod
    def _home_art_priority(row: Dict[str, Any]) -> int:
        media_type = str(row.get("media_type") or "picture").lower()
        extension = str(
            row.get("extension") or extension_of(str(row.get("uri") or ""))
        ).lower()
        if media_type == "picture" and extension in HOME_FAST_IMAGE_EXTENSIONS:
            return 0
        if media_type == "picture":
            return 1
        return 2

    def _home_candidates_limit(self, limit: int) -> int:
        return min(
            HOME_WIDGET_CANDIDATE_MAXIMUM,
            max(limit, limit * HOME_WIDGET_CANDIDATE_MULTIPLIER),
        )

    def _home_random_seed(
        self, params: Optional[Dict[str, str]], route: str
    ) -> Optional[float]:
        if not self._is_home_widget(params):
            return None
        values = params or {}
        session_token = ""
        session_getter = getattr(
            self.kodi, "random_home_widget_session_token", None
        )
        if callable(session_getter):
            try:
                session_token = str(session_getter() or "")
            except Exception:
                session_token = ""
        token = "\x1f".join(
            (
                str(route or ""),
                session_token,
                str(values.get("generation") or "0"),
                str(values.get("random_generation") or "0"),
            )
        )
        digest = hashlib.sha256(token.encode("utf-8")).digest()
        return int.from_bytes(digest[:8], "big") / float(1 << 64)

    def _prioritize_home_rows(
        self,
        rows: Sequence[Dict[str, Any]],
        params: Optional[Dict[str, str]],
        limit: int,
    ) -> List[Dict[str, Any]]:
        values = list(rows)
        if not self._is_home_widget(params):
            return values
        # Python's sort is stable, so date/random order is preserved inside
        # each render-cost class. Standard stills reach Kodi's visible image
        # queue before RAW/HEIF files and generated video frames.
        values.sort(key=self._home_art_priority)
        return values[:limit]

    @staticmethod
    def _set_widget_title(item, label: str) -> None:
        """Expose a stable title for Estuary poster widgets.

        Kodi's poster layout reads ``ListItem.Title`` while picture plug-ins
        traditionally only populated ``ListItem.Label``. Publishing both keeps
        filenames and album names visible after poster artwork is supplied.
        """

        title = str(label or "")
        try:
            item.setProperty("MyPicsDB3.WidgetLabel", title)
        except Exception:
            pass
        try:
            getter = getattr(item, "getVideoInfoTag", None)
            if callable(getter):
                getter().setTitle(title)
        except Exception:
            pass

    def _item(
        self,
        label: str,
        art: Optional[str] = None,
        path: Optional[str] = None,
        publish_video_title: bool = True,
    ) -> xbmcgui.ListItem:
        item = xbmcgui.ListItem(label=label, path=path or "")
        if publish_video_title:
            self._set_widget_title(item, label)
        else:
            try:
                item.setProperty("MyPicsDB3.WidgetLabel", str(label or ""))
            except Exception:
                pass
        image = art or self.icon
        item.setArt({
            "thumb": image,
            "icon": image,
            "poster": image,
            "landscape": image,
            "fanart": self.fanart,
        })
        return item

    def add_folder(self, label: str, route: str, art: Optional[str] = None, context: Optional[List[Tuple[str, str]]] = None, **params: Any):
        target = self.url(route, **params)
        item = self._item(label, art)
        item.setProperty("MyPicsDB3.MediaType", "folder")
        item.setProperty("MyPicsDB3.WidgetPath", target)
        if context:
            item.addContextMenuItems(context)
        return (target, item, True)

    def add_action(self, label: str, route: str, art: Optional[str] = None, context: Optional[List[Tuple[str, str]]] = None, **params: Any):
        # Action rows are commands, not videos. Publishing a VideoInfoTag here
        # can make Kodi route the plug-in URL through VideoPlayer even when
        # IsPlayable is false, leaving the Python invoker waiting for a media
        # resolution after the command has already completed.
        item = self._item(label, art, publish_video_title=False)
        item.setProperty("IsPlayable", "false")
        if context:
            item.addContextMenuItems(context)
        return (self.url(route, **params), item, False)

    def add_info(self, label: str, art: Optional[str] = None):
        # Display-only rows must not publish video metadata. Kodi may otherwise
        # send an empty directory-item URL to VideoPlayer and show
        # "Playback failed" when the user presses OK on an information row.
        item = self._item(label, art, publish_video_title=False)
        item.setProperty("IsPlayable", "false")
        item.setProperty("MyPicsDB3.MediaType", "info")
        return ("", item, False)

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
            self.add_folder(self.text(32801, "Collections"), "collections", **rating_params),
            self.add_action(
                self.text(32740, "Create smart collection"),
                "action/create-smart-collection",
            ),
            self.add_folder(self.text(30000, "Picture sources"), "sources", **rating_params),
            self.add_folder(self.text(32903, "Metadata mapping"), "metadata-mapping"),
            self.add_folder(self.text(32950, "Browse metadata"), "metadata-browser", **rating_params),
            self.add_folder(self.text(32945, "Needs attention"), "needs-attention", **rating_params),
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
                self.add_action(
                    self.text(32738, "Refresh random selections"),
                    "action/refresh-random",
                ),
                scan_action,
                self.add_folder(self.text(30014, "Scan status"), "status"),
                self.add_folder(self.text(32843, "Diagnostics"), "diagnostics"),
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

    def metadata_browser(self, params: Optional[Dict[str, str]] = None):
        params = params or {}
        rating_params = self._rating_route_params(params)
        items = [
            self.add_folder(
                self.text(category.string_id, category.fallback),
                "metadata-category",
                category=category.key,
                **rating_params,
            )
            for category in METADATA_BROWSER_CATEGORIES
        ]
        self.finish(
            items,
            content="files",
            category=self._rating_category(self.text(32950, "Browse metadata"), params),
        )

    def metadata_category(self, key: str, params: Optional[Dict[str, str]] = None):
        params = params or {}
        try:
            category = metadata_category_by_key(key)
        except ValueError as exc:
            self.kodi.notify(str(exc), error=True)
            return self.finish(
                [],
                content="files",
                cache=False,
                category=self.text(32950, "Browse metadata"),
            )
        rating_params = self._rating_route_params(params)
        items = []
        for facet_key in category.facet_keys:
            facet = metadata_facet_by_key(facet_key)
            items.append(
                self.add_folder(
                    self.text(facet.string_id, facet.fallback),
                    "metadata-values",
                    field=facet.key,
                    **rating_params,
                )
            )
        self.finish(
            items,
            content="files",
            category=self._rating_category(
                self.text(category.string_id, category.fallback), params
            ),
        )

    def _metadata_value_label(self, facet_key: str, value: Any) -> str:
        text = str(value)
        if facet_key == "extension":
            return "." + text.lstrip(".")
        if facet_key == "aspect":
            labels = {
                "landscape": self.text(32881, "Landscape"),
                "portrait": self.text(32882, "Portrait"),
                "square": self.text(32883, "Square"),
            }
            return labels.get(text.lower(), text)
        if facet_key == "rating":
            return self.text(32955, "Rating %s") % text
        return text

    def metadata_values(self, field: str, params: Optional[Dict[str, str]] = None):
        params = params or {}
        try:
            facet = metadata_facet_by_key(field)
        except ValueError as exc:
            self.kodi.notify(str(exc), error=True)
            return self.finish(
                [],
                content="files",
                cache=False,
                category=self.text(32950, "Browse metadata"),
            )
        default_limit = max(1, min(499, int(self.kodi.settings.browser_page_size)))
        limit = safe_limit(params.get("limit"), default_limit)
        limit = max(1, min(499, limit))
        try:
            offset = max(0, int(params.get("offset", "0") or 0))
        except (TypeError, ValueError):
            offset = 0
        query = metadata_browser_base_query()
        rows = self.catalog.query_facet_counts(
            query, facet.catalog_field, limit + 1, offset
        )
        page_rows = rows[:limit]
        rating_params = self._rating_route_params(params)
        items = []
        for row in page_rows:
            raw_value = row.get("value")
            label = "%s  [COLOR=grey](%d)[/COLOR]" % (
                self._metadata_value_label(facet.key, raw_value),
                int(row.get("picture_count") or 0),
            )
            items.append(
                self.add_folder(
                    label,
                    "metadata-result",
                    field=facet.key,
                    value=raw_value,
                    **rating_params,
                )
            )
        if len(rows) > limit:
            items.append(
                self._next_page_item(
                    "metadata-values",
                    offset,
                    limit,
                    field=facet.key,
                    **rating_params,
                )
            )
        self.finish(
            items,
            content="files",
            cache=False,
            category=self._rating_category(
                self.text(facet.string_id, facet.fallback), params
            ),
        )

    def metadata_result(self, field: str, value: Any, params: Dict[str, str]):
        try:
            facet = metadata_facet_by_key(field)
            query = metadata_value_query(facet.key, value)
        except ValueError as exc:
            self.kodi.notify(str(exc), error=True)
            return self.finish(
                [],
                content="images",
                cache=False,
                category=self.text(32950, "Browse metadata"),
            )
        result_params = dict(params)
        result_params["field"] = facet.key
        result_params["value"] = str(value)
        category = "%s: %s" % (
            self.text(facet.string_id, facet.fallback),
            self._metadata_value_label(facet.key, value),
        )
        prefix_items = None
        if not self._is_home_widget(params):
            action_params = {
                "field": facet.key,
                "value": str(value),
                **self._rating_route_params(params),
            }
            prefix_items = [
                self._snapshot_results_action("metadata", **action_params),
                self._export_results_action("metadata", **action_params),
            ]
        return self.pictures(
            "metadata-result",
            lambda limit, offset: self.catalog.query_pictures(query, limit, offset),
            result_params,
            category,
            prefix_items=prefix_items,
        )

    def needs_attention(self, params: Optional[Dict[str, str]] = None):
        params = params or {}
        rating_params = self._rating_route_params(params)
        items = []
        for preset in ATTENTION_PRESETS:
            total = int(self.catalog.count_query_pictures(preset.query))
            label = "%s  [COLOR=grey](%d)[/COLOR]" % (
                self.text(preset.string_id, preset.fallback),
                total,
            )
            items.append(
                self.add_folder(
                    label,
                    "needs-attention-result",
                    kind=preset.key,
                    **rating_params,
                )
            )
        self.finish(
            items,
            content="files",
            category=self._rating_category(self.text(32945, "Needs attention"), params),
        )

    def needs_attention_result(self, kind: str, params: Dict[str, str]):
        try:
            preset = attention_preset(kind)
        except ValueError as exc:
            self.kodi.notify(str(exc), error=True)
            return self.finish(
                [],
                content="images",
                cache=False,
                category=self.text(32945, "Needs attention"),
            )
        result_params = dict(params)
        result_params["kind"] = preset.key
        prefix_items = None
        if not self._is_home_widget(params):
            action_params = {
                "kind": preset.key,
                **self._rating_route_params(params),
            }
            prefix_items = [
                self._snapshot_results_action("needs-attention", **action_params),
                self._export_results_action("needs-attention", **action_params),
            ]
        return self.pictures(
            "needs-attention-result",
            lambda limit, offset: self.catalog.query_pictures(
                preset.query,
                limit,
                offset,
            ),
            result_params,
            self.text(preset.string_id, preset.fallback),
            prefix_items=prefix_items,
        )

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
        action_params = {
            "q": request.text,
            **self._rating_route_params(search_params),
        }
        snapshot_item = self._snapshot_results_action("search", **action_params)
        export_item = self._export_results_action("search", **action_params)
        return self.pictures(
            "search",
            lambda limit, offset: self.catalog.query_pictures(
                request.query,
                limit,
                offset,
            ),
            search_params,
            category,
            prefix_items=[save_item, snapshot_item, export_item],
        )

    def _snapshot_results_action(self, scope: str, **params):
        return self.add_action(
            self.text(32957, "Save current results as collection"),
            "action/snapshot-results",
            scope=scope,
            **params,
        )

    def _export_results_action(self, scope: str, **params):
        return self.add_action(
            self.text(32966, "Export current results"),
            "action/export-results",
            scope=scope,
            **params,
        )

    def _export_selection_from_params(
        self, params: Dict[str, str]
    ) -> Tuple[List[int], str]:
        scope = str(params.get("scope") or "").strip()
        if scope == "collection":
            collection_id = int(params.get("id") or 0)
            collection = self.catalog.get_collection(collection_id)
            if collection is None:
                raise ValueError(self.text(32809, "Collection was not found"))
            return (
                self.catalog.ordered_collection_picture_ids(collection_id),
                collection.name,
            )
        query, suggested_name = self._snapshot_query_from_params(params)
        return self.catalog.ordered_query_picture_ids(query), suggested_name

    def _snapshot_query_from_params(
        self, params: Dict[str, str]
    ) -> Tuple[Any, str]:
        scope = str(params.get("scope") or "").strip()
        if scope == "search":
            request = build_global_search_request(params.get("q", ""))
            return request.query, "%s - %s" % (
                self.text(32500, "Search"), request.text
            )
        if scope == "saved-search":
            saved_id = int(params.get("id") or 0)
            saved = self.catalog.get_saved_search(saved_id)
            if saved is None:
                raise ValueError(self.text(32901, "Source was not found"))
            return saved.query, saved.name
        if scope == "metadata":
            facet = metadata_facet_by_key(params.get("field", ""))
            value = params.get("value", "")
            query = metadata_value_query(facet.key, value)
            name = "%s - %s" % (
                self.text(facet.string_id, facet.fallback),
                self._metadata_value_label(facet.key, value),
            )
            return query, name
        if scope == "needs-attention":
            preset = attention_preset(params.get("kind", ""))
            return preset.query, self.text(preset.string_id, preset.fallback)
        raise ValueError("Unknown collection snapshot source")

    def _music_playlist_context(
        self, collection_type: str, collection_id: int, playlist_uri: str
    ) -> List[Tuple[str, str]]:
        assign_label = (
            self.text(32832, "Change music playlist")
            if playlist_uri
            else self.text(32831, "Assign music playlist")
        )
        context = [
            (
                assign_label,
                "RunPlugin(%s)"
                % self.url(
                    "action/assign-music-playlist",
                    type=collection_type,
                    id=collection_id,
                ),
            )
        ]
        if playlist_uri:
            context.append(
                (
                    self.text(32833, "Remove music playlist"),
                    "RunPlugin(%s)"
                    % self.url(
                        "action/remove-music-playlist",
                        type=collection_type,
                        id=collection_id,
                    ),
                )
            )
        return context

    def _music_slideshow_action(
        self, scope: str, collection_id: int, playlist_uri: str
    ):
        label = self.text(32834, "Play picture slideshow with music")
        playlist_name = music_playlist_label(playlist_uri)
        if playlist_name:
            label = "%s  [COLOR=grey](%s)[/COLOR]" % (label, playlist_name)
        return self.add_action(
            label,
            "action/start-music-slideshow",
            scope=scope,
            id=collection_id,
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
            music_uri = str(row.get("music_playlist_uri") or "")
            context = [
                (self.text(32705, "Rename saved search"), rename),
                (self.text(32706, "Delete saved search"), delete),
            ]
            context.extend(
                self._music_playlist_context(
                    MUSIC_TARGET_SMART, saved_id, music_uri
                )
            )
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
            self.kodi.notify(self.text(32901, "Source was not found"), error=True)
            return self.finish(
                [],
                content="images",
                cache=False,
                category=self.text(32700, "Saved searches"),
            )
        saved_params = dict(params)
        saved_params["id"] = str(saved.id)
        music_uri = self.catalog.get_music_playlist(
            MUSIC_TARGET_SMART, saved.id
        )
        prefix_items = []
        if not self._is_home_widget(params):
            action_params = {
                "id": saved.id,
                **self._rating_route_params(params),
            }
            prefix_items.append(
                self._snapshot_results_action("saved-search", **action_params)
            )
            prefix_items.append(
                self._export_results_action("saved-search", **action_params)
            )
            if music_uri:
                prefix_items.append(
                    self._music_slideshow_action(
                        "saved-search", saved.id, music_uri
                    )
                )
        return self.pictures(
            "saved-search",
            lambda limit, offset: self.catalog.query_pictures(
                saved.query,
                limit,
                offset,
            ),
            saved_params,
            saved.name,
            prefix_items=prefix_items,
        )

    def collections(self, params: Optional[Dict[str, str]] = None):
        params = params or {}
        rating_params = self._rating_route_params(params)
        items = [
            self.add_action(
                self.text(32802, "Create collection"),
                "action/create-collection",
            )
        ]
        for row in self.catalog.list_collections():
            collection_id = int(row["id"])
            count = int(row.get("available_count") or 0)
            label = "%s  [COLOR=grey](%d)[/COLOR]" % (row["name"], count)
            rename = "RunPlugin(%s)" % self.url(
                "action/rename-collection", id=collection_id
            )
            delete = "RunPlugin(%s)" % self.url(
                "action/delete-collection", id=collection_id
            )
            music_uri = str(row.get("music_playlist_uri") or "")
            context = [
                (self.text(32803, "Rename collection"), rename),
                (self.text(32804, "Delete collection"), delete),
            ]
            context.extend(
                self._music_playlist_context(
                    MUSIC_TARGET_MANUAL, collection_id, music_uri
                )
            )
            art = self._media_art_uri(
                row.get("uri"), row.get("thumb_uri"), row.get("media_type")
            ) or self.icon
            items.append(
                self.add_folder(
                    label,
                    "collection",
                    art=art,
                    context=context,
                    id=collection_id,
                    **rating_params,
                )
            )
        self.finish(
            items,
            content="files",
            category=self._rating_category(
                self.text(32801, "Collections"), params
            ),
        )

    def collection(self, collection_id: int, params: Dict[str, str]):
        try:
            collection = self.catalog.get_collection(collection_id)
        except CollectionValidationError as exc:
            self.kodi.log.warning("Could not read collection %s: %s", collection_id, exc)
            collection = None
        if collection is None:
            self.kodi.notify(
                self.text(32809, "Collection was not found"), error=True
            )
            return self.finish(
                [],
                content="images",
                cache=False,
                category=self.text(32801, "Collections"),
            )

        is_widget = self._is_home_widget(params)
        default_limit = (
            self._widget_default_limit(params)
            if is_widget
            else self.kodi.settings.browser_page_size
        )
        limit = self._result_limit(params, default_limit)
        offset = int(params.get("offset", "0") or 0)
        rows = self.catalog.pictures_in_collection(
            collection_id, limit, offset
        )
        count_getter = getattr(self.catalog, "collection_available_count", None)
        total = (
            int(count_getter(collection_id))
            if callable(count_getter)
            else offset + len(rows)
        )
        items = []
        if offset == 0 and not is_widget:
            items.append(
                self.add_action(
                    self.text(32818, "Play collection slideshow"),
                    "action/start-slideshow",
                    scope="collection",
                    id=collection_id,
                    **self._rating_route_params(params),
                )
            )
            items.append(
                self.add_action(
                    self.text(32967, "Export collection"),
                    "action/export-results",
                    scope="collection",
                    id=collection_id,
                    **self._rating_route_params(params),
                )
            )
            music_uri = self.catalog.get_music_playlist(
                MUSIC_TARGET_MANUAL, collection_id
            )
            if music_uri:
                items.append(
                    self._music_slideshow_action(
                        "collection", collection_id, music_uri
                    )
                )
        for row_index, row in enumerate(rows):
            picture_id = int(row.get("id") or 0)
            absolute_index = offset + row_index
            context = []
            if absolute_index > 0:
                context.extend(
                    [
                        (
                            self.text(32211, "Move up"),
                            "RunPlugin(%s)"
                            % self.url(
                                "action/move-collection-item",
                                collection=collection_id,
                                id=picture_id,
                                direction="up",
                            ),
                        ),
                        (
                            self.text(32823, "Move to top"),
                            "RunPlugin(%s)"
                            % self.url(
                                "action/move-collection-item",
                                collection=collection_id,
                                id=picture_id,
                                direction="top",
                            ),
                        ),
                    ]
                )
            if absolute_index + 1 < total:
                context.extend(
                    [
                        (
                            self.text(32212, "Move down"),
                            "RunPlugin(%s)"
                            % self.url(
                                "action/move-collection-item",
                                collection=collection_id,
                                id=picture_id,
                                direction="down",
                            ),
                        ),
                        (
                            self.text(32824, "Move to bottom"),
                            "RunPlugin(%s)"
                            % self.url(
                                "action/move-collection-item",
                                collection=collection_id,
                                id=picture_id,
                                direction="bottom",
                            ),
                        ),
                    ]
                )
            remove = "RunPlugin(%s)" % self.url(
                "action/remove-from-collection",
                collection=collection_id,
                id=picture_id,
            )
            context.append((self.text(32813, "Remove from collection"), remove))
            items.append(
                self._media_item(
                    row,
                    extra_context=context,
                    browse_params=params,
                    slideshow_route="collection",
                )
            )
        if len(rows) == limit and "limit" not in params and not is_widget:
            page_params = {
                key: value
                for key, value in params.items()
                if key not in {"id", "offset", "limit", "widget"}
            }
            items.append(
                self._next_page_item(
                    "collection",
                    offset,
                    limit,
                    id=collection_id,
                    **page_params,
                )
            )
        self.finish(
            items,
            content="images",
            cache=False,
            category=self._rating_category(collection.name, params),
            view_mode=self._browser_view_mode(params),
        )

    def _finish_native_picture_directory(
        self,
        rows: Sequence[Dict[str, Any]],
        log_message: str,
        log_id: int,
    ):
        """Return an ordered, picture-only directory for Kodi SlideShow."""

        items = []
        seen = set()
        for row in rows:
            if str(row.get("media_type") or "picture") == "video":
                continue
            media_uri = str(row.get("uri") or "").strip()
            if not media_uri or media_uri in seen:
                continue
            seen.add(media_uri)
            date_text = str(
                row.get("taken_at") or row.get("discovered_at") or ""
            )
            visible_label = str(
                row.get("filename") or date_text or self.text(30031, "Picture")
            )
            sort_label = "%06d %s" % (len(items) + 1, visible_label)
            art_uri = self._media_art_uri(
                media_uri, row.get("thumb_uri"), "picture"
            )
            item = self._item(
                sort_label,
                art_uri,
                media_uri,
                publish_video_title=False,
            )
            info: Dict[str, Any] = {
                "title": visible_label,
                "picturepath": media_uri,
                "date": date_text,
            }
            if row.get("width") and row.get("height"):
                info["resolution"] = "%sx%s" % (row["width"], row["height"])
            if row.get("camera_make"):
                info["cameramake"] = row["camera_make"]
            if row.get("camera_model"):
                info["cameramodel"] = row["camera_model"]
            if row.get("caption"):
                info["exifcomment"] = row["caption"]
            try:
                self._set_picture_info(
                    item, info, date_text, row.get("width"), row.get("height")
                )
            except Exception:
                pass
            item.setProperty("MyPicsDB3.MediaType", "picture")
            item.setProperty("MyPicsDB3.PictureId", str(row.get("id", "")))
            items.append((media_uri, item, False))

        self.kodi.log.debug(log_message, log_id, len(items))
        return self.finish(items, content="images", cache=False)

    def collection_slideshow_pictures(
        self, collection_id: int, params: Dict[str, str]
    ):
        """Expose still pictures from one collection to Kodi's slideshow loader.

        The route is intentionally not linked from the browser. Kodi's native
        ``SlideShow`` built-in opens it through the directory layer, where each
        returned URL is a real still-image path. Labels carry a zero-padded
        position prefix because Kodi sorts slideshow directory results by label;
        picture metadata keeps the visible title free of that internal prefix.
        """

        rows = self.catalog.pictures_in_collection(
            collection_id, MAX_SLIDESHOW_ITEMS, 0
        )
        return self._finish_native_picture_directory(
            rows,
            "Native collection picture directory: collection_id=%s items=%d",
            collection_id,
        )

    def saved_search_slideshow_pictures(
        self, saved_search_id: int, params: Dict[str, str]
    ):
        """Expose picture-only smart-collection results to Kodi's slideshow."""

        try:
            saved = self.catalog.get_saved_search(saved_search_id)
        except SavedSearchValidationError as exc:
            self.kodi.log.warning(
                "Could not read smart collection %s for slideshow: %s",
                saved_search_id,
                exc,
            )
            saved = None
        if saved is None:
            return self.finish([], content="images", cache=False)
        rows = self.catalog.query_pictures(
            saved.query, MAX_SLIDESHOW_ITEMS, 0
        )
        return self._finish_native_picture_directory(
            rows,
            "Native smart-collection picture directory: "
            "saved_search_id=%s items=%d",
            saved_search_id,
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
            policy_getter = getattr(self.catalog, "get_source_scan_policy", None)
            explicit_policy = policy_getter(source.id) if callable(policy_getter) else None
            policy_state = (
                self.text(32887, "Custom scan settings")
                if explicit_policy is not None
                else self.text(32886, "Global scan defaults")
            )
            label = "%s  [COLOR=grey](%s; %s)[/COLOR]" % (source.label, state, policy_state)
            toggle = "RunPlugin(%s)" % self.url("action/toggle-source", id=source.id)
            scan = "RunPlugin(%s)" % self.url("action/scan", source=source.id)
            scan_settings = "RunPlugin(%s)" % self.url("action/source-scan-settings", id=source.id)
            toggle_label = self.text(30064, "Disable source") if source.enabled else self.text(30063, "Enable source")
            context = [
                (toggle_label, toggle),
                (self.text(30021, "Scan selected source"), scan),
                (self.text(32885, "Source scan settings"), scan_settings),
            ]
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

    @staticmethod
    def _set_picture_info(
        item,
        info: Dict[str, Any],
        date_text: str,
        width: Any,
        height: Any,
    ) -> None:
        """Use Kodi's picture InfoTag where available, retaining a safe fallback."""

        getter = getattr(item, "getPictureInfoTag", None)
        if callable(getter):
            tag = getter()
            if width and height and hasattr(tag, "setResolution"):
                tag.setResolution(int(width), int(height))
            if date_text and hasattr(tag, "setDateTimeTaken"):
                tag.setDateTimeTaken(str(date_text))
            # InfoTagPicture does not expose title, camera, comment or path
            # setters yet, so keep only those compatibility fields here.
            compatibility = {
                key: value
                for key, value in info.items()
                if key not in {"resolution", "date"}
            }
            if compatibility:
                item.setInfo("pictures", compatibility)
            return
        item.setInfo("pictures", info)

    def _location_context(
        self,
        row: Dict[str, Any],
        browse_params: Optional[Dict[str, str]] = None,
    ) -> List[Tuple[str, str]]:
        if str(row.get("media_type") or "picture") != "picture":
            return []

        details = location_details_from_row(
            row,
            include_coordinates=bool(getattr(self.kodi.settings, "store_gps", False)),
        )
        context: List[Tuple[str, str]] = [
            (
                self.text(32979, "Location details"),
                "RunPlugin(%s)"
                % self.url("action/location-details", id=row.get("id")),
            )
        ]
        rating_params = self._rating_route_params(browse_params)
        if details.city:
            context.append(
                (
                    self.text(32980, "Browse this city"),
                    "ActivateWindow(Pictures,%s,return)"
                    % self.url(
                        "metadata-result",
                        field="city",
                        value=details.city,
                        **rating_params,
                    ),
                )
            )
        if details.country:
            context.append(
                (
                    self.text(32981, "Browse this country"),
                    "ActivateWindow(Pictures,%s,return)"
                    % self.url(
                        "metadata-result",
                        field="country",
                        value=details.country,
                        **rating_params,
                    ),
                )
            )
        return context

    def _show_location_details(self, picture_id: int) -> None:
        row = self.catalog.picture_by_id(picture_id)
        if not row or str(row.get("media_type") or "picture") != "picture":
            self.kodi.notify(self.text(32987, "Picture was not found"), error=True)
            return

        store_gps = bool(getattr(self.kodi.settings, "store_gps", False))
        details = location_details_from_row(row, include_coordinates=store_gps)
        lines: List[str] = []
        for label, value in (
            (self.text(32876, "Country"), details.country),
            (self.text(32877, "State or region"), details.state),
            (self.text(32878, "City"), details.city),
            (self.text(32879, "Sublocation"), details.sublocation),
        ):
            if value:
                lines.append("%s: %s" % (label, value))

        coordinates = format_coordinates(details)
        if coordinates:
            lines.append("%s: %s" % (self.text(32983, "Coordinates"), coordinates))
        elif not store_gps:
            lines.append(
                self.text(
                    32984,
                    "GPS coordinates are not stored because GPS storage is disabled. "
                    "Enable Metadata > Store GPS coordinates and run a scan to index them.",
                )
            )
        else:
            lines.append(self.text(32985, "No GPS coordinates are stored for this picture."))

        if not details.has_named_location and not coordinates:
            lines.insert(0, self.text(32986, "No location metadata is stored for this picture."))

        xbmcgui.Dialog().ok(
            self.text(32982, "Location"),
            "\n".join(lines),
        )

    def _metadata_refresh_context(self, row: Dict[str, Any]) -> List[Tuple[str, str]]:
        if str(row.get("media_type") or "picture") != "picture" or not row.get("id"):
            return []
        return [
            (
                self.text(32988, "Refresh metadata"),
                "RunPlugin(%s)"
                % self.url("action/refresh-metadata-picture", id=row.get("id")),
            ),
            (
                self.text(32989, "Metadata diagnostics"),
                "RunPlugin(%s)"
                % self.url("action/metadata-diagnostics", id=row.get("id")),
            ),
        ]

    @staticmethod
    def _diagnostic_value(value: Any) -> str:
        text = str(value or "").strip()
        return text if text else "-"

    def _metadata_refresher(self):
        settings = self.kodi.refresh_settings()
        return MetadataRefresher(
            self.catalog,
            self.runtime.filesystem,
            settings,
            self.kodi.log,
        )

    def _show_metadata_diagnostics(self, picture_id: int) -> None:
        try:
            refresher = self._metadata_refresher()
            inspection = refresher.inspect_picture(picture_id)
        except MetadataRefreshNotFound:
            self.kodi.notify(self.text(32987, "Picture was not found"), error=True)
            return
        except Exception as exc:
            self.kodi.notify(
                "%s: %s" % (self.text(32998, "Could not inspect metadata"), exc),
                error=True,
                milliseconds=7000,
            )
            return

        row = inspection.row
        fresh = inspection.fresh
        source = inspection.source_details
        store_gps = bool(getattr(refresher.settings, "store_gps", False))
        indexed_location = location_details_from_row(row, include_coordinates=store_gps)
        fresh_location = location_details_from_row(
            {
                "country": (fresh.location or {}).get("country"),
                "state": (fresh.location or {}).get("state"),
                "city": (fresh.location or {}).get("city"),
                "sublocation": (fresh.location or {}).get("sublocation"),
                "gps_latitude": fresh.gps_latitude,
                "gps_longitude": fresh.gps_longitude,
            },
            include_coordinates=store_gps,
        )
        indexed_coordinates = format_coordinates(indexed_location)
        fresh_coordinates = format_coordinates(fresh_location)

        yes = self.text(32994, "yes")
        no = self.text(32995, "no")
        lines = [
            "%s: %s" % (self.text(32999, "File"), self._diagnostic_value(row.get("filename"))),
            "",
            self.text(33000, "Indexed values"),
            "%s: %s" % (self.text(32922, "Camera make"), self._diagnostic_value(row.get("camera_make"))),
            "%s: %s" % (self.text(32923, "Camera model"), self._diagnostic_value(row.get("camera_model"))),
            "%s: %s" % (self.text(32983, "Coordinates"), self._diagnostic_value(indexed_coordinates)),
            "%s: %s" % (self.text(32878, "City"), self._diagnostic_value(row.get("city"))),
            "%s: %s" % (self.text(32876, "Country"), self._diagnostic_value(row.get("country"))),
            "",
            self.text(33001, "Fresh extraction"),
            "%s: %s" % (self.text(32922, "Camera make"), self._diagnostic_value(fresh.camera_make)),
            "%s: %s" % (self.text(32923, "Camera model"), self._diagnostic_value(fresh.camera_model)),
            "%s: %s" % (self.text(32983, "Coordinates"), self._diagnostic_value(fresh_coordinates)),
            "%s: %s" % (self.text(32878, "City"), self._diagnostic_value((fresh.location or {}).get("city"))),
            "%s: %s" % (self.text(32876, "Country"), self._diagnostic_value((fresh.location or {}).get("country"))),
            "",
            self.text(33002, "Extractor details"),
            "%s: %s" % (self.text(33003, "EXIF reader available"), yes if source.get("exifread_available") else no),
            "%s: %s" % (self.text(33004, "EXIF tags found"), int(source.get("exif_tag_count") or 0)),
            "%s: %s" % (self.text(33005, "Raw EXIF Make"), self._diagnostic_value(source.get("exif_make"))),
            "%s: %s" % (self.text(33006, "Raw EXIF Model"), self._diagnostic_value(source.get("exif_model"))),
            "%s: %s/%s" % (
                self.text(33007, "EXIF GPS latitude/longitude tags"),
                yes if source.get("gps_latitude_present") else no,
                yes if source.get("gps_longitude_present") else no,
            ),
            "%s: %s" % (self.text(33008, "Embedded XMP found"), yes if source.get("xmp_present") else no),
            "%s: %s" % (
                self.text(33020, "XMP GPS latitude"),
                self._diagnostic_value(source.get("xmp_gps_latitude_raw")),
            ),
            "%s: %s" % (
                self.text(33021, "XMP GPS longitude"),
                self._diagnostic_value(source.get("xmp_gps_longitude_raw")),
            ),
            "%s: %s" % (
                self.text(33022, "GPS source"),
                self._diagnostic_value(source.get("gps_source")),
            ),
            "%s: %s" % (self.text(33009, "IPTC loaded"), yes if source.get("iptc_loaded") else no),
            "%s: %s" % (self.text(33010, "Store GPS coordinates"), yes if store_gps else no),
            "%s: %s"
            % (
                self.text(33016, "Metadata header bytes buffered"),
                int(source.get("prefix_bytes_read") or 0),
            ),
            "%s: %s"
            % (
                self.text(33017, "Embedded EXIF block found"),
                yes if source.get("embedded_exif_found") else no,
            ),
            "%s: %s"
            % (
                self.text(33014, "Core EXIF fallback used"),
                yes if source.get("exif_fallback_used") else no,
            ),
        ]
        xmp_location_fields = source.get("xmp_location_fields") or {}
        if xmp_location_fields:
            lines.append("")
            lines.append(self.text(33023, "XMP location/GPS fields"))
            for field_name in sorted(xmp_location_fields, key=lambda value: str(value).casefold())[:12]:
                field_value = str(xmp_location_fields.get(field_name) or "").strip()
                if len(field_value) > 160:
                    field_value = field_value[:157] + "..."
                lines.append("%s: %s" % (field_name, self._diagnostic_value(field_value)))

        if source.get("exif_fallback_used"):
            lines.append(
                "%s: %s"
                % (
                    self.text(33015, "Fallback EXIF tags found"),
                    int(source.get("exif_fallback_tag_count") or 0),
                )
            )
        if source.get("exif_error"):
            lines.append(
                "%s: %s"
                % (self.text(33011, "EXIF reader error"), source.get("exif_error"))
            )
        if source.get("prefix_error"):
            lines.append(
                "%s: %s"
                % (self.text(33018, "Metadata prefix read error"), source.get("prefix_error"))
            )
        if source.get("dimension_error"):
            lines.append(
                "%s: %s"
                % (self.text(33019, "Image dimension probe error"), source.get("dimension_error"))
            )
        dialog = xbmcgui.Dialog()
        heading = self.text(32989, "Metadata diagnostics")
        message = "\n".join(lines)
        textviewer = getattr(dialog, "textviewer", None)
        if callable(textviewer):
            textviewer(heading, message)
        else:
            dialog.ok(heading, message)

    def _show_metadata_refresh_busy(self) -> None:
        xbmcgui.Dialog().ok(
            self.text(33024, "Metadata refresh unavailable"),
            self.text(
                33025,
                "A catalogue scan, schema migration or another metadata refresh is active. Wait for it to finish and try again.",
            ),
        )

    def _refresh_picture_metadata(self, picture_id: int) -> None:
        row = self.catalog.picture_by_id(picture_id)
        if not row or str(row.get("media_type") or "picture") != "picture":
            self.kodi.notify(self.text(32987, "Picture was not found"), error=True)
            return
        if not xbmcgui.Dialog().yesno(
            self.text(32988, "Refresh metadata"),
            self.text(32991, "Re-read metadata for '%s'? The source file will not be modified.")
            % str(row.get("filename") or self.text(30031, "Picture")),
        ):
            return
        try:
            self._metadata_refresher().refresh_picture(picture_id)
        except MetadataRefreshBusy:
            self._show_metadata_refresh_busy()
            return
        except Exception as exc:
            self.kodi.notify(
                "%s: %s" % (self.text(32996, "Metadata refresh failed"), exc),
                error=True,
                milliseconds=7000,
            )
            return
        self._invalidate_home_widgets("picture metadata refreshed")
        self.kodi.notify(self.text(32992, "Metadata refreshed"))
        xbmc.executebuiltin("Container.Refresh")

    def _refresh_folder_metadata(self, folder_id: int) -> None:
        folder = self.catalog.get_folder(folder_id)
        if not folder:
            self.kodi.notify(self.text(32997, "Folder was not found"), error=True)
            return
        picture_ids = self.catalog.picture_ids_in_folder(folder_id)
        if not picture_ids:
            self.kodi.notify(self.text(33012, "No pictures in this folder"))
            return
        if not xbmcgui.Dialog().yesno(
            self.text(32990, "Refresh metadata in this folder"),
            self.text(32993, "Re-read metadata for %d pictures directly in '%s'? Source files will not be modified and subfolders are not included.")
            % (len(picture_ids), str(folder.get("name") or self.text(30032, "Album"))),
        ):
            return

        dialog = xbmcgui.DialogProgress()
        try:
            dialog.create(
                self.text(32990, "Refresh metadata in this folder"),
                str(folder.get("name") or self.text(30032, "Album")),
            )

            def cancelled() -> bool:
                checker = getattr(dialog, "iscanceled", None)
                return bool(callable(checker) and checker())

            def progress(index: int, total: int, filename: str) -> None:
                percent = int((index * 100) / max(1, total))
                dialog.update(percent, "%d / %d" % (index, total), filename or "")

            refresher = self._metadata_refresher()
            stats = refresher.refresh_folder(
                folder_id, cancelled=cancelled, progress=progress
            )
        except MetadataRefreshBusy:
            self._show_metadata_refresh_busy()
            return
        except Exception as exc:
            self.kodi.notify(
                "%s: %s" % (self.text(32996, "Metadata refresh failed"), exc),
                error=True,
                milliseconds=7000,
            )
            return
        finally:
            try:
                dialog.close()
            except Exception:
                pass

        if stats.refreshed:
            self._invalidate_home_widgets("folder metadata refreshed")
        self.kodi.notify(
            self.text(33013, "Metadata refresh complete: %d refreshed, %d failed")
            % (stats.refreshed, stats.failed),
            error=stats.failed > 0,
            milliseconds=6000,
        )
        xbmc.executebuiltin("Container.Refresh")

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
        # Do not create a VideoInfoTag for ordinary still-picture rows. Kodi
        # can otherwise route a direct JPEG/PNG path through VideoPlayer instead
        # of the native picture viewer. Videos receive their VideoInfoTag below.
        item = self._item(
            label,
            art_uri,
            media_uri,
            publish_video_title=False,
        )
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
                self._set_picture_info(
                    item, info, date_text, row.get("width"), row.get("height")
                )
        except Exception:
            pass
        item.setProperty("MyPicsDB3.MediaType", media_type)
        item.setProperty("MyPicsDB3.WidgetPath", media_uri)
        item.setProperty("MyPicsDB3.PictureId", str(row.get("id", "")))
        item.setProperty("MyPicsDB3.TakenAt", date_text)
        item.setProperty("MyPicsDB3.Camera", " ".join(filter(None, [row.get("camera_make"), row.get("camera_model")])))
        item.setProperty("MyPicsDB3.Folder", str(row.get("folder_name") or ""))
        item.setProperty("MyPicsDB3.Source", str(row.get("source_label") or ""))
        if row.get("rating") is not None:
            item.setProperty("MyPicsDB3.Rating", str(row["rating"]))
        toggle = "RunPlugin(%s)" % self.url("action/toggle-favorite", id=row.get("id"))
        add_to_collection = "RunPlugin(%s)" % self.url(
            "action/add-to-collection", id=row.get("id")
        )
        context = [
            (self.text(30022, "Toggle favorite"), toggle),
            (self.text(32812, "Add to collection"), add_to_collection),
        ]
        context.extend(self._metadata_refresh_context(row))
        context.extend(self._location_context(row, browse_params))
        if self._is_home_widget(browse_params):
            context.append(
                (
                    self.text(32842, "Open Collections"),
                    "ActivateWindow(Pictures,%s,return)"
                    % self.url("collections"),
                )
            )
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
            row.get("representative_uri"),
            row.get("representative_thumb"),
            row.get("representative_media_type"),
        ) or self.icon
        context = [(self.text(30021, "Scan selected source"), "RunPlugin(%s)" % self.url("action/scan", source=row.get("source_id")))]
        if row.get("id"):
            context.append(
                (
                    self.text(32990, "Refresh metadata in this folder"),
                    "RunPlugin(%s)"
                    % self.url("action/refresh-metadata-folder", id=row["id"]),
                )
            )
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
            self._widget_default_limit(params)
            if is_widget
            else self.kodi.settings.browser_page_size
        )
        limit = self._result_limit(params, default_limit)
        offset = int(params.get("offset", "0") or 0)
        query_limit = (
            self._home_candidates_limit(limit)
            if self._is_home_widget(params)
            else limit
        )
        rows = self._prioritize_home_rows(
            getter(query_limit, offset), params, limit
        )
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
                    art=self._media_art_uri(row.get("uri"), row.get("thumb_uri"), row.get("media_type")),
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
                    art=self._media_art_uri(undated.get("uri"), undated.get("thumb_uri"), undated.get("media_type")),
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
                    art=self._media_art_uri(row.get("uri"), row.get("thumb_uri"), row.get("media_type")),
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
                    art=self._media_art_uri(row.get("uri"), row.get("thumb_uri"), row.get("media_type")),
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
            items.append(self.add_folder(label, "camera", art=self._media_art_uri(row.get("uri"), row.get("thumb_uri"), row.get("media_type")), make=row.get("camera_make", ""), model=row.get("camera_model", ""), **rating_params))
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
            items.append(self.add_folder(label, "tag", art=self._media_art_uri(row.get("uri"), row.get("thumb_uri"), row.get("media_type")), id=row["id"], **rating_params))
        self.finish(
            items,
            content="images",
            category=self._rating_category(self.text(30009, "Keywords"), params),
            view_mode=self._browser_view_mode(params),
        )

    def _saved_search_name_map(self) -> Dict[int, str]:
        return {
            int(row["id"]): str(row["name"])
            for row in self.catalog.list_saved_searches()
        }

    def _collection_name_map(self) -> Dict[int, str]:
        return {
            int(row["id"]): str(row["name"])
            for row in self.catalog.list_collections()
        }

    def _load_home_layout_items(
        self,
        saved_names: Dict[int, str],
        collection_names: Dict[int, str],
    ):
        parsed = parse_home_layout_v2(
            self.kodi.addon.getSetting("home_layout_v2"),
            saved_names.keys(),
            collection_names.keys(),
        )
        if parsed is not None:
            return parsed

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
        return migrate_home_layout_items(order, enabled)

    def _write_home_layout_items(
        self,
        items,
        saved_names: Dict[int, str],
        collection_names: Dict[int, str],
    ) -> None:
        self.kodi.addon.setSetting(
            "home_layout_v2", serialize_home_layout_v2(items)
        )
        slots = home_layout_slots(items, saved_names, collection_names)
        for position, slot in enumerate(slots, start=1):
            self.kodi.addon.setSetting(
                "home_row_%d" % position, str(slot["row"])
            )
            self.kodi.addon.setSetting(
                "home_smart_id_%d" % position, str(slot["smart_id"])
            )
            self.kodi.addon.setSetting(
                "home_smart_name_%d" % position, str(slot["smart_name"])
            )
            self.kodi.addon.setSetting(
                "home_smart_mode_%d" % position, str(slot["smart_mode"])
            )
            self.kodi.addon.setSetting(
                "home_collection_id_%d" % position,
                str(slot["collection_id"]),
            )
            self.kodi.addon.setSetting(
                "home_collection_name_%d" % position,
                str(slot["collection_name"]),
            )

        # Preserve the old built-in-only layout for downgrade compatibility.
        builtin_order = [item.key for item in items if item.kind == "builtin"]
        builtin_enabled = [
            item.key
            for item in items
            if item.kind == "builtin" and item.enabled
        ]
        self.kodi.addon.setSetting(
            "home_layout",
            serialize_persisted_home_layout(builtin_order, builtin_enabled),
        )

    def _invalidate_home_widgets(self, reason: str) -> None:
        invalidator = getattr(self.kodi, "invalidate_home_widgets", None)
        if callable(invalidator):
            try:
                invalidator(reason)
            except Exception as exc:
                self.kodi.log.warning(
                    "Could not invalidate home-screen widgets: %s", exc
                )

    def _invalidate_random_home_widgets(self, reason: str) -> None:
        invalidator = getattr(self.kodi, "invalidate_random_home_widgets", None)
        if callable(invalidator):
            try:
                invalidator(reason)
            except Exception as exc:
                self.kodi.log.warning(
                    "Could not invalidate random home-screen widgets: %s", exc
                )

    def _configure_home_screen(self) -> None:
        saved_names = self._saved_search_name_map()
        collection_names = self._collection_name_map()
        items = self._load_home_layout_items(saved_names, collection_names)
        result = show_smart_home_layout_editor(
            items,
            {
                key: self.text(view.string_id, view.fallback)
                for key, view in HOME_VIEW_BY_KEY.items()
            },
            saved_names,
            SmartHomeEditorText(
                heading=self.text(32208, "Configure home-screen rows"),
                row_heading=self.text(32799, "Home-screen row"),
                visible_heading=self.text(32218, "Enabled"),
                order_heading=self.text(32800, "Order"),
                on=self.text(32223, "On"),
                off=self.text(32224, "Off"),
                move_up=self.text(32211, "Move up"),
                move_down=self.text(32212, "Move down"),
                save=self.text(32225, "Save"),
                cancel=self.text(32226, "Cancel"),
                defaults=self.text(32227, "Defaults"),
                add_collection=self.text(32825, "Add collection"),
                add_smart_collection=self.text(32785, "Add smart collection"),
                add_manual_collection=self.text(32826, "Add manual collection"),
                remove_collection=self.text(32827, "Remove collection row"),
                maximum_rows=self.text(32791, "A maximum of nine home-screen rows can be shown."),
                no_smart_collections=self.text(32792, "There are no additional saved smart collections to add."),
                no_manual_collections=self.text(32828, "There are no additional manual collections to add."),
            ),
            collection_names=collection_names,
        )
        if result is None:
            return

        self._write_home_layout_items(result, saved_names, collection_names)
        self._invalidate_home_widgets("home layout changed")
        self.kodi.notify(self.text(32214, "Home-screen layout saved"))

    def _dynamic_home_slot_snapshot(self) -> Tuple[Tuple[str, str, str], ...]:
        values = []
        for position in range(1, 10):
            row = self.kodi.addon.getSetting("home_row_%d" % position)
            if row == "smart":
                values.append(
                    (
                        row,
                        self.kodi.addon.getSetting("home_smart_id_%d" % position),
                        self.kodi.addon.getSetting("home_smart_name_%d" % position),
                    )
                )
            elif row == "collection":
                values.append(
                    (
                        row,
                        self.kodi.addon.getSetting("home_collection_id_%d" % position),
                        self.kodi.addon.getSetting("home_collection_name_%d" % position),
                    )
                )
        return tuple(values)

    def _sync_saved_search_home_rows(
        self, removed_saved_search_id: Optional[int] = None
    ) -> bool:
        saved_names = self._saved_search_name_map()
        collection_names = self._collection_name_map()
        items = self._load_home_layout_items(saved_names, collection_names)
        if removed_saved_search_id is not None:
            items = remove_saved_search_from_home_layout(
                items, removed_saved_search_id
            )
        before = self._dynamic_home_slot_snapshot()
        self._write_home_layout_items(items, saved_names, collection_names)
        changed = before != self._dynamic_home_slot_snapshot()
        if changed:
            self._invalidate_home_widgets("smart collection home rows changed")
        return changed

    def _sync_collection_home_rows(
        self, removed_collection_id: Optional[int] = None
    ) -> bool:
        saved_names = self._saved_search_name_map()
        collection_names = self._collection_name_map()
        items = self._load_home_layout_items(saved_names, collection_names)
        if removed_collection_id is not None:
            items = remove_collection_from_home_layout(
                items, removed_collection_id
            )
        before = self._dynamic_home_slot_snapshot()
        self._write_home_layout_items(items, saved_names, collection_names)
        changed = before != self._dynamic_home_slot_snapshot()
        if changed:
            self._invalidate_home_widgets("manual collection home rows changed")
        return changed

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

    def _metadata_target_fallback(self, target_field: Optional[str]) -> str:
        values = {
            None: self.text(32920, "Ignore this tag"),
            "taken_at": self.text(32921, "Capture date"),
            "camera_make": self.text(32922, "Camera make"),
            "camera_model": self.text(32923, "Camera model"),
            "rating": self.text(32924, "Rating"),
            "keywords": self.text(32925, "Keywords"),
            "caption": self.text(32926, "Caption"),
            "country": self.text(32927, "Country"),
            "state": self.text(32928, "State or region"),
            "city": self.text(32929, "City"),
            "sublocation": self.text(32930, "Sublocation"),
        }
        return values.get(target_field, str(target_field or ""))

    def metadata_mapping(self, params: Optional[Dict[str, str]] = None):
        overrides = self.catalog.list_metadata_mapping_overrides()
        items = [
            self.add_action(
                self.text(32904, "Add metadata mapping"),
                "action/add-metadata-mapping",
            )
        ]
        if overrides:
            items.append(
                self.add_action(
                    self.text(32905, "Reset all custom mappings"),
                    "action/reset-metadata-mappings",
                )
            )
        for rule in overrides:
            target = self._metadata_target_fallback(rule.target_field)
            label = "%s · %s → %s  [COLOR=grey](%d)[/COLOR]" % (
                rule.source_type.upper(),
                rule.source_tag,
                target,
                int(rule.priority),
            )
            context = [
                (
                    self.text(32906, "Remove custom mapping"),
                    "RunPlugin(%s)"
                    % self.url(
                        "action/remove-metadata-mapping",
                        source_type=rule.source_type,
                        source_tag=rule.source_tag,
                    ),
                )
            ]
            items.append(
                self.add_action(
                    label,
                    "action/edit-metadata-mapping",
                    context=context,
                    source_type=rule.source_type,
                    source_tag=rule.source_tag,
                )
            )
        self.finish(
            items,
            content="files",
            category=self.text(32903, "Metadata mapping"),
        )

    def _add_metadata_mapping(self) -> None:
        dialog = xbmcgui.Dialog()
        source_index = dialog.select(
            self.text(32908, "Metadata source"),
            [value.upper() for value in SOURCE_TYPES],
            preselect=0,
        )
        if source_index < 0:
            return
        source_type = SOURCE_TYPES[int(source_index)]
        source_tag = dialog.input(self.text(32909, "Source tag name"), defaultt="")
        if not str(source_tag or "").strip():
            return
        targets: List[Optional[str]] = [None] + list(TARGET_FIELDS)
        target_index = dialog.select(
            self.text(32907, "Map tag to"),
            [self._metadata_target_fallback(target) for target in targets],
            preselect=1,
        )
        if target_index < 0:
            return
        target_field = targets[int(target_index)]
        if target_field is None and not dialog.yesno(
            self.text(32910, "Ignore metadata tag?"),
            self.text(32911, "This tag will not contribute to canonical metadata."),
        ):
            return
        priority_text = dialog.input(
            self.text(32912, "Priority (lower wins)"), defaultt="100"
        )
        try:
            priority = int(priority_text)
            rule = MetadataMappingRule(source_type, source_tag, target_field, priority)
            self.catalog.set_metadata_mapping_rule(rule)
        except (TypeError, ValueError) as exc:
            self.kodi.notify(
                "%s: %s" % (self.text(32913, "Invalid metadata mapping"), exc),
                error=True,
            )
            return
        self.kodi.notify(self.text(32914, "Metadata mapping saved"))
        self.kodi.notify(self.text(32915, "Run a scan to reindex metadata"))
        xbmc.executebuiltin("Container.Refresh")

    def _edit_metadata_mapping(self, source_type: str, source_tag: str) -> None:
        existing = next(
            (
                rule
                for rule in self.catalog.list_metadata_mapping_overrides()
                if rule.source_type == str(source_type).casefold()
                and rule.source_tag.casefold() == str(source_tag).casefold()
            ),
            None,
        )
        if existing is None:
            self.kodi.notify(self.text(32916, "Metadata mapping was not found"), error=True)
            return
        dialog = xbmcgui.Dialog()
        targets: List[Optional[str]] = [None] + list(TARGET_FIELDS)
        labels = [self._metadata_target_fallback(target) for target in targets]
        try:
            preselect = targets.index(existing.target_field)
        except ValueError:
            preselect = 0
        selected = dialog.select(
            self.text(32907, "Map tag to"), labels, preselect=preselect
        )
        if selected < 0:
            return
        target_field = targets[int(selected)]
        priority_text = dialog.input(
            self.text(32912, "Priority (lower wins)"),
            defaultt=str(existing.priority),
        )
        try:
            priority = int(priority_text)
            self.catalog.set_metadata_mapping_rule(
                MetadataMappingRule(
                    existing.source_type,
                    existing.source_tag,
                    target_field,
                    priority,
                )
            )
        except (TypeError, ValueError) as exc:
            self.kodi.notify(
                "%s: %s" % (self.text(32913, "Invalid metadata mapping"), exc),
                error=True,
            )
            return
        self.kodi.notify(self.text(32914, "Metadata mapping saved"))
        self.kodi.notify(self.text(32915, "Run a scan to reindex metadata"))
        xbmc.executebuiltin("Container.Refresh")

    def _configure_source_scan_policy(self, source_id: int) -> None:
        source = self.catalog.get_source(source_id)
        if source is None:
            self.kodi.notify(self.text(32901, "Source was not found"), error=True)
            return

        settings = self.kodi.refresh_settings()
        global_policy = source_scan_policy_from_settings(settings)
        explicit = self.catalog.get_source_scan_policy(source_id)
        dialog = xbmcgui.Dialog()
        mode = dialog.select(
            "%s: %s" % (self.text(32885, "Source scan settings"), source.label),
            [
                self.text(32886, "Global scan defaults"),
                self.text(32887, "Custom scan settings"),
            ],
            preselect=1 if explicit is not None else 0,
        )
        if mode < 0:
            return
        if mode == 0:
            self.catalog.clear_source_scan_policy(source_id)
            self.kodi.notify(self.text(32897, "Source now uses global scan defaults"))
            xbmc.executebuiltin("Container.Refresh")
            return

        current = explicit or global_policy

        def choose_bool(heading: str, value: bool) -> Optional[bool]:
            selected = dialog.select(
                heading,
                [self.text(32224, "Off"), self.text(32223, "On")],
                preselect=1 if value else 0,
            )
            if selected < 0:
                return None
            return selected == 1

        recursive = choose_bool(
            self.text(32890, "Scan subfolders recursively"), current.recursive
        )
        if recursive is None:
            return
        include_videos = choose_bool(
            self.text(32900, "Include videos for this source"), current.include_videos
        )
        if include_videos is None:
            return
        picture_extensions = dialog.input(
            self.text(32891, "Picture file extensions"),
            defaultt=",".join(current.picture_extensions),
        )
        video_extensions = dialog.input(
            self.text(32892, "Video file extensions"),
            defaultt=",".join(current.video_extensions),
        )
        exclude_fragments = dialog.input(
            self.text(32893, "Excluded path fragments"),
            defaultt="|".join(current.exclude_fragments),
        )
        exclude_hidden = choose_bool(
            self.text(32894, "Exclude hidden files and folders"),
            current.exclude_hidden,
        )
        if exclude_hidden is None:
            return

        from .utils import split_csv, split_pipe

        pictures = split_csv(picture_extensions)
        videos = split_csv(video_extensions)
        if not pictures:
            self.kodi.notify(
                self.text(32898, "At least one picture extension is required"),
                error=True,
            )
            return
        if include_videos and not videos:
            self.kodi.notify(
                self.text(32902, "At least one video extension is required when videos are enabled"),
                error=True,
            )
            return
        policy = SourceScanPolicy(
            recursive=recursive,
            include_videos=include_videos,
            picture_extensions=pictures,
            video_extensions=videos,
            exclude_fragments=split_pipe(exclude_fragments),
            exclude_hidden=exclude_hidden,
        )
        summary = (
            "%s: %s\n%s: %s\n%s: %s\n%s: %s\n%s: %s\n%s: %s"
            % (
                self.text(32890, "Scan subfolders recursively"),
                self.text(32223, "On") if recursive else self.text(32224, "Off"),
                self.text(32900, "Include videos for this source"),
                self.text(32223, "On") if include_videos else self.text(32224, "Off"),
                self.text(32891, "Picture file extensions"),
                ",".join(pictures),
                self.text(32892, "Video file extensions"),
                ",".join(videos) or "-",
                self.text(32893, "Excluded path fragments"),
                "|".join(policy.exclude_fragments) or "-",
                self.text(32894, "Exclude hidden files and folders"),
                self.text(32223, "On") if exclude_hidden else self.text(32224, "Off"),
            )
        )
        if not dialog.yesno(self.text(32895, "Save source scan settings?"), summary):
            return
        self.catalog.set_source_scan_policy(source_id, policy)
        self.kodi.notify(
            "%s. %s"
            % (
                self.text(32896, "Source scan settings saved"),
                self.text(32899, "Run a scan to apply the changed source policy"),
            )
        )
        xbmc.executebuiltin("Container.Refresh")

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
        if scope == "collection":
            return self.catalog.pictures_in_collection(
                int(params["id"]), limit, 0
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

    def _release_direct_slideshow_action(self) -> None:
        """Finish a direct non-folder plug-in playback request before playback.

        Selecting an action row can still make Kodi open the plug-in URL as a
        media item. Marking that request unresolved before the action starts a
        real playlist prevents Kodi from waiting for ``addon.py`` as the active
        player item and eventually killing the otherwise completed invoker.
        ``RunPlugin`` calls normally use a negative handle and are left alone.
        """

        if int(self.handle) < 0:
            return
        resolver = getattr(xbmcplugin, "setResolvedUrl", None)
        if not callable(resolver):
            return
        try:
            resolver(self.handle, False, xbmcgui.ListItem())
            self.kodi.log.debug("Released direct slideshow action playback handle")
        except Exception as exc:
            self.kodi.log.warning(
                "Could not release direct slideshow action playback handle: %s",
                exc,
            )

    def _select_collection_slideshow_rows(
        self,
        rows: Sequence[Dict[str, Any]],
        start_id: int,
    ) -> Optional[List[Dict[str, Any]]]:
        """Split a mixed manual collection into a safe Kodi playlist type.

        Kodi 21 on Windows may route still images in a mixed picture playlist
        through VideoPlayer. A manual collection can span unrelated folders, so
        the native folder-slideshow fallback is unavailable. Prompting for one
        media type avoids the unstable compatibility probe while preserving the
        stored order within the selected type.
        """

        pictures = [
            row
            for row in rows
            if str(row.get("media_type") or "picture") != "video"
        ]
        videos = [
            row for row in rows if str(row.get("media_type") or "") == "video"
        ]
        if not pictures or not videos:
            return list(rows)

        start_is_video = any(
            int(row.get("id") or 0) == int(start_id)
            and str(row.get("media_type") or "") == "video"
            for row in rows
        )
        selected = xbmcgui.Dialog().select(
            self.text(32819, "Choose collection playback"),
            [
                self.text(32820, "Play picture slideshow"),
                self.text(32821, "Play video playlist"),
            ],
            preselect=1 if start_is_video else 0,
        )
        if selected == 0:
            self.kodi.log.info(
                "Mixed collection playback split to picture slideshow: "
                "pictures=%d videos=%d",
                len(pictures),
                len(videos),
            )
            return pictures
        if selected == 1:
            self.kodi.log.info(
                "Mixed collection playback split to video playlist: "
                "pictures=%d videos=%d",
                len(pictures),
                len(videos),
            )
            return videos
        self.kodi.log.debug("Mixed collection playback cancelled")
        return None

    def _start_music_slideshow(self, params: Dict[str, str]) -> None:
        self._release_direct_slideshow_action()
        acquire = getattr(self.kodi, "acquire_slideshow_start", None)
        release = getattr(self.kodi, "release_slideshow_start", None)
        token = acquire() if callable(acquire) else ""
        if callable(acquire) and not token:
            self.kodi.notify(
                self.text(32725, "A slideshow is already being prepared")
            )
            return
        try:
            self._start_music_slideshow_unlocked(params)
        finally:
            if token and callable(release):
                release(token)

    def _start_music_slideshow_unlocked(
        self, params: Dict[str, str]
    ) -> None:
        scope = str(params.get("scope") or "")
        try:
            collection_id = int(params.get("id") or 0)
        except (TypeError, ValueError):
            collection_id = 0
        target_type = (
            MUSIC_TARGET_SMART
            if scope == "saved-search"
            else MUSIC_TARGET_MANUAL
            if scope == "collection"
            else ""
        )
        if not target_type or collection_id <= 0:
            self.kodi.notify(
                self.text(32838, "Music slideshow could not be started"),
                error=True,
            )
            return
        playlist_uri = self.catalog.get_music_playlist(
            target_type, collection_id
        )
        if not playlist_uri:
            self.kodi.notify(
                self.text(32839, "No music playlist is assigned"),
                error=True,
            )
            return
        try:
            rows = self._slideshow_rows(
                {"scope": scope, "id": str(collection_id)}
            )
        except SavedSearchValidationError as exc:
            self.kodi.notify(
                "%s: %s"
                % (self.text(32710, "Invalid saved search"), exc),
                error=True,
            )
            return
        picture_rows = [
            row
            for row in rows
            if str(row.get("media_type") or "picture") != "video"
            and str(row.get("uri") or "").strip()
        ]
        if not picture_rows:
            self.kodi.notify(
                self.text(32840, "No pictures to play with music")
            )
            return
        directory_uri = self.url(
            "slideshow/saved-search-pictures"
            if scope == "saved-search"
            else "slideshow/collection-pictures",
            id=collection_id,
            **self._rating_route_params(params),
        )
        begin_slide_uri = str(picture_rows[0].get("uri") or "")
        session_token = uuid.uuid4().hex
        fingerprint = ""
        try:
            stop_active_media_players(xbmc, logger=self.kodi.log)
            count = start_music_playlist(
                xbmc, playlist_uri, logger=self.kodi.log
            )
            fingerprint = self.kodi.music_playlist_fingerprint()
            if not fingerprint:
                stop_music_player(self.kodi, logger=self.kodi.log)
                raise MusicSlideshowError(
                    "Kodi could not verify the loaded music playlist"
                )
            self.kodi.set_music_slideshow_session(
                session_token, fingerprint
            )
            published = self.kodi.music_slideshow_session()
            if (
                str(published.get("token") or "") != session_token
                or str(published.get("playlist_fingerprint") or "")
                != fingerprint
            ):
                stop_music_player(self.kodi, logger=self.kodi.log)
                raise MusicSlideshowError(
                    "Kodi could not publish music slideshow ownership"
                )
            start_native_directory_slideshow(
                xbmc,
                directory_uri,
                recursive=False,
                begin_slide_uri=begin_slide_uri,
                logger=self.kodi.log,
            )
            self.kodi.log.info(
                "Music slideshow started: scope=%s id=%d pictures=%d music_items=%d",
                scope,
                collection_id,
                len(picture_rows),
                count,
            )
        except (MusicPlaylistValidationError, MusicSlideshowError, SlideshowError) as exc:
            if fingerprint:
                try:
                    if self.kodi.music_playlist_fingerprint() == fingerprint:
                        stop_music_player(self.kodi, logger=self.kodi.log)
                except Exception:
                    pass
            self.kodi.clear_music_slideshow_session(session_token)
            self.kodi.notify(
                "%s: %s"
                % (
                    self.text(32838, "Music slideshow could not be started"),
                    exc,
                ),
                error=True,
            )

    def _start_slideshow(self, params: Dict[str, str]) -> None:
        self._release_direct_slideshow_action()
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
        if scope == "collection":
            selected_rows = self._select_collection_slideshow_rows(rows, start_id)
            if selected_rows is None:
                return
            rows = selected_rows
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

        if scope == "collection" and picture_count and not video_count:
            collection_uri = self.url(
                "slideshow/collection-pictures",
                id=params.get("id", ""),
                **self._rating_route_params(params),
            )
            begin_slide_uri = uris[start_position] if uris else ""
            self.kodi.log.info(
                "Slideshow route=native-collection-picture collection_id=%s "
                "rows=%d pictures=%d videos=0 unique=%d empty=%d "
                "duplicates=%d start=%d",
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
                start_native_directory_slideshow(
                    xbmc,
                    collection_uri,
                    recursive=False,
                    begin_slide_uri=begin_slide_uri,
                    logger=self.kodi.log,
                )
            except SlideshowError as exc:
                self.kodi.notify(
                    "%s: %s" % (self.text(32605, "Could not start slideshow"), exc),
                    error=True,
                )
            return

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

    def diagnostics(self):
        snapshot = collect_diagnostics(self.runtime)
        not_installed = self.text(32857, "Not installed")
        on = self.text(32223, "On")
        off = self.text(32224, "Off")

        skin = snapshot["skin"]
        skin_text = str(skin.get("id") or not_installed)
        if skin.get("version"):
            skin_text = "%s %s" % (skin_text, skin["version"])

        values = [
            "%s: %s"
            % (self.text(32844, "MyPicsDB 3 version"), snapshot["plugin_version"]),
            "%s: %s"
            % (
                self.text(32845, "Screensaver version"),
                snapshot["screensaver_version"] or not_installed,
            ),
            "%s: %s"
            % (
                self.text(32846, "Repository version"),
                snapshot["repository_version"] or not_installed,
            ),
            "%s: %s" % (self.text(32847, "Current skin"), skin_text),
            "%s: %s"
            % (self.text(30041, "Database backend"), snapshot["backend"]),
            "%s: %s"
            % (self.text(32848, "Database schema"), snapshot["schema_version"]),
            "%s: %s"
            % (
                self.text(32849, "Query Model version"),
                snapshot["query_model_version"],
            ),
            "%s: %s"
            % (self.text(30038, "Indexed media"), snapshot["indexed_media"]),
            "%s: %s"
            % (self.text(32601, "Indexed videos"), snapshot["indexed_videos"]),
            "%s: %s"
            % (self.text(30039, "Missing media"), snapshot["missing_media"]),
            "%s: %s"
            % (self.text(30040, "Indexed albums"), snapshot["indexed_albums"]),
            "%s: %s" % (self.text(32850, "Sources"), snapshot["sources"]),
            "%s: %s"
            % (self.text(32851, "Enabled sources"), snapshot["enabled_sources"]),
        ]

        last_scan = snapshot["last_scan"]
        if last_scan.get("finished_at"):
            values.append(
                "%s: %s"
                % (self.text(30036, "Last scan"), last_scan["finished_at"])
            )
            if last_scan.get("status"):
                values.append("Status: %s" % last_scan["status"])
            if last_scan.get("duration_seconds") is not None:
                values.append(
                    "%s: %s"
                    % (
                        self.text(32797, "Scan duration"),
                        format_duration(last_scan["duration_seconds"]),
                    )
                )
        else:
            values.append(
                "%s: %s"
                % (self.text(30036, "Last scan"), self.text(30037, "Never"))
            )

        active = snapshot["active_scan"]
        if active:
            kind = (
                self.text(32731, "Automatic scan")
                if active["kind"] == "automatic"
                else self.text(32732, "Manual scan")
            )
            state = (
                self.text(32735, "Stopping scan")
                if active["state"] == "cancelling"
                else self.text(32733, "Scan in progress")
            )
            values.append(
                "%s: %s - %s"
                % (self.text(32852, "Active scan"), kind, state)
            )
            values.append(
                "%s: %s"
                % (self.text(30047, "Pictures found"), active["pictures_seen"])
            )
            if active.get("elapsed_seconds") is not None:
                values.append(
                    "%s: %s"
                    % (
                        self.text(32798, "Elapsed time"),
                        format_duration(active["elapsed_seconds"]),
                    )
                )
        else:
            values.append(
                "%s: %s"
                % (
                    self.text(32852, "Active scan"),
                    self.text(32730, "No scan is running"),
                )
            )

        playlist_compatibility = {
            "compatible": self.text(32866, "Compatible"),
            "incompatible": self.text(32867, "Incompatible"),
            "unknown": self.text(32868, "Unknown"),
        }.get(
            str(snapshot.get("picture_playlist_compatibility") or "unknown"),
            self.text(32868, "Unknown"),
        )
        music_session = snapshot.get("music_slideshow_session") or {}

        values.extend(
            [
                "%s: %s"
                % (
                    self.text(32863, "Home widget generation"),
                    snapshot["home_generations"]["content"],
                ),
                "%s: %s"
                % (
                    self.text(32864, "Random Home generation"),
                    snapshot["home_generations"]["random"],
                ),
                "%s: %s"
                % (
                    self.text(32865, "Picture playlist compatibility"),
                    playlist_compatibility,
                ),
                "%s: %s"
                % (
                    self.text(32869, "Music slideshow session"),
                    self.text(32870, "Active")
                    if music_session.get("active")
                    else self.text(32871, "Inactive"),
                ),
                "%s: %s"
                % (
                    self.text(32872, "Music playlist ownership marker"),
                    self.text(32873, "Present")
                    if music_session.get("playlist_fingerprint_present")
                    else self.text(32874, "Missing"),
                ),
                "%s: %s"
                % (
                    self.text(32853, "Home-screen row count"),
                    snapshot["home_widget_limit"],
                ),
                "%s: %s h"
                % (
                    self.text(32854, "Random refresh interval"),
                    snapshot["random_home_refresh_hours"],
                ),
                "%s: %s"
                % (
                    self.text(32855, "Include videos"),
                    on if snapshot["include_videos"] else off,
                ),
                "%s: %s"
                % (
                    self.text(32856, "Debug logging"),
                    on if snapshot["debug_logging"] else off,
                ),
                "%s: %s"
                % (
                    self.text(32861, "Support bundle folder"),
                    self.text(
                        32862,
                        "Kodi userdata > addon_data > "
                        "plugin.image.mypicsdb3 > support-bundles",
                    ),
                ),
            ]
        )

        items = [self.add_info(value) for value in values]
        items.append(
            self.add_action(
                self.text(32720, "Write diagnostic log entry"),
                "action/log-diagnostic",
            )
        )
        items.append(
            self.add_action(
                self.text(32858, "Export support bundle"),
                "action/export-support-bundle",
            )
        )
        self.finish(
            items,
            content="files",
            cache=False,
            category=self.text(32843, "Diagnostics"),
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
        if latest:
            latest_duration = duration_seconds(
                latest.get("started_at"), latest.get("finished_at")
            )
            if latest_duration is not None:
                values.append(
                    "%s: %s"
                    % (
                        self.text(32797, "Scan duration"),
                        format_duration(latest_duration),
                    )
                )
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
            try:
                elapsed = max(0, time.time() - float(active.get("started_at")))
            except (TypeError, ValueError):
                elapsed = None
            if elapsed is not None:
                values.append(
                    "%s: %s"
                    % (self.text(32798, "Elapsed time"), format_duration(elapsed))
                )
                values.append(
                    "%s: %s"
                    % (
                        self.text(32977, "Current scan rate"),
                        format_rate(active.get("pictures_seen"), elapsed),
                    )
                )
            values.extend(
                [
                    "%s: %s"
                    % (
                        self.text(32978, "Metadata reads"),
                        int(active.get("metadata_reads") or 0),
                    ),
                    "%s: %s"
                    % (
                        self.text(30049, "Pictures unchanged"),
                        int(active.get("pictures_unchanged") or 0),
                    ),
                    "%s: %s"
                    % (
                        self.text(30048, "Pictures updated"),
                        int(active.get("pictures_added") or 0)
                        + int(active.get("pictures_updated") or 0),
                    ),
                    "%s: %s"
                    % (self.text(30050, "Errors"), int(active.get("errors") or 0)),
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
        items = [self.add_info(value) for value in values]
        if active:
            items.append(self.add_action(self.text(32726, "Stop scan"), "action/stop-scan"))
        items.append(self.add_action(self.text(30060, "Test database connection"), "action/test-db"))
        items.append(self.add_action(self.text(30061, "Clean missing records"), "action/cleanup"))
        self.finish(items, content="files", category=self.text(30014, "Scan status"))

    def action(self, route: str, params: Dict[str, str]):
        if route == "action/export-support-bundle":
            try:
                bundle_path = write_support_bundle(self.runtime)
            except Exception as exc:
                self.kodi.log.warning("Could not export support bundle: %s", exc)
                self.kodi.notify(
                    "%s: %s"
                    % (self.text(32860, "Could not export support bundle"), exc),
                    error=True,
                )
                return
            self.kodi.log.info(
                "Privacy-safe support bundle exported: %s",
                os.path.basename(bundle_path),
            )
            self.kodi.notify(
                "%s\n%s: %s"
                % (
                    self.text(32859, "Support bundle saved: %s")
                    % os.path.basename(bundle_path),
                    self.text(32861, "Support bundle folder"),
                    self.text(
                        32862,
                        "Kodi userdata > addon_data > "
                        "plugin.image.mypicsdb3 > support-bundles",
                    ),
                ),
                milliseconds=8000,
            )
            return
        if route == "action/location-details":
            try:
                picture_id = int(params.get("id") or 0)
            except (TypeError, ValueError):
                picture_id = 0
            if picture_id <= 0:
                self.kodi.notify(self.text(32987, "Picture was not found"), error=True)
                return
            self._show_location_details(picture_id)
            return
        if route in {"action/refresh-metadata-picture", "action/metadata-diagnostics"}:
            try:
                picture_id = int(params.get("id") or 0)
            except (TypeError, ValueError):
                picture_id = 0
            if picture_id <= 0:
                self.kodi.notify(self.text(32987, "Picture was not found"), error=True)
                return
            if route == "action/metadata-diagnostics":
                self._show_metadata_diagnostics(picture_id)
            else:
                self._refresh_picture_metadata(picture_id)
            return
        if route == "action/refresh-metadata-folder":
            try:
                folder_id = int(params.get("id") or 0)
            except (TypeError, ValueError):
                folder_id = 0
            if folder_id <= 0:
                self.kodi.notify(self.text(32997, "Folder was not found"), error=True)
                return
            self._refresh_folder_metadata(folder_id)
            return
        if route == "action/settings":
            previous_limit = int(getattr(self.kodi.settings, "home_widget_limit", 10))
            self.kodi.open_settings()
            current = self.kodi.refresh_settings()
            if int(getattr(current, "home_widget_limit", 10)) != previous_limit:
                self._invalidate_home_widgets("home widget limit changed")
            return
        if route == "action/start-slideshow":
            self._start_slideshow(params)
            return
        if route == "action/start-music-slideshow":
            self._start_music_slideshow(params)
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
        if route == "action/assign-music-playlist":
            try:
                target_type = normalize_music_target_type(params.get("type"))
                target_id = int(params.get("id") or 0)
                current = self.catalog.get_music_playlist(
                    target_type, target_id
                )
                selected = xbmcgui.Dialog().browseSingle(
                    1,
                    self.text(32835, "Choose music playlist"),
                    "music",
                    MUSIC_PLAYLIST_MASK,
                    False,
                    False,
                    current or KODI_MUSIC_PLAYLIST_DIRECTORY,
                )
                selected = str(selected or "").strip()
                if not selected or selected == current:
                    return
                if not self.catalog.set_music_playlist(
                    target_type, target_id, selected
                ):
                    raise MusicPlaylistValidationError(
                        "Collection was not found"
                    )
                self.kodi.notify(
                    self.text(32836, "Music playlist assigned")
                )
                xbmc.executebuiltin("Container.Refresh")
            except (MusicPlaylistValidationError, RuntimeError, TypeError, ValueError) as exc:
                self.kodi.notify(
                    "%s: %s"
                    % (
                        self.text(32841, "Could not save music playlist"),
                        exc,
                    ),
                    error=True,
                )
            return
        if route == "action/remove-music-playlist":
            try:
                target_type = normalize_music_target_type(params.get("type"))
                target_id = int(params.get("id") or 0)
                self.catalog.clear_music_playlist(target_type, target_id)
                self.kodi.notify(
                    self.text(32837, "Music playlist removed")
                )
                xbmc.executebuiltin("Container.Refresh")
            except (MusicPlaylistValidationError, RuntimeError, TypeError, ValueError) as exc:
                self.kodi.notify(
                    "%s: %s"
                    % (
                        self.text(32841, "Could not save music playlist"),
                        exc,
                    ),
                    error=True,
                )
            return
        if route == "action/export-results":
            progress = None
            try:
                picture_ids, suggested_name = self._export_selection_from_params(params)
                if not picture_ids:
                    self.kodi.notify(self.text(32976, "No matching media to export"))
                    return
                dialog = xbmcgui.Dialog()
                default_name = normalize_export_name(suggested_name)
                export_name = dialog.input(
                    self.text(32968, "Export folder name"),
                    defaultt=default_name[:120],
                )
                if not str(export_name or "").strip():
                    return
                destination = dialog.browseSingle(
                    3,
                    self.text(32969, "Choose export destination"),
                    "",
                    "",
                    False,
                    False,
                    "",
                )
                destination = str(destination or "").strip()
                if not destination:
                    return
                if not dialog.yesno(
                    self.text(32970, "Export media?"),
                    self.text(
                        32971,
                        "Copy %d matching items to a new export folder? "
                        "Original files will not be modified.",
                    )
                    % len(picture_ids),
                ):
                    return

                progress_type = getattr(xbmcgui, "DialogProgress", None)
                if callable(progress_type):
                    progress = progress_type()
                    progress.create(
                        self.text(32972, "Exporting media"),
                        "%d %s" % (len(picture_ids), self.text(32965, "items")),
                    )

                def cancelled() -> bool:
                    if progress is None:
                        return False
                    checker = getattr(progress, "iscanceled", None)
                    return bool(callable(checker) and checker())

                def update_progress(done: int, total: int, filename: str) -> None:
                    if progress is None:
                        return
                    percent = min(100, int((done * 100) / max(1, total)))
                    message = "%d / %d - %s" % (done, total, filename)
                    progress.update(percent, message)

                from . import VERSION

                result = SafeExporter(
                    self.catalog,
                    self.runtime.filesystem,
                    VERSION,
                    logger=self.kodi.log,
                ).export_ids(
                    picture_ids,
                    destination,
                    str(export_name),
                    suggested_name,
                    cancelled=cancelled,
                    progress=update_progress,
                )
                if result.cancelled:
                    message = self.text(
                        32974,
                        "Export cancelled: %d copied, %d missing, %d failed",
                    ) % (result.copied, result.missing, result.failed)
                else:
                    message = self.text(
                        32973,
                        "Export complete: %d copied, %d missing, %d failed",
                    ) % (result.copied, result.missing, result.failed)
                self.kodi.notify(
                    message,
                    error=bool(result.failed),
                    milliseconds=7000,
                    force=True,
                )
                self.kodi.log.info(
                    "Media export status=%s selected=%d copied=%d missing=%d "
                    "failed=%d collisions=%d",
                    "cancelled" if result.cancelled else "completed",
                    result.selected,
                    result.copied,
                    result.missing,
                    result.failed,
                    result.collisions,
                )
            except (
                CollectionValidationError,
                ExportError,
                SavedSearchValidationError,
                OSError,
                RuntimeError,
                TypeError,
                ValueError,
            ) as exc:
                self.kodi.notify(
                    "%s: %s" % (self.text(32975, "Could not export media"), exc),
                    error=True,
                    milliseconds=7000,
                    force=True,
                )
            finally:
                if progress is not None:
                    try:
                        progress.close()
                    except Exception:
                        pass
            return
        if route == "action/snapshot-results":
            progress = None
            try:
                query, suggested_name = self._snapshot_query_from_params(params)
                total = int(self.catalog.count_query_pictures(query))
                if total <= 0:
                    self.kodi.notify(self.text(32963, "No matching media to save"))
                    return
                dialog = xbmcgui.Dialog()
                name = dialog.input(
                    self.text(32958, "Collection snapshot name"),
                    defaultt=suggested_name[:191],
                )
                if not str(name or "").strip():
                    return
                if not dialog.yesno(
                    self.text(32959, "Create collection snapshot?"),
                    self.text(
                        32960,
                        "Create a static manual collection with %d currently "
                        "matching items? It will not update automatically.",
                    )
                    % total,
                ):
                    return
                progress_type = getattr(xbmcgui, "DialogProgressBG", None)
                if callable(progress_type):
                    try:
                        progress = progress_type()
                        progress.create(
                            self.text(32964, "Creating collection snapshot"),
                            "%d %s" % (total, self.text(32965, "items")),
                        )
                    except Exception:
                        progress = None
                collection_id, item_count = self.catalog.create_collection_snapshot(
                    name, query
                )
                self.kodi.notify(
                    self.text(32961, "Collection snapshot created (%d items)")
                    % item_count
                )
                xbmc.executebuiltin(
                    "Container.Update(%s)"
                    % self.url("collection", id=collection_id)
                )
            except (
                CollectionValidationError,
                SavedSearchValidationError,
                TypeError,
                ValueError,
            ) as exc:
                self.kodi.notify(
                    "%s: %s"
                    % (self.text(32962, "Could not create collection snapshot"), exc),
                    error=True,
                )
            finally:
                if progress is not None:
                    try:
                        progress.close()
                    except Exception:
                        pass
            return
        if route == "action/create-smart-collection":
            try:
                editor = SmartFilterEditor(
                    self.catalog,
                    xbmcgui.Dialog(),
                    self.text,
                )
                result = editor.run()
                if result is None:
                    return
                saved_id = self.catalog.create_saved_search(result.name, result.query)
                self.kodi.notify(self.text(32769, "Smart collection saved"))
                xbmc.executebuiltin(
                    "Container.Update(%s)" % self.url("saved-search", id=saved_id)
                )
            except (ValueError, SavedSearchValidationError) as exc:
                self.kodi.notify(
                    "%s: %s"
                    % (self.text(32770, "Could not save smart collection"), exc),
                    error=True,
                )
            return
        if route == "action/create-collection":
            name = xbmcgui.Dialog().input(
                self.text(32805, "Collection name")
            )
            if not name:
                return
            try:
                collection_id = self.catalog.create_collection(name)
                self.kodi.notify(self.text(32806, "Collection created"))
                xbmc.executebuiltin(
                    "Container.Update(%s)"
                    % self.url("collection", id=collection_id)
                )
            except CollectionValidationError as exc:
                self.kodi.notify(
                    "%s: %s"
                    % (self.text(32810, "Could not save collection"), exc),
                    error=True,
                )
            return
        if route == "action/rename-collection":
            try:
                collection = self.catalog.get_collection(int(params["id"]))
                if collection is None:
                    self.kodi.notify(
                        self.text(32809, "Collection was not found"), error=True
                    )
                    return
                name = xbmcgui.Dialog().input(
                    self.text(32803, "Rename collection"),
                    defaultt=collection.name,
                )
                if not name or name.strip() == collection.name:
                    return
                self.catalog.rename_collection(collection.id, name)
                home_changed = self._sync_collection_home_rows()
                self.kodi.notify(self.text(32807, "Collection renamed"))
                xbmc.executebuiltin(
                    "ReloadSkin()" if home_changed else "Container.Refresh"
                )
            except CollectionValidationError as exc:
                self.kodi.notify(
                    "%s: %s"
                    % (self.text(32810, "Could not save collection"), exc),
                    error=True,
                )
            return
        if route == "action/delete-collection":
            try:
                collection = self.catalog.get_collection(int(params["id"]))
                if collection is None:
                    self.kodi.notify(
                        self.text(32809, "Collection was not found"), error=True
                    )
                    return
                confirmed = xbmcgui.Dialog().yesno(
                    self.text(32804, "Delete collection"),
                    self.text(
                        32811,
                        "Delete '%s'? Pictures and videos are not deleted.",
                    )
                    % collection.name,
                )
                if not confirmed:
                    return
                collection_id = collection.id
                self.catalog.delete_collection(collection_id)
                home_changed = self._sync_collection_home_rows(collection_id)
                self.kodi.notify(self.text(32808, "Collection deleted"))
                xbmc.executebuiltin(
                    "ReloadSkin()" if home_changed else "Container.Refresh"
                )
            except CollectionValidationError as exc:
                self.kodi.notify(
                    "%s: %s"
                    % (self.text(32809, "Collection was not found"), exc),
                    error=True,
                )
            return
        if route == "action/add-to-collection":
            picture_id = int(params["id"])
            collections = self.catalog.list_collections()
            dialog = xbmcgui.Dialog()
            selection = dialog.select(
                self.text(32812, "Add to collection"),
                [self.text(32814, "Create new collection...")]
                + [str(row["name"]) for row in collections],
            )
            if selection < 0:
                return
            try:
                if selection == 0:
                    name = dialog.input(self.text(32805, "Collection name"))
                    if not name:
                        return
                    collection_id = self.catalog.create_collection(name)
                    collection = self.catalog.get_collection(collection_id)
                else:
                    row = collections[selection - 1]
                    collection_id = int(row["id"])
                    collection = self.catalog.get_collection(collection_id)
                if collection is None:
                    self.kodi.notify(
                        self.text(32809, "Collection was not found"), error=True
                    )
                    return
                added = self.catalog.add_picture_to_collection(
                    collection_id, picture_id
                )
                self.kodi.notify(
                    (
                        self.text(32815, "Added to '%s'")
                        if added
                        else self.text(32816, "Already in '%s'")
                    )
                    % collection.name
                )
                if added:
                    self._invalidate_home_widgets(
                        "manual collection content changed"
                    )
            except (CollectionValidationError, IndexError) as exc:
                self.kodi.notify(
                    "%s: %s"
                    % (self.text(32810, "Could not save collection"), exc),
                    error=True,
                )
            return
        if route == "action/remove-from-collection":
            try:
                collection_id = int(params["collection"])
                picture_id = int(params["id"])
                collection = self.catalog.get_collection(collection_id)
                if collection is None:
                    self.kodi.notify(
                        self.text(32809, "Collection was not found"), error=True
                    )
                    return
                removed = self.catalog.remove_picture_from_collection(
                    collection_id, picture_id
                )
                if removed:
                    self.kodi.notify(
                        self.text(32817, "Removed from '%s'") % collection.name
                    )
                    self._invalidate_home_widgets(
                        "manual collection content changed"
                    )
                    xbmc.executebuiltin("Container.Refresh")
            except CollectionValidationError as exc:
                self.kodi.notify(
                    "%s: %s"
                    % (self.text(32809, "Collection was not found"), exc),
                    error=True,
                )
            return
        if route == "action/move-collection-item":
            try:
                collection_id = int(params["collection"])
                picture_id = int(params["id"])
                direction = str(params.get("direction") or "")
                moved = self.catalog.move_picture_in_collection(
                    collection_id, picture_id, direction
                )
                if moved:
                    self._invalidate_home_widgets(
                        "manual collection order changed"
                    )
                    xbmc.executebuiltin("Container.Refresh")
            except (CollectionValidationError, ValueError) as exc:
                self.kodi.notify(
                    "%s: %s"
                    % (self.text(32829, "Could not reorder collection"), exc),
                    error=True,
                )
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
                home_changed = self._sync_saved_search_home_rows()
                self.kodi.notify(self.text(32707, "Saved search renamed"))
                xbmc.executebuiltin(
                    "ReloadSkin()" if home_changed else "Container.Refresh"
                )
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
                saved_id = int(saved["id"])
                self.catalog.delete_saved_search(saved_id)
                home_changed = self._sync_saved_search_home_rows(saved_id)
                self.kodi.notify(self.text(32708, "Saved search deleted"))
                xbmc.executebuiltin(
                    "ReloadSkin()" if home_changed else "Container.Refresh"
                )
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
        if route == "action/source-scan-settings":
            self._configure_source_scan_policy(int(params["id"]))
            return
        if route == "action/add-metadata-mapping":
            self._add_metadata_mapping()
            return
        if route == "action/edit-metadata-mapping":
            self._edit_metadata_mapping(
                params.get("source_type", ""), params.get("source_tag", "")
            )
            return
        if route == "action/remove-metadata-mapping":
            removed = self.catalog.clear_metadata_mapping_rule(
                params.get("source_type", ""), params.get("source_tag", "")
            )
            if removed:
                self.kodi.notify(self.text(32917, "Custom metadata mapping removed"))
                self.kodi.notify(self.text(32915, "Run a scan to reindex metadata"))
            xbmc.executebuiltin("Container.Refresh")
            return
        if route == "action/reset-metadata-mappings":
            if xbmcgui.Dialog().yesno(
                self.text(32905, "Reset all custom mappings"),
                self.text(32918, "Restore the built-in metadata mapping defaults?"),
            ):
                self.catalog.clear_metadata_mapping_rules()
                self.kodi.notify(self.text(32919, "Built-in metadata mappings restored"))
                self.kodi.notify(self.text(32915, "Run a scan to reindex metadata"))
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
        if route == "action/refresh-random":
            self._invalidate_random_home_widgets("manual random refresh")
            refresher = getattr(self.kodi, "refresh_random_views", None)
            if callable(refresher):
                refresher()
            else:
                xbmc.executebuiltin("Container.Refresh")
            self.kodi.notify(self.text(32739, "Random selections refreshed"))
            return
        if route == "action/stop-scan":
            active = self._scan_status()
            if not active:
                self.kodi.notify(self.text(32730, "No scan is running"))
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
            if not self._playback_active():
                self.kodi.notify(
                    self.text(32729, "Stopping scan")
                    if requested
                    else self.text(32730, "No scan is running")
                )
            return
        if route == "action/scan":
            self._manual_scan(params.get("source"))
            return

    def _playback_active(self) -> bool:
        checker = getattr(self.kodi, "is_playing", None)
        if not callable(checker):
            return False
        try:
            return bool(checker())
        except Exception as exc:
            self.kodi.log.warning("Could not read playback state: %s", exc)
            return False

    def _manual_scan(self, source_id: Optional[str]):
        source_ids = [int(source_id)] if source_id else None
        self._background_scan(source_ids)

    def _background_scan(self, source_ids: Optional[List[int]] = None):
        heading = self.text(30056, "MyPicsDB 3")
        scanning_message = self.text(30026, "Scanning started")
        monitor = self.kodi.abort_monitor()
        scan_token = uuid.uuid4().hex
        scan_started = False
        last_progress_at = 0.0
        dialog = None
        try:
            settings = self.kodi.refresh_settings()
        except Exception as exc:
            self.kodi.log.error("Could not load scan settings: %s", exc)
            if not self._playback_active():
                self.kodi.notify(
                    "%s: %s" % (self.text(30028, "Scanning failed"), exc),
                    error=True,
                    milliseconds=7000,
                )
            return
        playback_paused = False

        def abort_requested() -> bool:
            return bool(monitor and monitor.abortRequested())

        if abort_requested():
            return

        def close_progress_dialog() -> None:
            nonlocal dialog
            if dialog is None:
                return
            try:
                dialog.close()
            except Exception as exc:
                if not abort_requested():
                    self.kodi.log.warning(
                        "Could not close manual scan progress dialog: %s", exc
                    )
            dialog = None

        def ensure_progress_dialog(message: str = scanning_message):
            nonlocal dialog
            if abort_requested() or self._playback_active():
                close_progress_dialog()
                return None
            if dialog is not None:
                return dialog
            creator = getattr(self.kodi, "create_background_progress", None)
            try:
                if callable(creator):
                    dialog = creator(heading, message)
                else:
                    dialog = xbmcgui.DialogProgressBG()
                    dialog.create(heading, message)
            except Exception as exc:
                dialog = None
                if not abort_requested():
                    self.kodi.log.warning(
                        "Could not create manual scan progress dialog: %s", exc
                    )
            return dialog

        def update_dialog(message: str) -> None:
            current = ensure_progress_dialog(message)
            if current is None:
                return
            try:
                current.update(0, heading, message)
            except Exception as exc:
                if not abort_requested():
                    self.kodi.log.warning(
                        "Manual scan progress update failed: %s", exc
                    )
                close_progress_dialog()

        def soft_cancelled() -> bool:
            stop_requested = getattr(self.kodi, "scan_cancel_requested", None)
            return bool(callable(stop_requested) and stop_requested(scan_token))

        def begin_status(_stats) -> None:
            nonlocal scan_started
            scan_started = True
            publisher = getattr(self.kodi, "begin_scan_status", None)
            if callable(publisher):
                publisher(scan_token, "manual")
            ensure_progress_dialog()

        def cancelled() -> bool:
            nonlocal playback_paused
            if abort_requested() or soft_cancelled():
                close_progress_dialog()
                return True

            while (
                settings.pause_during_playback
                and self._playback_active()
                and not abort_requested()
                and not soft_cancelled()
            ):
                close_progress_dialog()
                if not playback_paused:
                    playback_paused = True
                    self.kodi.log.info("Manual scan paused during playback")
                if monitor and monitor.waitForAbort(1):
                    return True

            if abort_requested() or soft_cancelled():
                close_progress_dialog()
                return True

            if playback_paused:
                playback_paused = False
                self.kodi.log.info("Manual scan resumed after playback")

            if self._playback_active():
                close_progress_dialog()
            elif scan_started:
                ensure_progress_dialog()
            return False

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
                publisher(
                    scan_token,
                    source.label,
                    path,
                    stats.pictures_seen,
                    getattr(stats, "pictures_unchanged", 0),
                    getattr(stats, "metadata_reads", 0),
                    getattr(stats, "pictures_added", 0),
                    getattr(stats, "pictures_updated", 0),
                    getattr(stats, "errors", 0),
                )
            update_dialog(message)

        try:
            scanner = Scanner(
                self.catalog,
                self.runtime.filesystem,
                settings,
                self.kodi.log,
                cancelled=cancelled,
                progress=progress,
                started=begin_status,
            )
            stats = scanner.scan_sources(source_ids)
            if (
                int(getattr(stats, "pictures_added", 0) or 0)
                + int(getattr(stats, "pictures_updated", 0) or 0)
                + int(getattr(stats, "missing_marked", 0) or 0)
                > 0
            ):
                self._invalidate_home_widgets("manual scan changed pictures")
            if abort_requested():
                self.kodi.log.info(
                    "Manual scan interrupted because Kodi or the add-on service stopped"
                )
                return
            if stats.cancelled:
                self.kodi.log.info("Manual scan cancelled by user")
                if not self._playback_active():
                    self.kodi.notify(self.text(30042, "Scan cancelled"))
            else:
                message = "%s: %d, %s: %d" % (
                    self.text(30047, "Pictures found"),
                    stats.pictures_seen,
                    self.text(30050, "Errors"),
                    getattr(stats, "errors", 0),
                )
                if not self._playback_active():
                    self.kodi.notify(
                        message,
                        error=stats.errors > 0,
                        milliseconds=6000,
                    )
        except RuntimeError as exc:
            self.kodi.log.warning("Manual scan could not run: %s", exc)
            if not abort_requested() and not self._playback_active():
                self.kodi.notify(str(exc), error=True)
        except Exception as exc:
            self.kodi.log.error("Manual scan failed: %s", exc)
            if not abort_requested() and not self._playback_active():
                self.kodi.notify(
                    "%s: %s" % (self.text(30028, "Scanning failed"), exc),
                    error=True,
                    milliseconds=7000,
                )
        finally:
            close_progress_dialog()
            if scan_started:
                finisher = getattr(self.kodi, "finish_scan_status", None)
                if callable(finisher):
                    try:
                        finisher(scan_token)
                    except Exception as exc:
                        self.kodi.log.warning(
                            "Could not clear manual scan status: %s", exc
                        )

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
        if route == "collections":
            return self.collections(params)
        if route == "collection":
            return self.collection(int(params["id"]), params)
        if route == "slideshow/collection-pictures":
            return self.collection_slideshow_pictures(int(params["id"]), params)
        if route == "slideshow/saved-search-pictures":
            return self.saved_search_slideshow_pictures(
                int(params["id"]), params
            )
        if route == "home-slot":
            try:
                slot = int(params.get("slot") or 0)
            except (TypeError, ValueError):
                slot = 0
            if slot < 1 or slot > 9:
                self.kodi.log.warning(
                    "Home row ignored because its slot is invalid: %s",
                    params.get("slot"),
                )
                return self.finish([], content="images", cache=False)
            row = str(
                self.kodi.addon.getSetting("home_row_%d" % slot) or "none"
            )
            builtin_route = HOME_SLOT_ROUTE_BY_KEY.get(row)
            if builtin_route:
                return self.dispatch(Request(builtin_route, params))
            if row == "smart":
                return self.dispatch(Request("home-smart", params))
            if row == "collection":
                return self.dispatch(Request("home-collection", params))
            if row != "none":
                self.kodi.log.warning(
                    "Home row %d ignored because its type is invalid: %s",
                    slot,
                    row,
                )
            return self.finish([], content="images", cache=False)
        if route == "home-smart":
            try:
                slot = int(params.get("slot") or 0)
            except (TypeError, ValueError):
                slot = 0
            if slot < 1 or slot > 9:
                self.kodi.log.warning(
                    "Smart home row ignored because its slot is invalid: %s",
                    params.get("slot"),
                )
                return self.finish([], content="images", cache=False)
            try:
                saved_search_id = int(
                    self.kodi.addon.getSetting("home_smart_id_%d" % slot) or 0
                )
            except (TypeError, ValueError):
                saved_search_id = 0
            if saved_search_id <= 0:
                self.kodi.log.warning(
                    "Smart home row %d has no saved collection", slot
                )
                return self.finish([], content="images", cache=False)
            return self.saved_search(saved_search_id, params)
        if route == "home-collection":
            try:
                slot = int(params.get("slot") or 0)
            except (TypeError, ValueError):
                slot = 0
            if slot < 1 or slot > 9:
                self.kodi.log.warning(
                    "Manual collection home row ignored because its slot is invalid: %s",
                    params.get("slot"),
                )
                return self.finish([], content="images", cache=False)
            try:
                collection_id = int(
                    self.kodi.addon.getSetting(
                        "home_collection_id_%d" % slot
                    )
                    or 0
                )
            except (TypeError, ValueError):
                collection_id = 0
            if collection_id <= 0:
                self.kodi.log.warning(
                    "Manual collection home row %d has no collection", slot
                )
                return self.finish([], content="images", cache=False)
            return self.collection(collection_id, params)
        if route == "diagnostics":
            return self.diagnostics()
        if route == "metadata-browser":
            return self.metadata_browser(params)
        if route == "metadata-category":
            return self.metadata_category(params.get("category", ""), params)
        if route == "metadata-values":
            return self.metadata_values(params.get("field", ""), params)
        if route == "metadata-result":
            return self.metadata_result(
                params.get("field", ""), params.get("value", ""), params
            )
        if route == "needs-attention":
            return self.needs_attention(params)
        if route == "needs-attention-result":
            return self.needs_attention_result(params.get("kind", ""), params)
        if route == "metadata-mapping":
            return self.metadata_mapping(params)
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
            limit = self._result_limit(params, self._widget_default_limit(params))
            query_limit = (
                self._home_candidates_limit(limit)
                if self._is_home_widget(params)
                else limit
            )
            seed = self._home_random_seed(params, route)
            random_rows = (
                self.catalog.random_pictures(query_limit)
                if seed is None
                else self.catalog.random_pictures(query_limit, seed)
            )
            rows = self._prioritize_home_rows(random_rows, params, limit)
            return self.finish(
                [self._media_item(row, browse_params=params) for row in rows],
                category=self._rating_category(self.text(30003, "Random memories"), params),
                view_mode=self._browser_view_mode(params),
            )
        if route == "recent-folders":
            default_limit = (
                self._widget_default_limit(params)
                if parse_bool(params.get("widget"), False)
                else self.kodi.settings.browser_page_size
            )
            limit = self._result_limit(params, default_limit)
            return self.folders(route, self.catalog.recent_folders(limit), self.text(30004, "Recent albums"), params)
        if route == "random-folders":
            limit = self._result_limit(params, self._widget_default_limit(params))
            seed = self._home_random_seed(params, route)
            rows = (
                self.catalog.random_folders(limit)
                if seed is None
                else self.catalog.random_folders(limit, seed)
            )
            return self.folders(route, rows, self.text(30005, "Random albums"), params)
        if route == "on-this-day":
            now = datetime.now()
            getter = lambda limit, offset: self.catalog.on_this_day(now.month, now.day, now.year, limit, offset)
            return self.pictures(route, getter, params, self.text(30006, "On this day"))
        if route == "on-this-day-random":
            now = datetime.now()
            limit = self._result_limit(params, self._widget_default_limit(params))
            query_limit = (
                self._home_candidates_limit(limit)
                if self._is_home_widget(params)
                else limit
            )
            seed = self._home_random_seed(params, route)
            random_rows = (
                self.catalog.random_on_this_day(
                    now.month, now.day, now.year, query_limit
                )
                if seed is None
                else self.catalog.random_on_this_day(
                    now.month, now.day, now.year, query_limit, seed
                )
            )
            rows = self._prioritize_home_rows(random_rows, params, limit)
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
