from __future__ import annotations

import re
from typing import Any, Callable, Optional, Tuple

from .album_view import detect_current_album_view_mode


_PICTURES_WINDOW_ID = 10002
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


def _current_window_id(xbmcgui_module) -> Optional[int]:
    try:
        return int(xbmcgui_module.getCurrentWindowId())
    except Exception:
        return None


def _condition_is_true(xbmc_module, condition: str) -> bool:
    get_condition = getattr(xbmc_module, "getCondVisibility", None)
    if not callable(get_condition):
        return False
    try:
        return bool(get_condition(condition))
    except Exception:
        return False


def _container_matches(
    xbmc_module,
    xbmcgui_module,
    get_label: Callable[[str], Any],
    expected_category_key: str,
    expected_content_key: str,
) -> bool:
    # Container labels can remain populated behind dialogs, the picture player
    # and other windows. Only change a view while Pictures is the active window.
    if _current_window_id(xbmcgui_module) != _PICTURES_WINDOW_ID:
        return False
    if _condition_is_true(xbmc_module, "System.HasActiveModalDialog"):
        return False
    if _condition_is_true(xbmc_module, "Container.IsUpdating"):
        return False
    try:
        category = _normalized_label(get_label("Container.PluginCategory"))
        content = str(get_label("Container.Content") or "").strip().casefold()
    except Exception:
        return False
    return category == expected_category_key and content == expected_content_key


def _container_labels(get_label: Callable[[str], Any]) -> Tuple[str, str]:
    try:
        category = str(get_label("Container.PluginCategory") or "")
    except Exception:
        category = ""
    try:
        content = str(get_label("Container.Content") or "")
    except Exception:
        content = ""
    return category, content


def _execute_view_mode(execute: Callable[..., Any], command: str) -> None:
    """Run the built-in synchronously when Kodi exposes the blocking argument."""
    try:
        execute(command, True)
    except TypeError:
        # Test doubles and older compatibility shims may expose only the
        # one-argument form. Kodi itself supports the blocking flag.
        execute(command)


def _debug(logger: Optional[Any], message: str, *args: Any) -> None:
    if logger is not None:
        logger.debug(message, *args)


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
    logger: Optional[Any] = None,
) -> bool:
    """Apply and verify a Kodi view only on a stable Pictures container.

    ``endOfDirectory`` can return before Kodi has finished activating and
    restoring the path-specific view for the new directory. Category/content
    matching prevents touching the parent menu. The active window, modal-dialog
    state and container-update state are also checked so stale labels behind the
    picture player or another window cannot trigger ``Container.SetViewMode``.
    Empty result lists are filtered by the caller. If Kodi performs a late
    path-view restore, retry while the same stable result container is active.
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

    _debug(
        logger,
        "Album view request: target=%d category=%r content=%r",
        mode,
        expected_category,
        expected_content,
    )

    # First make sure the picture result, not its parent menu or a stale
    # container behind another window, owns the GUI continuously long enough
    # for Kodi's path-specific view restore to finish.
    while True:
        if _container_matches(
            xbmc_module,
            xbmcgui_module,
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
            category, content = _container_labels(get_label)
            _debug(
                logger,
                "Album view skipped before apply: target=%d window=%r category=%r content=%r",
                mode,
                _current_window_id(xbmcgui_module),
                category,
                content,
            )
            return False
        sleep(interval)
        elapsed += interval

    command = "Container.SetViewMode(%d)" % mode
    attempts = 0
    since_apply = retry
    target_for = 0

    while True:
        if not _container_matches(
            xbmc_module,
            xbmcgui_module,
            get_label,
            expected_category_key,
            expected_content_key,
        ):
            # The user navigated away, a modal opened or another window became
            # active. Never retry against a stale Pictures container.
            _debug(
                logger,
                "Album view retries cancelled: target=%d attempts=%d window=%r",
                mode,
                attempts,
                _current_window_id(xbmcgui_module),
            )
            return attempts > 0

        current_mode = detect_current_album_view_mode(xbmc_module, xbmcgui_module)
        if current_mode == mode:
            if target_for >= verify:
                _debug(
                    logger,
                    "Album view active: target=%d attempts=%d category=%r",
                    mode,
                    attempts,
                    expected_category,
                )
                return True
            target_for += interval
        else:
            target_for = 0
            if since_apply >= retry and attempts < attempts_limit:
                _debug(
                    logger,
                    "Album view apply: target=%d current=%r attempt=%d/%d",
                    mode,
                    current_mode,
                    attempts + 1,
                    attempts_limit,
                )
                _execute_view_mode(execute, command)
                attempts += 1
                since_apply = 0

        if elapsed >= timeout or not callable(sleep):
            _debug(
                logger,
                "Album view verification ended: target=%d current=%r attempts=%d",
                mode,
                current_mode,
                attempts,
            )
            return current_mode == mode
        sleep(interval)
        elapsed += interval
        since_apply += interval
