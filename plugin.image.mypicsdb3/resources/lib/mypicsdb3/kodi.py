from __future__ import annotations

import hashlib
import json
import os
import time
import uuid
from typing import Any, Dict, List, Optional

from .config import Settings, from_getter, resolve_home_widget_limit
from .log import Logger
from .utils import is_indexable_picture_source_uri, normalize_uri, parse_bool

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
MUSIC_SLIDESHOW_PROPERTY = "MyPicsDB3.MusicSlideshowSessionV1"
PICTURE_PLAYLIST_COMPATIBILITY_PROPERTY = "MyPicsDB3.PicturePlaylistCompatibilityV2"
SLIDESHOW_START_PROPERTY = "MyPicsDB3.SlideshowStart"
SLIDESHOW_START_TTL_SECONDS = 180.0
SCAN_STATUS_PROPERTY = "MyPicsDB3.ScanStatusV1"
SCAN_CANCEL_PROPERTY = "MyPicsDB3.ScanCancelV1"
HOME_WIDGET_GENERATION_PROPERTY = "MyPicsDB3.HomeWidgetGeneration"
RANDOM_HOME_WIDGET_GENERATION_PROPERTY = "MyPicsDB3.RandomWidgetGeneration"
HOME_WIDGET_LIMIT_PROPERTY = "MyPicsDB3.HomeWidgetLimit"
HOME_LAYOUT_SLOT_COUNT = 9
HOME_ROW_PROPERTY_FORMAT = "MyPicsDB3.HomeRow%d"
HOME_SMART_ID_PROPERTY_FORMAT = "MyPicsDB3.HomeSmartId%d"
HOME_SMART_NAME_PROPERTY_FORMAT = "MyPicsDB3.HomeSmartName%d"
HOME_SMART_MODE_PROPERTY_FORMAT = "MyPicsDB3.HomeSmartMode%d"
HOME_COLLECTION_ID_PROPERTY_FORMAT = "MyPicsDB3.HomeCollectionId%d"
HOME_COLLECTION_NAME_PROPERTY_FORMAT = "MyPicsDB3.HomeCollectionName%d"

INTEGER_SETTING_IDS = frozenset(
    {
        "widget_limit",
        "home_widget_limit",
        "random_home_refresh_hours",
        "browser_page_size",
        "album_view_mode",
        "scan_interval_hours",
        "startup_delay_seconds",
        "batch_size",
        "metadata_prefix_mb",
        "deep_metadata_max_mb",
        "mysql_port",
        "mysql_connect_timeout",
        "missing_retention_days",
    }
)
BOOLEAN_SETTING_IDS = frozenset(
    {
        "show_notifications",
        "auto_scan",
        "pause_during_playback",
        "include_videos",
        "exclude_hidden",
        "read_xmp",
        "read_iptc",
        "store_gps",
        "mysql_auto_create",
        "debug_logging",
        "home_widget_limit_migrated_v2",
    }
)


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
    def __init__(self, publish_home_state: bool = True):
        if xbmcaddon is None:
            raise RuntimeError("Kodi Python modules are not available")
        self._publish_home_state_on_refresh = bool(publish_home_state)
        self.addon = xbmcaddon.Addon()
        self.addon_id = self.addon.getAddonInfo("id")
        self.name = self.addon.getAddonInfo("name")
        self.profile_path = self.translate(self.addon.getAddonInfo("profile"))
        if xbmcvfs and not xbmcvfs.exists(self.profile_path):
            xbmcvfs.mkdirs(self.profile_path)
        migration = self._migrate_home_widget_limit_setting()
        self.settings = self.load_settings()
        self.log = Logger(self.name, self.settings.debug_logging, xbmc)
        if migration is not None:
            old_widget, old_home, effective, saved = migration
            self.log.info(
                "Home-screen row-count migration: widget_limit=%d, "
                "home_widget_limit=%d, effective=%d, saved=%s",
                old_widget,
                old_home,
                effective,
                str(bool(saved)).lower(),
            )
        if self._publish_home_state_on_refresh:
            self.publish_home_state()

    @staticmethod
    def translate(path: str) -> str:
        if xbmcvfs is not None and hasattr(xbmcvfs, "translatePath"):
            return xbmcvfs.translatePath(path)
        if xbmc is not None and hasattr(xbmc, "translatePath"):
            return xbmc.translatePath(path)
        return path

    def _set_integer_setting(self, setting_id: str, value: int) -> bool:
        get_settings = getattr(self.addon, "getSettings", None)
        if callable(get_settings):
            try:
                get_settings().setInt(setting_id, int(value))
                return True
            except Exception:
                pass
        typed_setter = getattr(self.addon, "setSettingInt", None)
        if callable(typed_setter):
            try:
                return bool(typed_setter(setting_id, int(value)))
            except Exception:
                pass
        try:
            result = self.addon.setSetting(setting_id, str(int(value)))
            return True if result is None else bool(result)
        except Exception:
            return False

    def _set_boolean_setting(self, setting_id: str, value: bool) -> bool:
        get_settings = getattr(self.addon, "getSettings", None)
        if callable(get_settings):
            try:
                get_settings().setBool(setting_id, bool(value))
                return True
            except Exception:
                pass
        typed_setter = getattr(self.addon, "setSettingBool", None)
        if callable(typed_setter):
            try:
                return bool(typed_setter(setting_id, bool(value)))
            except Exception:
                pass
        try:
            result = self.addon.setSetting(
                setting_id, "true" if value else "false"
            )
            return True if result is None else bool(result)
        except Exception:
            return False

    def _migrate_home_widget_limit_setting(self):
        getter = self._setting_getter()
        migration_complete = parse_bool(
            getter("home_widget_limit_migrated_v2"), False
        )
        if migration_complete:
            return None
        old_widget = int(
            resolve_home_widget_limit(getter("widget_limit"), 10, True)
        )
        try:
            old_home = max(4, min(40, int(getter("home_widget_limit"))))
        except (TypeError, ValueError):
            old_home = 10
        effective = resolve_home_widget_limit(old_widget, old_home, False)
        saved = (
            self._set_integer_setting("widget_limit", effective)
            and self._set_integer_setting("home_widget_limit", effective)
            and self._set_boolean_setting("home_widget_limit_migrated_v2", True)
        )
        return old_widget, old_home, effective, saved

    def _setting_getter(self):
        legacy_getter = self.addon.getSetting
        get_settings = getattr(self.addon, "getSettings", None)
        if not callable(get_settings):
            return legacy_getter
        try:
            settings_api = get_settings()
        except Exception:
            return legacy_getter

        def getter(setting_id: str):
            try:
                if setting_id in INTEGER_SETTING_IDS:
                    return settings_api.getInt(setting_id)
                if setting_id in BOOLEAN_SETTING_IDS:
                    return settings_api.getBool(setting_id)
                return settings_api.getString(setting_id)
            except Exception:
                return legacy_getter(setting_id)

        return getter

    def load_settings(self) -> Settings:
        return from_getter(self._setting_getter(), self.profile_path)

    def refresh_settings(self) -> Settings:
        self.settings = self.load_settings()
        self.log.debug_enabled = self.settings.debug_logging
        if self._publish_home_state_on_refresh:
            self.publish_home_widget_limit()
        return self.settings

    def publish_home_state(self) -> None:
        """Publish the settings consumed by the Estuary home integration."""

        self.publish_home_widget_limit()
        self.publish_home_layout_slots()

    def enable_home_state_publishing(self) -> None:
        """Enable refresh-time publishing and publish the initial state once."""

        self._publish_home_state_on_refresh = True
        self.publish_home_state()

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
        try:
            xbmcgui.Dialog().notification(self.name, message, icon, milliseconds)
        except Exception as exc:
            self.log.warning("Could not show notification: %s", exc)

    @staticmethod
    def _home_window():
        if xbmcgui is None:
            return None
        try:
            return xbmcgui.Window(HOME_WINDOW_ID)
        except Exception:
            return None

    def scan_status(self) -> Dict[str, Any]:
        """Return the current cross-interpreter scan state.

        Kodi runs the plug-in actions and the background service in separate
        Python interpreters. A Home-window property is therefore used as a
        lightweight session-local hand-off for menu state, progress and soft
        cancellation requests.
        """

        window = self._home_window()
        if window is None:
            return {}
        try:
            raw = str(window.getProperty(SCAN_STATUS_PROPERTY) or "")
            value = json.loads(raw) if raw else {}
        except Exception:
            return {}
        if not isinstance(value, dict) or not str(value.get("token") or ""):
            return {}
        return value

    def begin_scan_status(self, token: str, kind: str) -> None:
        window = self._home_window()
        if window is None:
            return
        value = {
            "token": str(token),
            "kind": str(kind or "manual"),
            "state": "running",
            "pictures_seen": 0,
            "source": "",
            "path": "",
            "started_at": time.time(),
        }
        try:
            window.clearProperty(SCAN_CANCEL_PROPERTY)
            window.setProperty(
                SCAN_STATUS_PROPERTY,
                json.dumps(value, ensure_ascii=False, separators=(",", ":")),
            )
        except Exception as exc:
            self.log.warning("Could not publish scan start: %s", exc)

    def update_scan_status(
        self,
        token: str,
        source: str,
        path: str,
        pictures_seen: int,
    ) -> None:
        window = self._home_window()
        if window is None:
            return
        current = self.scan_status()
        if str(current.get("token") or "") != str(token):
            return
        current.update(
            {
                "source": str(source or ""),
                "path": str(path or ""),
                "pictures_seen": max(0, int(pictures_seen or 0)),
            }
        )
        try:
            window.setProperty(
                SCAN_STATUS_PROPERTY,
                json.dumps(current, ensure_ascii=False, separators=(",", ":")),
            )
        except Exception as exc:
            self.log.warning("Could not publish scan progress: %s", exc)

    def scan_cancel_requested(self, token: str) -> bool:
        window = self._home_window()
        if window is None:
            return False
        try:
            return str(window.getProperty(SCAN_CANCEL_PROPERTY) or "") == str(token)
        except Exception:
            return False

    def request_scan_cancel(self) -> bool:
        window = self._home_window()
        if window is None:
            return False
        current = self.scan_status()
        token = str(current.get("token") or "")
        if not token:
            return False
        current["state"] = "cancelling"
        try:
            window.setProperty(SCAN_CANCEL_PROPERTY, token)
            window.setProperty(
                SCAN_STATUS_PROPERTY,
                json.dumps(current, ensure_ascii=False, separators=(",", ":")),
            )
            return True
        except Exception as exc:
            self.log.warning("Could not request scan cancellation: %s", exc)
            return False

    def finish_scan_status(self, token: str) -> None:
        window = self._home_window()
        if window is None:
            return
        try:
            current = self.scan_status()
            if str(current.get("token") or "") == str(token):
                window.clearProperty(SCAN_STATUS_PROPERTY)
            if str(window.getProperty(SCAN_CANCEL_PROPERTY) or "") == str(token):
                window.clearProperty(SCAN_CANCEL_PROPERTY)
        except Exception as exc:
            self.log.warning("Could not clear scan status: %s", exc)

    def publish_home_widget_limit(self) -> int:
        settings = getattr(self, "settings", None)
        limit = max(4, min(40, int(getattr(settings, "home_widget_limit", 10))))
        window = self._home_window()
        if window is None:
            return limit
        try:
            window.setProperty(HOME_WIDGET_LIMIT_PROPERTY, str(limit))
        except Exception as exc:
            logger = getattr(self, "log", None)
            if logger is not None:
                logger.warning("Could not publish home-screen widget limit: %s", exc)
        return limit

    def publish_home_layout_slots(self) -> None:
        """Publish home-row settings as comma-free Home-window properties.

        Kodi's ``$INFO[...]`` label parser treats commas as prefix/suffix
        separators, so a nested ``Addon.SettingStr(addon_id,setting_id)`` cannot
        safely be embedded in widget URLs. The Estuary integration reads these
        simple properties instead.
        """

        window = self._home_window()
        addon = getattr(self, "addon", None)
        if window is None or addon is None:
            return
        try:
            for position in range(1, HOME_LAYOUT_SLOT_COUNT + 1):
                row = str(addon.getSetting("home_row_%d" % position) or "none")
                raw_smart_id = addon.getSetting("home_smart_id_%d" % position)
                try:
                    smart_id = max(0, int(raw_smart_id or 0))
                except (TypeError, ValueError):
                    smart_id = 0
                smart_name = str(
                    addon.getSetting("home_smart_name_%d" % position) or ""
                )
                raw_collection_id = addon.getSetting(
                    "home_collection_id_%d" % position
                )
                try:
                    collection_id = max(0, int(raw_collection_id or 0))
                except (TypeError, ValueError):
                    collection_id = 0
                collection_name = str(
                    addon.getSetting("home_collection_name_%d" % position)
                    or ""
                )
                # The property remains for 0.4.10 skin compatibility, but
                # 0.4.11 no longer exposes per-row dynamic collection layouts.
                smart_mode = "poster"
                window.setProperty(HOME_ROW_PROPERTY_FORMAT % position, row)
                window.setProperty(
                    HOME_SMART_ID_PROPERTY_FORMAT % position, str(smart_id)
                )
                window.setProperty(
                    HOME_SMART_NAME_PROPERTY_FORMAT % position, smart_name
                )
                window.setProperty(
                    HOME_SMART_MODE_PROPERTY_FORMAT % position, smart_mode
                )
                window.setProperty(
                    HOME_COLLECTION_ID_PROPERTY_FORMAT % position,
                    str(collection_id),
                )
                window.setProperty(
                    HOME_COLLECTION_NAME_PROPERTY_FORMAT % position,
                    collection_name,
                )
        except Exception as exc:
            logger = getattr(self, "log", None)
            if logger is not None:
                logger.warning("Could not publish home-screen layout: %s", exc)

    def _increment_home_window_counter(
        self, property_name: str, log_label: str, reason: str = ""
    ) -> int:
        window = self._home_window()
        if window is None:
            return 0
        try:
            current = int(str(window.getProperty(property_name) or "0"))
        except (TypeError, ValueError):
            current = 0
        generation = 1 if current >= 2147483646 else current + 1
        try:
            window.setProperty(property_name, str(generation))
            if reason:
                self.log.debug(
                    "%s invalidated (%s), generation=%d",
                    log_label,
                    reason,
                    generation,
                )
            return generation
        except Exception as exc:
            self.log.warning("Could not invalidate %s: %s", log_label.lower(), exc)
            return current

    def invalidate_home_widgets(self, reason: str = "") -> int:
        """Change the home content-provider URL without reloading the skin.

        The Estuary integration includes this Home-window generation value in
        every MyPicsDB 3 widget URL. Updating it makes Kodi request fresh
        database results while preserving the rest of the home screen and its
        texture cache.
        """

        self.publish_home_widget_limit()
        self.publish_home_layout_slots()
        return self._increment_home_window_counter(
            HOME_WIDGET_GENERATION_PROPERTY,
            "Home-screen widgets",
            reason,
        )

    def invalidate_random_home_widgets(self, reason: str = "") -> int:
        """Refresh only Estuary rows whose providers return random results."""

        return self._increment_home_window_counter(
            RANDOM_HOME_WIDGET_GENERATION_PROPERTY,
            "Random home-screen widgets",
            reason,
        )

    def create_background_progress(self, heading: str, message: str):
        if xbmcgui is None:
            return None
        try:
            dialog = xbmcgui.DialogProgressBG()
            dialog.create(heading, message)
            return dialog
        except Exception as exc:
            self.log.warning("Could not create background progress dialog: %s", exc)
            return None

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
    def refresh_random_views() -> None:
        """Request fresh random plug-in results and home-screen widgets.

        Random routes are database-only and are deliberately not persisted.
        Refresh the active plug-in container, then reload the optional Estuary
        fork so its content-provider rows invoke those routes again.
        """

        if xbmc is None:
            return
        xbmc.executebuiltin("Container.Refresh")
        skin_id = xbmc.getSkinDir() if hasattr(xbmc, "getSkinDir") else ""
        if skin_id == "skin.estuary.mypicsdb3":
            # Estuary remembers one horizontal widget position globally. A
            # fresh random result set can otherwise reopen with its first item
            # mostly outside the viewport, which looks like an empty tile.
            xbmc.executebuiltin("ClearProperty(listposition,home)")
            xbmc.executebuiltin("ReloadSkin()")

    @staticmethod
    def refresh_date_sensitive_views() -> bool:
        """Request a lightweight refresh for local-date-dependent views.

        A full ``ReloadSkin`` invalidates every home widget and makes Kodi
        recreate network and RAW artwork. The service now refreshes only the
        active container after the GUI becomes idle.
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
            folder_path = (
                str(xbmc.getInfoLabel("Container.FolderPath") or "")
                if hasattr(xbmc, "getInfoLabel")
                else ""
            )
            if current_window != 10002 or not folder_path.startswith(
                "plugin://plugin.image.mypicsdb3"
            ):
                return True
            if hasattr(xbmc, "getCondVisibility") and any(
                xbmc.getCondVisibility(condition)
                for condition in (
                    "Container.IsUpdating",
                    "Player.HasMedia",
                    "System.HasActiveModalDialog",
                )
            ):
                return False
            xbmc.executebuiltin("Container.Refresh")
            return True

        if current_window != 10000:
            return False

        if hasattr(xbmc, "getCondVisibility"):
            unsafe_conditions = (
                "Container.IsUpdating",
                "Library.IsScanning",
                "Player.HasMedia",
                "System.HasActiveModalDialog",
                "System.ScreenSaverActive",
                "System.DPMSActive",
            )
            if any(xbmc.getCondVisibility(condition) for condition in unsafe_conditions):
                return False

        xbmc.executebuiltin("Container.Refresh")
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

    def music_playlist_fingerprint(self) -> str:
        """Fingerprint Kodi's current music queue without persisting its items."""

        try:
            result = self.execute_jsonrpc(
                "Playlist.GetItems",
                {
                    "playlistid": 0,
                    "properties": ["file"],
                    "limits": {"start": 0, "end": 5000},
                },
            )
            if not isinstance(result, dict):
                return ""
            items = result.get("items") or []
            files = [
                str(item.get("file") or "")
                for item in items
                if isinstance(item, dict)
            ]
            total = int((result.get("limits") or {}).get("total") or len(files))
            if total <= 0 or not any(files):
                return ""
            payload = json.dumps(
                {"total": total, "files": files},
                ensure_ascii=False,
                separators=(",", ":"),
            )
            return hashlib.sha256(payload.encode("utf-8")).hexdigest()
        except Exception as exc:
            self.log.warning("Could not fingerprint the music playlist: %s", exc)
            return ""

    def set_music_slideshow_session(
        self, token: str, playlist_fingerprint: str
    ) -> None:
        if xbmcgui is None:
            return
        try:
            payload = json.dumps(
                {
                    "version": 1,
                    "token": str(token or ""),
                    "playlist_fingerprint": str(playlist_fingerprint or ""),
                },
                separators=(",", ":"),
            )
            xbmcgui.Window(HOME_WINDOW_ID).setProperty(
                MUSIC_SLIDESHOW_PROPERTY, payload
            )
            self.log.debug("Music slideshow session published")
        except Exception as exc:
            self.log.warning("Could not publish music slideshow session: %s", exc)

    @staticmethod
    def music_slideshow_session() -> Dict[str, str]:
        if xbmcgui is None:
            return {}
        try:
            raw = xbmcgui.Window(HOME_WINDOW_ID).getProperty(
                MUSIC_SLIDESHOW_PROPERTY
            )
            payload = json.loads(str(raw or "{}"))
            if not isinstance(payload, dict) or int(payload.get("version") or 0) != 1:
                return {}
            token = str(payload.get("token") or "")
            if not token:
                return {}
            return {
                "token": token,
                "playlist_fingerprint": str(
                    payload.get("playlist_fingerprint") or ""
                ),
            }
        except Exception:
            return {}

    @staticmethod
    def clear_music_slideshow_session(token: str = "") -> None:
        if xbmcgui is None:
            return
        try:
            window = xbmcgui.Window(HOME_WINDOW_ID)
            if token:
                raw = window.getProperty(MUSIC_SLIDESHOW_PROPERTY)
                payload = json.loads(str(raw or "{}"))
                if str(payload.get("token") or "") != str(token):
                    return
            window.clearProperty(MUSIC_SLIDESHOW_PROPERTY)
        except Exception:
            return

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
        if xbmc is None:
            return False
        try:
            return bool(xbmc.Player().isPlaying())
        except Exception:
            return False

    @staticmethod
    def playing_file() -> str:
        if xbmc is None:
            return ""
        try:
            if hasattr(xbmc, "getCondVisibility") and not xbmc.getCondVisibility(
                "Player.HasMedia"
            ):
                return ""
            if hasattr(xbmc, "getInfoLabel"):
                return normalize_uri(
                    str(xbmc.getInfoLabel("Player.Filenameandpath") or "")
                )
            player = xbmc.Player()
            if not player.isPlaying():
                return ""
            return normalize_uri(str(player.getPlayingFile() or ""))
        except Exception:
            return ""

    @staticmethod
    def abort_monitor():
        return create_abort_monitor()
