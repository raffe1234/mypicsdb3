from __future__ import annotations

import json
import os
import time
import uuid
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


SHUTDOWN_NOTIFICATION_METHODS = frozenset(("System.OnQuit", "System.OnRestart"))
HOME_WINDOW_ID = 10000
MIXED_SLIDESHOW_PROPERTY = "MyPicsDB3.MixedSlideshowActive"
PICTURE_PLAYLIST_COMPATIBILITY_PROPERTY = "MyPicsDB3.PicturePlaylistCompatibilityV2"
SLIDESHOW_START_PROPERTY = "MyPicsDB3.SlideshowStart"
SLIDESHOW_START_TTL_SECONDS = 180.0


def create_abort_monitor(xbmc_module=None):
    """Create a monitor that reacts to Kodi's early shutdown notification.

    Kodi sends ``System.OnQuit`` before the service manager triggers the normal
    Monitor abort flag. Catching that notification lets scans stop while Kodi is
    still in the first part of its shutdown sequence.
    """

    module = xbmc_module if xbmc_module is not None else xbmc
    if module is None:
        return None

    class ShutdownAwareMonitor(module.Monitor):
        def __init__(self):
            super().__init__()
            self._shutdown_requested = False

        def onNotification(self, sender, method, data):  # noqa: N802 - Kodi API
            if str(method or "") in SHUTDOWN_NOTIFICATION_METHODS:
                self._shutdown_requested = True

        def abortRequested(self):  # noqa: N802 - Kodi API
            return bool(self._shutdown_requested or super().abortRequested())

        def waitForAbort(self, timeout):  # noqa: N802 - Kodi API
            if self._shutdown_requested:
                return True
            native_abort = super().waitForAbort(timeout)
            return bool(native_abort or self._shutdown_requested)

    return ShutdownAwareMonitor()


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

    def notify(
        self,
        message: str,
        error: bool = False,
        milliseconds: int = 4000,
        force: bool = False,
    ) -> None:
        if (
            (not force and not self.settings.show_notifications)
            or xbmcgui is None
        ):
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
    def refresh_date_sensitive_views() -> bool:
        """Refresh views whose contents depend on the local calendar date.

        The custom Estuary home rows are cached until the skin is rebuilt.
        Reloading a skin while Kodi is scanning, playing media, displaying a
        modal dialog or running a screen saver can destabilize the GUI, so the
        background service must defer and retry until the home window is idle.
        """
        if xbmc is None:
            return True

        current_window = (
            xbmcgui.getCurrentWindowId()
            if xbmcgui and hasattr(xbmcgui, "getCurrentWindowId")
            else None
        )
        skin_id = xbmc.getSkinDir() if hasattr(xbmc, "getSkinDir") else ""
        if skin_id != "skin.estuary.mypicsdb3":
            xbmc.executebuiltin("Container.Refresh")
            return True

        if current_window != 10000:
            return False

        if hasattr(xbmc, "getCondVisibility"):
            unsafe_conditions = (
                "Library.IsScanning",
                "Player.HasMedia",
                "System.HasActiveModalDialog",
                "System.ScreenSaverActive",
                "System.DPMSActive",
            )
            if any(xbmc.getCondVisibility(condition) for condition in unsafe_conditions):
                return False

        xbmc.executebuiltin("ReloadSkin()")
        return True

    def acquire_slideshow_start(self) -> Optional[str]:
        """Acquire a short session-local guard for playlist construction.

        Kodi may launch multiple plug-in interpreter instances when slideshow
        actions are selected repeatedly. Without a guard, those instances can
        clear and append to the same global Kodi playlists concurrently.
        """

        if xbmcgui is None:
            return uuid.uuid4().hex
        try:
            window = xbmcgui.Window(HOME_WINDOW_ID)
            now = time.time()
            current = str(window.getProperty(SLIDESHOW_START_PROPERTY) or "")
            if current:
                _token, _separator, timestamp = current.partition("|")
                try:
                    age = now - float(timestamp)
                except (TypeError, ValueError):
                    age = SLIDESHOW_START_TTL_SECONDS + 1.0
                if 0.0 <= age < SLIDESHOW_START_TTL_SECONDS:
                    self.log.info(
                        "Slideshow start ignored: another slideshow is being prepared"
                    )
                    return None

            token = uuid.uuid4().hex
            value = "%s|%.6f" % (token, now)
            window.setProperty(SLIDESHOW_START_PROPERTY, value)
            if str(window.getProperty(SLIDESHOW_START_PROPERTY) or "") != value:
                self.log.info(
                    "Slideshow start ignored: another slideshow acquired the guard"
                )
                return None
            self.log.debug("Slideshow start guard acquired")
            return token
        except Exception as exc:
            self.log.warning("Could not acquire slideshow start guard: %s", exc)
            return uuid.uuid4().hex

    def release_slideshow_start(self, token: str) -> None:
        if xbmcgui is None:
            return
        try:
            window = xbmcgui.Window(HOME_WINDOW_ID)
            current = str(window.getProperty(SLIDESHOW_START_PROPERTY) or "")
            current_token, _separator, _timestamp = current.partition("|")
            if current_token == str(token or ""):
                window.clearProperty(SLIDESHOW_START_PROPERTY)
                self.log.debug("Slideshow start guard released")
        except Exception as exc:
            self.log.warning("Could not release slideshow start guard: %s", exc)

    def set_mixed_slideshow_active(self, active: bool) -> None:
        """Publish whether MyPicsDB owns the current database slideshow.

        Kodi plug-in actions and the background service run in separate Python
        interpreters. A property on the Home window is a lightweight, session-
        local hand-off that avoids persistent settings or profile files.
        """

        if xbmcgui is None:
            return
        try:
            window = xbmcgui.Window(HOME_WINDOW_ID)
            if active:
                window.setProperty(MIXED_SLIDESHOW_PROPERTY, "true")
            else:
                window.clearProperty(MIXED_SLIDESHOW_PROPERTY)
            self.log.debug(
                "Mixed slideshow monitor state: %s",
                "active" if active else "inactive",
            )
        except Exception as exc:
            self.log.warning("Could not update mixed slideshow state: %s", exc)

    @staticmethod
    def mixed_slideshow_active() -> bool:
        if xbmcgui is None:
            return False
        try:
            value = xbmcgui.Window(HOME_WINDOW_ID).getProperty(
                MIXED_SLIDESHOW_PROPERTY
            )
            return str(value or "").strip().lower() == "true"
        except Exception:
            return False

    def set_picture_playlist_compatibility(self, compatible: Optional[bool]) -> None:
        """Cache picture-playlist support for the current Kodi session."""

        if xbmcgui is None:
            return
        try:
            window = xbmcgui.Window(HOME_WINDOW_ID)
            if compatible is None:
                window.clearProperty(PICTURE_PLAYLIST_COMPATIBILITY_PROPERTY)
                value = "unknown"
            else:
                value = "compatible" if compatible else "incompatible"
                window.setProperty(PICTURE_PLAYLIST_COMPATIBILITY_PROPERTY, value)
            self.log.debug("Picture playlist compatibility: %s", value)
        except Exception as exc:
            self.log.warning(
                "Could not update picture playlist compatibility: %s", exc
            )

    @staticmethod
    def picture_playlist_compatibility() -> Optional[bool]:
        if xbmcgui is None:
            return None
        try:
            value = str(
                xbmcgui.Window(HOME_WINDOW_ID).getProperty(
                    PICTURE_PLAYLIST_COMPATIBILITY_PROPERTY
                )
                or ""
            ).strip().lower()
        except Exception:
            return None
        if value == "compatible":
            return True
        if value == "incompatible":
            return False
        return None

    @staticmethod
    def is_playing() -> bool:
        return bool(xbmc and xbmc.Player().isPlaying())

    @staticmethod
    def playing_file() -> str:
        if xbmc is None:
            return ""
        try:
            player = xbmc.Player()
            if not player.isPlaying():
                return ""
            return normalize_uri(str(player.getPlayingFile() or ""))
        except Exception:
            return ""

    @staticmethod
    def abort_monitor():
        return create_abort_monitor()
