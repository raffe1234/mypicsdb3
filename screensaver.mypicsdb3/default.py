from __future__ import annotations

import os
import random
import sys
import time

import xbmc
import xbmcaddon
import xbmcgui
import xbmcvfs


PLUGIN_ID = "plugin.image.mypicsdb3"
SCREENSAVER_ID = "screensaver.mypicsdb3"


def _translate(path: str) -> str:
    if hasattr(xbmcvfs, "translatePath"):
        return xbmcvfs.translatePath(path)
    return xbmc.translatePath(path)


def _load_core():
    plugin = xbmcaddon.Addon(PLUGIN_ID)
    plugin_path = _translate(plugin.getAddonInfo("path"))
    library_path = os.path.join(plugin_path, "resources", "lib")
    if library_path not in sys.path:
        sys.path.insert(0, library_path)
    from mypicsdb3.screensaver import (  # pylint: disable=import-outside-toplevel
        SCREEN_SOURCE_MANUAL,
        SCREEN_SOURCE_SMART,
        ScreensaverReadOnlyProvider,
        ScreensaverSourceError,
        normalize_item_limit,
        normalize_slide_seconds,
        plugin_settings_from_addon,
    )

    return {
        "plugin": plugin,
        "manual": SCREEN_SOURCE_MANUAL,
        "smart": SCREEN_SOURCE_SMART,
        "provider": ScreensaverReadOnlyProvider,
        "error": ScreensaverSourceError,
        "normalize_limit": normalize_item_limit,
        "normalize_seconds": normalize_slide_seconds,
        "plugin_settings": plugin_settings_from_addon,
    }


def _logger(message: str, level=xbmc.LOGINFO) -> None:
    xbmc.log("[MyPicsDB 3 Screensaver] %s" % message, level)


def _provider(core):
    plugin = core["plugin"]
    profile = _translate(plugin.getAddonInfo("profile"))
    settings = core["plugin_settings"](plugin, profile)
    return core["provider"](settings, logger=None)


def _choose_source(core, addon) -> None:
    try:
        sources = _provider(core).list_sources()
    except core["error"] as exc:
        xbmcgui.Dialog().ok("MyPicsDB 3 Screensaver", str(exc))
        return
    if not sources:
        xbmcgui.Dialog().ok(
            "MyPicsDB 3 Screensaver",
            "Create a manual collection or save a smart collection in MyPicsDB 3 first.",
        )
        return
    labels = []
    for source in sources:
        prefix = "Manual" if source.source_type == core["manual"] else "Smart"
        labels.append("%s: %s" % (prefix, source.name))
    selected = xbmcgui.Dialog().select("Choose MyPicsDB collection", labels)
    if selected < 0:
        return
    source = sources[selected]
    addon.setSetting("source_type", source.source_type)
    addon.setSetting("source_id", str(source.source_id))
    addon.setSetting("source_name", source.name)
    xbmcgui.Dialog().notification(
        "MyPicsDB 3 Screensaver",
        "Selected: %s" % source.name,
        xbmcgui.NOTIFICATION_INFO,
        3000,
    )


def _clear_source(addon) -> None:
    addon.setSetting("source_type", "")
    addon.setSetting("source_id", "")
    addon.setSetting("source_name", "")
    xbmcgui.Dialog().notification(
        "MyPicsDB 3 Screensaver",
        "Collection selection cleared",
        xbmcgui.NOTIFICATION_INFO,
        2500,
    )


class _ExitMonitor(xbmc.Monitor):
    def __init__(self):
        super().__init__()
        self.deactivated = False

    def onScreensaverDeactivated(self):  # noqa: N802 - Kodi callback name
        self.deactivated = True


class _ScreensaverWindow(xbmcgui.WindowDialog):
    def __init__(self):
        super().__init__()
        self.exit_requested = False

    def onAction(self, action):  # noqa: N802 - Kodi callback name
        self.exit_requested = True
        self.close()


def _show_fallback(message: str, seconds: int = 10) -> None:
    monitor = _ExitMonitor()
    window = _ScreensaverWindow()
    width = max(1, int(xbmcgui.getScreenWidth()))
    height = max(1, int(xbmcgui.getScreenHeight()))
    label = xbmcgui.ControlLabel(
        int(width * 0.1),
        int(height * 0.42),
        int(width * 0.8),
        int(height * 0.16),
        message,
        alignment=0x00000002 | 0x00000004,
    )
    window.addControl(label)
    window.show()
    try:
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            if monitor.abortRequested() or monitor.deactivated or window.exit_requested:
                break
            if monitor.waitForAbort(0.2):
                break
    finally:
        window.close()


def _run_screensaver(core, addon) -> None:
    source_type = addon.getSetting("source_type")
    source_id = addon.getSetting("source_id")
    if not source_type or not source_id:
        _show_fallback(
            "Choose a MyPicsDB collection in this screensaver's settings."
        )
        return

    limit = core["normalize_limit"](addon.getSetting("max_items"))
    seconds = core["normalize_seconds"](addon.getSetting("slide_seconds"))
    randomize = addon.getSetting("randomize").strip().lower() not in {
        "false",
        "0",
        "no",
        "off",
    }
    show_filename = addon.getSetting("show_filename").strip().lower() in {
        "true",
        "1",
        "yes",
        "on",
    }

    try:
        pictures = _provider(core).pictures(
            source_type,
            int(source_id),
            limit=limit,
            randomize=randomize,
        )
    except (ValueError, core["error"]) as exc:
        _logger(str(exc), xbmc.LOGWARNING)
        _show_fallback("MyPicsDB 3 Screensaver: %s" % exc)
        return
    if not pictures:
        _show_fallback("The selected MyPicsDB collection has no available pictures.")
        return

    monitor = _ExitMonitor()
    window = _ScreensaverWindow()
    width = max(1, int(xbmcgui.getScreenWidth()))
    height = max(1, int(xbmcgui.getScreenHeight()))
    image = xbmcgui.ControlImage(0, 0, width, height, "", aspectRatio=2)
    window.addControl(image)
    caption = None
    if show_filename:
        caption = xbmcgui.ControlLabel(
            int(width * 0.03),
            int(height * 0.91),
            int(width * 0.94),
            int(height * 0.06),
            "",
            textColor="0xFFE6E6E6",
            shadowColor="0xCC000000",
        )
        window.addControl(caption)
    window.show()
    _logger(
        "Started source_type=%s source_id=%s pictures=%d random=%s"
        % (source_type, source_id, len(pictures), str(randomize).lower())
    )

    try:
        index = 0
        while not monitor.abortRequested() and not monitor.deactivated:
            if window.exit_requested:
                break
            picture = pictures[index]
            image.setImage(picture.uri, True)
            if caption is not None:
                caption.setLabel(picture.filename)
            deadline = time.monotonic() + seconds
            while time.monotonic() < deadline:
                if monitor.abortRequested() or monitor.deactivated or window.exit_requested:
                    return
                if monitor.waitForAbort(min(0.2, max(0.01, deadline - time.monotonic()))):
                    return
            index += 1
            if index >= len(pictures):
                index = 0
                if randomize and len(pictures) > 1:
                    random.shuffle(pictures)
    finally:
        window.close()
        _logger("Stopped")


def main(argv=None) -> None:
    args = list(sys.argv[1:] if argv is None else argv)
    addon = xbmcaddon.Addon(SCREENSAVER_ID)
    try:
        core = _load_core()
    except Exception as exc:
        _logger("Could not load MyPicsDB 3 core: %s" % exc, xbmc.LOGERROR)
        _show_fallback("MyPicsDB 3 is unavailable.")
        return
    if args and args[0] == "choose-source":
        _choose_source(core, addon)
        return
    if args and args[0] == "clear-source":
        _clear_source(addon)
        return
    _run_screensaver(core, addon)


if __name__ == "__main__":
    main()
