from __future__ import annotations

import json
from typing import Iterable


PICTURE_PLAYLIST_ID = 2


class SlideshowError(RuntimeError):
    pass


def _rpc(xbmc_module, method: str, params: dict) -> None:
    request = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": method,
        "params": params,
    }
    raw = xbmc_module.executeJSONRPC(json.dumps(request, ensure_ascii=False))
    try:
        response = json.loads(raw or "{}")
    except (TypeError, ValueError) as exc:
        raise SlideshowError("Kodi returned an invalid JSON-RPC response") from exc
    if response.get("error"):
        raise SlideshowError(str(response["error"].get("message") or response["error"]))


def start_mixed_slideshow(
    xbmc_module,
    uris: Iterable[str],
    start_position: int = 0,
) -> int:
    items = [{"file": str(uri)} for uri in uris if str(uri or "").strip()]
    if not items:
        return 0
    position = max(0, min(int(start_position), len(items) - 1))
    _rpc(xbmc_module, "Playlist.Clear", {"playlistid": PICTURE_PLAYLIST_ID})
    _rpc(
        xbmc_module,
        "Playlist.Add",
        {"playlistid": PICTURE_PLAYLIST_ID, "item": items},
    )
    _rpc(
        xbmc_module,
        "Player.Open",
        {"item": {"playlistid": PICTURE_PLAYLIST_ID, "position": position}},
    )
    return len(items)
