from __future__ import annotations

import json
import os
from typing import Any, Dict, List, Optional

from .config import Settings, from_getter
from .log import Logger
from .utils import is_indexable_picture_source_uri, normalize_uri

try:
    import xbmc  # type: ignore
    import xbmcaddon  # type: ignore
    import xbmcgui  # type: ignore
    import xbmcvfs  # type: ignore
except ImportError:  # pragma: no cover - Kodi modules are unavailable in unit tests
    xbmc = xbmcaddon = xbmcgui = xbmcvfs = None


class KodiContext:
    def __init__(self):
        if xbmcaddon is None:
            raise RuntimeError("Kodi Python modules are not available")
        self.addon = xbmcaddon.Addon()
        self.addon_id = self.addon.getAddonInfo("id")
        self.name = self.addon.getAddonInfo("name")
        self.profile_path = self.translate(self.addon.getAddonInfo("profile"))
        if xbmcvfs and not xbmcvfs.exists(self.profile_path):
            xbmcvfs.mkdirs(self.profile_path)
        self.settings = self.load_settings()
        self.log = Logger(self.name, self.settings.debug_logging, xbmc)

    @staticmethod
    def translate(path: str) -> str:
        if xbmcvfs is not None and hasattr(xbmcvfs, "translatePath"):
            return xbmcvfs.translatePath(path)
        if xbmc is not None and hasattr(xbmc, "translatePath"):
            return xbmc.translatePath(path)
        return path

    def load_settings(self) -> Settings:
        return from_getter(self.addon.getSetting, self.profile_path)

    def refresh_settings(self) -> Settings:
        self.settings = self.load_settings()
        self.log.debug_enabled = self.settings.debug_logging
        return self.settings

    def localize(self, string_id: int, fallback: str = "") -> str:
        value = self.addon.getLocalizedString(string_id)
        return value or fallback

    def notify(self, message: str, error: bool = False, milliseconds: int = 4000) -> None:
        if not self.settings.show_notifications or xbmcgui is None:
            return
        icon = xbmcgui.NOTIFICATION_ERROR if error else xbmcgui.NOTIFICATION_INFO
        xbmcgui.Dialog().notification(self.name, message, icon, milliseconds)

    def execute_jsonrpc(self, method: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        request = {"jsonrpc": "2.0", "id": 1, "method": method}
        if params is not None:
            request["params"] = params
        response = json.loads(xbmc.executeJSONRPC(json.dumps(request)))
        if "error" in response:
            raise RuntimeError("JSON-RPC %s failed: %s" % (method, response["error"]))
        return response.get("result", {})

    def kodi_picture_sources(self) -> List[Dict[str, str]]:
        result = self.execute_jsonrpc("Files.GetSources", {"media": "pictures"})
        sources: List[Dict[str, str]] = []
        for source in result.get("sources", []):
            uri = normalize_uri(str(source.get("file", "")), directory=True)
            if is_indexable_picture_source_uri(uri):
                sources.append({"label": str(source.get("label") or uri), "uri": uri})
        return sources

    def open_settings(self) -> None:
        self.addon.openSettings()

    @staticmethod
    def refresh_date_sensitive_views() -> None:
        """Refresh views whose contents depend on the local calendar date.

        Estuary home-screen widgets keep their directory contents until the
        skin is rebuilt. Reloading the custom skin once at midnight refreshes
        all rows; elsewhere a normal container refresh is sufficient.
        """
        if xbmc is None:
            return
        current_window = xbmcgui.getCurrentWindowId() if xbmcgui and hasattr(xbmcgui, "getCurrentWindowId") else None
        skin_id = xbmc.getSkinDir() if hasattr(xbmc, "getSkinDir") else ""
        if current_window == 10000 and skin_id == "skin.estuary.mypicsdb3":
            xbmc.executebuiltin("ReloadSkin()")
        else:
            xbmc.executebuiltin("Container.Refresh")

    @staticmethod
    def is_playing() -> bool:
        return bool(xbmc and xbmc.Player().isPlaying())

    @staticmethod
    def abort_monitor():
        return xbmc.Monitor() if xbmc else None
