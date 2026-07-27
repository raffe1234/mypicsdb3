from __future__ import annotations

import re
from typing import Any, Callable

from .album_view import detect_current_album_view_mode


_VIEW_MODE_POLL_INTERVAL_MS = 50
_VIEW_MODE_TIMEOUT_MS = 2000
_VIEW_MODE_SETTLE_MS = 200
_VIEW_MODE_VERIFY_MS = 200
_VIEW_MODE_RETRY_MS = 200
_VIEW_MODE_MAX_ATTEMPTS = 3
_KODI_FORMATTING_TAG = re.compile(r"\[/?[A-Za-z]+(?:=[^\]]+)?\]")


def _normalized_label(value: Any) -> str:
    text = _KODI_FORMATTING_TAG.sub("", str(value or ""))
    return " ".join(text.split()).casefold()


def _container_matches(
    get_label: Callable[[str], Any],
    expected_category_key: str,
    expected_content_key: str,
) -> bool:
    try:
        category = _normalized_label(get_label("Container.PluginCategory"))
        content = str(get_label("Container.Content") or "").strip().casefold()
    except Exception:
        return False
    return category == expected_category_key and content == expected_content_key


def _execute_view_mode(execute: Callable[..., Any], command: str) -> None:
    """Run the built-in synchronously when Kodi exposes the blocking argument."""
    try:
        execute(command, True)
    except TypeError:
        # Test doubles and older compatibility shims may expose only the
        # one-argument form. Kodi itself supports the blocking flag.
        execute(command)


def set_view_mode_when_container_ready(
    xbmc_module,
    xbmcgui_module,
    view_mode: int,
    expected_category: str,
    expected_content: str,
    *,
    timeout_ms: int = _VIEW_MODE_TIMEOUT_MS,
    poll_interval_ms: int = _VIEW_MODE_POLL_INTERVAL_MS,
    settle_ms: int = _VIEW_MODE_SETTLE_MS,
    verify_ms: int = _VIEW_MODE_VERIFY_MS,
    retry_ms: int = _VIEW_MODE_RETRY_MS,
    max_attempts: int = _VIEW_MODE_MAX_ATTEMPTS,
) -> bool:
    """Apply and verify a Kodi view only on the requested picture container.

    ``endOfDirectory`` can return before Kodi has finished activating and
    restoring the path-specific view for the new directory. Category/content
    matching prevents touching the parent menu. After a short continuous settle
    period, apply the configured view synchronously and require the target view
    control to remain active. If Kodi performs a late path-view restore, retry
    while the same result container is still active.
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
    settle = max(0, int(settle_ms))
    verify = max(0, int(verify_ms))
    retry = max(0, int(retry_ms))
    attempts_limit = max(1, int(max_attempts))
    elapsed = 0
    matched_for = 0

    # First make sure the picture result, not its parent menu, owns the window
    # continuously long enough for Kodi's path-specific view restore to start.
    while True:
        if _container_matches(
            get_label,
            expected_category_key,
            expected_content_key,
        ):
            if matched_for >= settle:
                break
            matched_for += interval
        else:
            matched_for = 0

        if elapsed >= timeout or not callable(sleep):
            return False
        sleep(interval)
        elapsed += interval

    command = "Container.SetViewMode(%d)" % mode
    attempts = 0
    since_apply = retry
    target_for = 0

    while True:
        if not _container_matches(
            get_label,
            expected_category_key,
            expected_content_key,
        ):
            # The user navigated away. Never retry against another container.
            return attempts > 0

        current_mode = detect_current_album_view_mode(xbmc_module, xbmcgui_module)
        if current_mode == mode:
            if target_for >= verify:
                return True
            target_for += interval
        else:
            target_for = 0
            if since_apply >= retry and attempts < attempts_limit:
                _execute_view_mode(execute, command)
                attempts += 1
                since_apply = 0

        if elapsed >= timeout or not callable(sleep):
            return current_mode == mode
        sleep(interval)
        elapsed += interval
        since_apply += interval
