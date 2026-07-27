from __future__ import annotations

import json
from typing import Iterable, List


PICTURE_PLAYLIST_ID = 2
PLAYLIST_ADD_BATCH_SIZE = 250


class SlideshowError(RuntimeError):
    pass


def _quote_builtin_argument(value: str) -> str:
    """Quote one Kodi built-in argument without changing the media URI."""

    return '"%s"' % str(value).replace("\\", "\\\\").replace('"', '\\"')


def _rpc(xbmc_module, method: str, params: dict) -> None:
    request = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": method,
        "params": params,
    }
    try:
        raw = xbmc_module.executeJSONRPC(json.dumps(request, ensure_ascii=False))
    except Exception as exc:
        raise SlideshowError("Kodi JSON-RPC call failed: %s" % method) from exc
    try:
        response = json.loads(raw or "{}")
    except (TypeError, ValueError) as exc:
        raise SlideshowError("Kodi returned an invalid JSON-RPC response") from exc
    if response.get("error"):
        raise SlideshowError(str(response["error"].get("message") or response["error"]))


def _playlist_items(uris: Iterable[str]) -> List[dict]:
    """Return unique, non-empty playlist items while preserving query order."""

    items: List[dict] = []
    seen = set()
    for uri in uris:
        value = str(uri or "")
        if not value.strip() or value in seen:
            continue
        seen.add(value)
        items.append({"file": value})
    return items


def _clear_picture_playlist_quietly(xbmc_module) -> None:
    try:
        _rpc(xbmc_module, "Playlist.Clear", {"playlistid": PICTURE_PLAYLIST_ID})
    except SlideshowError:
        pass


def start_mixed_slideshow(
    xbmc_module,
    uris: Iterable[str],
    start_position: int = 0,
) -> int:
    """Build and start one database-backed playlist from arbitrary folders.

    Large result sets are appended in bounded JSON-RPC requests. This avoids one
    oversized Playlist.Add payload while preserving catalogue order.
    """

    items = _playlist_items(uris)
    if not items:
        return 0
    position = max(0, min(int(start_position), len(items) - 1))
    _rpc(xbmc_module, "Playlist.Clear", {"playlistid": PICTURE_PLAYLIST_ID})
    try:
        for offset in range(0, len(items), PLAYLIST_ADD_BATCH_SIZE):
            _rpc(
                xbmc_module,
                "Playlist.Add",
                {
                    "playlistid": PICTURE_PLAYLIST_ID,
                    "item": items[offset : offset + PLAYLIST_ADD_BATCH_SIZE],
                },
            )
        _rpc(
            xbmc_module,
            "Player.Open",
            {"item": {"playlistid": PICTURE_PLAYLIST_ID, "position": position}},
        )
    except SlideshowError:
        _clear_picture_playlist_quietly(xbmc_module)
        raise
    return len(items)


def start_native_folder_slideshow(
    xbmc_module,
    folder_uri: str,
    *,
    recursive: bool = True,
) -> None:
    """Use Kodi's native folder slideshow for one indexed album tree.

    Kodi owns picture/video transitions for this path, which avoids the custom
    JSON-RPC playlist and background video monitor used for database result
    sets spanning arbitrary folders.
    """

    uri = str(folder_uri or "").strip()
    if not uri:
        raise SlideshowError("Folder URI is empty")
    arguments = [_quote_builtin_argument(uri)]
    if recursive:
        arguments.append("recursive")
    arguments.append("notrandom")
    xbmc_module.executebuiltin("SlideShow(%s)" % ",".join(arguments))
