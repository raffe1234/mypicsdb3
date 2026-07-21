from __future__ import annotations

from typing import Callable, Optional

from .preferences import ALBUM_VIEW_MODE_BY_ID, ALBUM_VIEW_MODES


def detect_current_album_view_mode(xbmc_module, xbmcgui_module) -> Optional[int]:
    """Return the focused Estuary view control id when Kodi exposes it."""
    window_ids = []
    try:
        window_ids.append(int(xbmcgui_module.getCurrentWindowId()))
    except Exception:
        pass
    if 10002 not in window_ids:
        window_ids.append(10002)  # Pictures window

    for window_id in window_ids:
        try:
            focus_id = int(xbmcgui_module.Window(window_id).getFocusId())
        except Exception:
            continue
        if focus_id in ALBUM_VIEW_MODE_BY_ID and focus_id != 0:
            return focus_id

    try:
        view_name = str(xbmc_module.getInfoLabel("Container.Viewmode") or "")
    except Exception:
        view_name = ""
    compact_name = "".join(
        character for character in view_name.casefold() if character.isalnum()
    )
    return {
        "list": 50,
        "iconwall": 52,
        "shift": 53,
        "infowall": 54,
        "widelist": 55,
        "wall": 500,
    }.get(compact_name)


def save_current_album_view(
    kodi,
    localize: Callable[[int, str], str],
    xbmc_module=None,
    xbmcgui_module=None,
) -> Optional[int]:
    """Save the current album view, or ask the user when it cannot be detected."""
    if xbmc_module is None or xbmcgui_module is None:
        import xbmc as xbmc_module  # type: ignore
        import xbmcgui as xbmcgui_module  # type: ignore

    mode_id = detect_current_album_view_mode(xbmc_module, xbmcgui_module)
    if mode_id is None:
        selectable_modes = [mode for mode in ALBUM_VIEW_MODES if mode.mode_id != 0]
        selected_ids = [mode.mode_id for mode in selectable_modes]
        try:
            preselect = selected_ids.index(int(kodi.settings.album_view_mode))
        except (ValueError, TypeError):
            preselect = 0
        selected = xbmcgui_module.Dialog().select(
            localize(32215, "Save current view as album default"),
            [localize(mode.string_id, mode.fallback) for mode in selectable_modes],
            preselect=preselect,
        )
        if selected < 0:
            return None
        mode_id = selectable_modes[selected].mode_id

    kodi.addon.setSetting("album_view_mode", str(mode_id))
    kodi.refresh_settings()
    mode = ALBUM_VIEW_MODE_BY_ID[mode_id]
    kodi.notify(
        "%s: %s"
        % (
            localize(32216, "Album default view saved"),
            localize(mode.string_id, mode.fallback),
        )
    )
    return mode_id
