from __future__ import annotations

import re
from typing import Any


_VIEW_MODE_POLL_INTERVAL_MS = 50
_VIEW_MODE_TIMEOUT_MS = 1000
_KODI_FORMATTING_TAG = re.compile(r"\[/?[A-Za-z]+(?:=[^\]]+)?\]")


def _normalized_label(value: Any) -> str:
    text = _KODI_FORMATTING_TAG.sub("", str(value or ""))
    return " ".join(text.split()).casefold()


def set_view_mode_when_container_ready(
    xbmc_module,
    view_mode: int,
    expected_category: str,
    expected_content: str,
    *,
    timeout_ms: int = _VIEW_MODE_TIMEOUT_MS,
    poll_interval_ms: int = _VIEW_MODE_POLL_INTERVAL_MS,
) -> bool:
    """Set a Kodi view mode only after the requested directory owns the window.

    Kodi can return from ``endOfDirectory`` while the previous directory is
    still the active container. Sending ``Container.SetViewMode`` immediately
    can therefore change the parent menu instead of the picture result. Wait
    for both the plug-in category and content type to match before applying the
    configured album view. A timeout is safer than touching an unrelated view.
    """
    try:
        mode = int(view_mode)
    except (TypeError, ValueError):
        return False
    if mode <= 0 or not expected_category or not expected_content:
        return False

    get_label = getattr(xbmc_module, "getInfoLabel", None)
    execute = getattr(xbmc_module, "executebuiltin", None)
    sleep = getattr(xbmc_module, "sleep", None)
    if not callable(get_label) or not callable(execute):
        return False

    expected_category_key = _normalized_label(expected_category)
    expected_content_key = str(expected_content).strip().casefold()
    interval = max(1, int(poll_interval_ms))
    timeout = max(0, int(timeout_ms))
    elapsed = 0

    while True:
        try:
            category = _normalized_label(get_label("Container.PluginCategory"))
            content = str(get_label("Container.Content") or "").strip().casefold()
        except Exception:
            return False

        if category == expected_category_key and content == expected_content_key:
            execute("Container.SetViewMode(%d)" % mode)
            return True

        if elapsed >= timeout or not callable(sleep):
            return False
        sleep(interval)
        elapsed += interval
