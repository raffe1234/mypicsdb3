from __future__ import annotations

import sys
from datetime import datetime
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence, Tuple

import xbmc  # type: ignore
import xbmcgui  # type: ignore
import xbmcplugin  # type: ignore

from .router import Request
from .scanner import Scanner
from .utils import plugin_url, safe_limit


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

    def url(self, route: str, **params: Any) -> str:
        return plugin_url(self.base_url, route, **params)

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

    def finish(self, items: Sequence[Tuple[str, xbmcgui.ListItem, bool]], content: str = "images", cache: bool = False, category: Optional[str] = None):
        if category:
            xbmcplugin.setPluginCategory(self.handle, category)
        xbmcplugin.setContent(self.handle, content)
        xbmcplugin.addDirectoryItems(self.handle, list(items), len(items))
        xbmcplugin.endOfDirectory(self.handle, succeeded=True, cacheToDisc=cache)

    def root(self):
        items = [
            self.add_folder(self.text(30000, "Picture sources"), "sources"),
            self.add_folder(self.text(30001, "Recently taken"), "recent-taken"),
            self.add_folder(self.text(30002, "Recently added"), "recent-added"),
            self.add_folder(self.text(30003, "Random memories"), "random"),
            self.add_folder(self.text(30004, "Recent albums"), "recent-folders"),
            self.add_folder(self.text(30005, "Random albums"), "random-folders"),
            self.add_folder(self.text(30006, "On this day"), "on-this-day"),
            self.add_folder(self.text(30007, "Years"), "years"),
            self.add_folder(self.text(30008, "Cameras"), "cameras"),
            self.add_folder(self.text(30009, "Keywords"), "keywords"),
            self.add_folder(self.text(30010, "Favorites"), "favorites"),
            self.add_folder(self.text(30011, "Rated pictures"), "rated"),
            self.add_folder(self.text(30012, "Geotagged pictures"), "geotagged"),
            self.add_action(self.text(30013, "Scan now"), "action/scan"),
            self.add_folder(self.text(30014, "Scan status"), "status"),
            self.add_action(self.text(30015, "Settings"), "action/settings"),
        ]
        self.finish(items, content="files", category=self.text(30056, "MyPicsDB 3"))

    def sources(self):
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
            context = [(state, toggle), (self.text(30021, "Scan selected source"), scan)]
            if source.enabled:
                items.append(self.add_folder(label, "source", art=self.icon, context=context, id=source.id))
            else:
                items.append(self.add_action(label, "action/toggle-source", context=context, id=source.id))
        self.finish(items, content="files", category=self.text(30000, "Picture sources"))

    def source(self, source_id: int):
        source = self.catalog.get_source(source_id)
        if not source:
            self.finish([], category=self.text(30000, "Picture sources"))
            return
        folders = self.catalog.source_root_folders(source_id)
        items = [self._folder_item(folder) for folder in folders]
        self.finish(items, content="images", category=source.label)

    def _picture_item(self, row: Dict[str, Any]) -> Tuple[str, xbmcgui.ListItem, bool]:
        date_text = str(row.get("taken_at") or row.get("discovered_at") or "")
        label = row.get("filename") or date_text or self.text(30031, "Picture")
        item = self._item(label, row.get("thumb_uri") or row.get("uri"), row.get("uri"))
        info: Dict[str, Any] = {"title": label, "picturepath": row.get("uri", ""), "date": date_text}
        if row.get("width") and row.get("height"):
            info["resolution"] = "%sx%s" % (row["width"], row["height"])
        if row.get("camera_make"):
            info["cameramake"] = row["camera_make"]
        if row.get("camera_model"):
            info["cameramodel"] = row["camera_model"]
        if row.get("caption"):
            info["exifcomment"] = row["caption"]
        try:
            item.setInfo("pictures", info)
        except Exception:
            pass
        item.setProperty("MyPicsDB3.PictureId", str(row.get("id", "")))
        item.setProperty("MyPicsDB3.TakenAt", date_text)
        item.setProperty("MyPicsDB3.Camera", " ".join(filter(None, [row.get("camera_make"), row.get("camera_model")])))
        item.setProperty("MyPicsDB3.Folder", str(row.get("folder_name") or ""))
        item.setProperty("MyPicsDB3.Source", str(row.get("source_label") or ""))
        if row.get("rating") is not None:
            item.setProperty("MyPicsDB3.Rating", str(row["rating"]))
        toggle = "RunPlugin(%s)" % self.url("action/toggle-favorite", id=row.get("id"))
        context = [(self.text(30022, "Toggle favorite"), toggle)]
        if row.get("folder_id"):
            context.append((self.text(30023, "Open containing album"), "ActivateWindow(Pictures,%s,return)" % self.url("folder", id=row["folder_id"])))
        item.addContextMenuItems(context)
        return (str(row.get("uri") or ""), item, False)

    def _folder_item(self, row: Dict[str, Any]) -> Tuple[str, xbmcgui.ListItem, bool]:
        count = int(row.get("picture_count") or 0)
        label = "%s  [COLOR=grey](%d)[/COLOR]" % (row.get("name") or self.text(30032, "Album"), count)
        art = row.get("representative_thumb") or row.get("representative_uri") or self.icon
        context = [(self.text(30021, "Scan selected source"), "RunPlugin(%s)" % self.url("action/scan", source=row.get("source_id")))]
        if row.get("uri"):
            context.append(("Slideshow", "SlideShow(%s,recursive)" % row["uri"]))
        return self.add_folder(label, "folder", art=art, context=context, id=row["id"])

    def _next_page_item(self, route: str, offset: int, limit: int, **params: Any):
        return self.add_folder(self.text(30024, "Next page"), route, offset=offset + limit, limit=limit, **params)

    def pictures(self, route: str, getter: Callable[[int, int], List[Dict[str, Any]]], params: Dict[str, str], category: str, random_view: bool = False):
        default_limit = self.kodi.settings.widget_limit if "limit" in params else self.kodi.settings.browser_page_size
        limit = safe_limit(params.get("limit"), default_limit)
        offset = int(params.get("offset", "0") or 0)
        rows = getter(limit, offset)
        items = [self._picture_item(row) for row in rows]
        if not random_view and len(rows) == limit and "limit" not in params:
            items.append(self._next_page_item(route, offset, limit))
        self.finish(items, content="images", cache=False, category=category)

    def folder(self, folder_id: int, params: Dict[str, str]):
        folder = self.catalog.get_folder(folder_id)
        if not folder:
            self.finish([], category=self.text(30032, "Albums"))
            return
        child_folders = self.catalog.child_folders(int(folder["source_id"]), folder["uri"])
        limit = safe_limit(params.get("limit"), self.kodi.settings.browser_page_size)
        offset = int(params.get("offset", "0") or 0)
        pictures = self.catalog.pictures_in_folder(folder_id, limit, offset)
        items = [self._folder_item(row) for row in child_folders]
        items.extend(self._picture_item(row) for row in pictures)
        if len(pictures) == limit:
            items.append(self._next_page_item("folder", offset, limit, id=folder_id))
        self.finish(items, content="images", category=folder.get("name") or self.text(30032, "Albums"))

    def folders(self, route: str, rows: List[Dict[str, Any]], category: str):
        self.finish([self._folder_item(row) for row in rows], content="images", category=category)

    def years(self):
        items = []
        for row in self.catalog.years():
            label = "%s  [COLOR=grey](%s)[/COLOR]" % (row["year"], row["picture_count"])
            items.append(self.add_folder(label, "year", art=row.get("thumb_uri") or row.get("uri"), year=row["year"]))
        self.finish(items, content="images", category=self.text(30007, "Years"))

    def cameras(self):
        items = []
        for row in self.catalog.cameras():
            name = " ".join(filter(None, [row.get("camera_make"), row.get("camera_model")])) or self.text(30033, "Unknown camera")
            label = "%s  [COLOR=grey](%s)[/COLOR]" % (name, row["picture_count"])
            items.append(self.add_folder(label, "camera", art=row.get("thumb_uri") or row.get("uri"), make=row.get("camera_make", ""), model=row.get("camera_model", "")))
        self.finish(items, content="images", category=self.text(30008, "Cameras"))

    def keywords(self):
        items = []
        for row in self.catalog.tags():
            label = "%s  [COLOR=grey](%s)[/COLOR]" % (row["name"], row["picture_count"])
            items.append(self.add_folder(label, "tag", art=row.get("thumb_uri") or row.get("uri"), id=row["id"]))
        self.finish(items, content="images", category=self.text(30009, "Keywords"))

    def status(self):
        overview = self.catalog.overview()
        latest = self.catalog.latest_scan()
        values = [
            "%s: %s" % (self.text(30041, "Database backend"), overview["backend"]),
            "%s: %s" % (self.text(30038, "Indexed pictures"), overview["pictures"]),
            "%s: %s" % (self.text(30039, "Missing pictures"), overview["missing"]),
            "%s: %s" % (self.text(30040, "Indexed albums"), overview["folders"]),
            "%s: %s" % (self.text(30036, "Last scan"), latest.get("finished_at") if latest else self.text(30037, "Never")),
        ]
        if latest:
            values.extend([
                "Status: %s" % latest.get("status"),
                "%s: %s" % (self.text(30047, "Pictures found"), latest.get("pictures_seen", 0)),
                "%s: %s" % (self.text(30048, "Pictures updated"), int(latest.get("pictures_added", 0)) + int(latest.get("pictures_updated", 0))),
                "%s: %s" % (self.text(30049, "Pictures unchanged"), latest.get("pictures_unchanged", 0)),
                "%s: %s" % (self.text(30050, "Errors"), latest.get("errors", 0)),
            ])
        items = [("", self._item(value), False) for value in values]
        items.append(self.add_action(self.text(30060, "Test database connection"), "action/test-db"))
        items.append(self.add_action(self.text(30061, "Clean missing records"), "action/cleanup"))
        self.finish(items, content="files", category=self.text(30014, "Scan status"))

    def action(self, route: str, params: Dict[str, str]):
        if route == "action/settings":
            self.kodi.open_settings()
            return
        if route == "action/refresh-sources":
            self.catalog.sync_sources(self.kodi.kodi_picture_sources())
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
        if route == "action/scan":
            self._manual_scan(params.get("source"))
            return

    def _manual_scan(self, source_id: Optional[str]):
        dialog = xbmcgui.DialogProgress()
        dialog.create(self.text(30056, "MyPicsDB 3"), self.text(30026, "Scanning started"))

        def cancelled() -> bool:
            return dialog.iscanceled()

        def progress(source, path, stats):
            dialog.update(0, "%s\n%s\n%s: %d" % (source.label, path, self.text(30047, "Pictures found"), stats.pictures_seen))

        scanner = Scanner(self.catalog, self.runtime.filesystem, self.kodi.settings, self.kodi.log, cancelled=cancelled, progress=progress)
        try:
            stats = scanner.scan_sources([int(source_id)] if source_id else None)
            if stats.cancelled:
                self.kodi.notify(self.text(30042, "Scan cancelled"))
            else:
                message = "%s: %d, %s: %d" % (self.text(30047, "Pictures found"), stats.pictures_seen, self.text(30050, "Errors"), stats.errors)
                self.kodi.notify(message, error=stats.errors > 0, milliseconds=6000)
        except RuntimeError as exc:
            self.kodi.notify(str(exc), error=True)
        finally:
            dialog.close()
            xbmc.executebuiltin("Container.Refresh")

    def dispatch(self, request: Request):
        route = request.route
        params = request.params
        if not route:
            return self.root()
        if route.startswith("action/"):
            return self.action(route, params)
        if route == "sources":
            return self.sources()
        if route == "source":
            return self.source(int(params["id"]))
        if route == "folder":
            return self.folder(int(params["id"]), params)
        if route == "recent-taken":
            return self.pictures(route, self.catalog.recent_taken, params, self.text(30001, "Recently taken"))
        if route == "recent-added":
            return self.pictures(route, self.catalog.recent_added, params, self.text(30002, "Recently added"))
        if route == "random":
            limit = safe_limit(params.get("limit"), self.kodi.settings.widget_limit)
            return self.finish([self._picture_item(row) for row in self.catalog.random_pictures(limit)], category=self.text(30003, "Random memories"))
        if route == "recent-folders":
            limit = safe_limit(params.get("limit"), self.kodi.settings.widget_limit if "limit" in params else self.kodi.settings.browser_page_size)
            return self.folders(route, self.catalog.recent_folders(limit), self.text(30004, "Recent albums"))
        if route == "random-folders":
            limit = safe_limit(params.get("limit"), self.kodi.settings.widget_limit)
            return self.folders(route, self.catalog.random_folders(limit), self.text(30005, "Random albums"))
        if route == "on-this-day":
            now = datetime.now()
            getter = lambda limit, offset: self.catalog.on_this_day(now.month, now.day, now.year, limit, offset)
            return self.pictures(route, getter, params, self.text(30006, "On this day"))
        if route == "years":
            return self.years()
        if route == "year":
            year = int(params["year"])
            return self.pictures(route, lambda limit, offset: self.catalog.pictures_for_year(year, limit, offset), params, str(year))
        if route == "cameras":
            return self.cameras()
        if route == "camera":
            make, model = params.get("make", ""), params.get("model", "")
            title = " ".join(filter(None, [make, model])) or self.text(30033, "Unknown camera")
            return self.pictures(route, lambda limit, offset: self.catalog.pictures_for_camera(make, model, limit, offset), params, title)
        if route == "keywords":
            return self.keywords()
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
        return self.root()
