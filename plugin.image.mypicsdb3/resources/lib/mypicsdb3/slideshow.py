from __future__ import annotations

import json
from typing import Any, Iterable, List, Optional


PICTURE_PLAYLIST_ID = 2
PLAYLIST_ADD_BATCH_SIZE = 250
PICTURE_PLAYER_PROBE_POLLS = 20
PICTURE_PLAYER_PROBE_INTERVAL_MS = 100


class SlideshowError(RuntimeError):
    pass


class SlideshowPlayerMismatchError(SlideshowError):
    """Kodi opened a picture-playlist image with the video player."""


def _quote_builtin_argument(value: str) -> str:
    """Quote one Kodi built-in argument without changing the media URI."""

    return '"%s"' % str(value).replace("\\", "\\\\").replace('"', '\\"')


def _rpc(xbmc_module, method: str, params: Optional[dict] = None):
    request = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": method,
    }
    if params is not None:
        request["params"] = params
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
    return response.get("result")


def _sleep(xbmc_module, milliseconds: int) -> None:
    sleep = getattr(xbmc_module, "sleep", None)
    if callable(sleep):
        sleep(int(milliseconds))


def _same_media_uri(left: str, right: str) -> bool:
    def cleaned(value: str) -> str:
        return str(value or "").strip().replace("\\", "/").casefold()

    return cleaned(left) == cleaned(right)


def _stop_player_quietly(xbmc_module, player_id: int) -> None:
    try:
        _rpc(xbmc_module, "Player.Stop", {"playerid": int(player_id)})
    except SlideshowError:
        pass


def _verify_picture_playlist_player(
    xbmc_module,
    expected_picture_uri: str,
    logger: Optional[Any] = None,
) -> None:
    """Detect Kodi builds that route picture playlist 2 through VideoPlayer.

    Some Kodi installations accept the mixed picture playlist but open a JPEG
    as a one-frame MJPEG video. In that state every picture reaches EOF almost
    immediately. Only classify the route as incompatible when the active video
    player's item is the exact picture used as the startup probe.
    """

    for _attempt in range(PICTURE_PLAYER_PROBE_POLLS):
        try:
            players = _rpc(xbmc_module, "Player.GetActivePlayers")
        except SlideshowError:
            _sleep(xbmc_module, PICTURE_PLAYER_PROBE_INTERVAL_MS)
            continue
        if not isinstance(players, list):
            break
        for player in players:
            if not isinstance(player, dict):
                continue
            player_type = str(player.get("type") or "")
            player_id = int(player.get("playerid", -1))
            if player_type == "picture":
                if logger is not None:
                    logger.debug("Mixed slideshow picture-player probe succeeded")
                return
            if player_type != "video" or player_id < 0:
                continue
            try:
                item_result = _rpc(
                    xbmc_module,
                    "Player.GetItem",
                    {"playerid": player_id, "properties": ["file"]},
                )
            except SlideshowError:
                continue
            item = item_result.get("item", {}) if isinstance(item_result, dict) else {}
            playing_uri = str(item.get("file") or "") if isinstance(item, dict) else ""
            if _same_media_uri(playing_uri, expected_picture_uri):
                _stop_player_quietly(xbmc_module, player_id)
                _sleep(xbmc_module, PICTURE_PLAYER_PROBE_INTERVAL_MS)
                raise SlideshowPlayerMismatchError(
                    "Kodi opened the picture-playlist probe with VideoPlayer"
                )
        _sleep(xbmc_module, PICTURE_PLAYER_PROBE_INTERVAL_MS)

    if logger is not None:
        logger.debug("Mixed slideshow picture-player probe was inconclusive")


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
    logger: Optional[Any] = None,
    probe_picture_position: Optional[int] = None,
) -> int:
    """Build and start one database-backed playlist from arbitrary folders.

    Large result sets are appended in bounded JSON-RPC requests. This avoids one
    oversized Playlist.Add payload while preserving catalogue order.
    """

    items = _playlist_items(uris)
    if not items:
        if logger is not None:
            logger.debug("Mixed slideshow contains no playable media after cleanup")
        return 0
    position = max(0, min(int(start_position), len(items) - 1))
    probe_position = None
    if probe_picture_position is not None:
        probe_position = max(0, min(int(probe_picture_position), len(items) - 1))
    open_position = probe_position if probe_position is not None else position
    if logger is not None:
        logger.debug(
            "Mixed slideshow playlist: items=%d start_position=%d batch_size=%d",
            len(items),
            position,
            PLAYLIST_ADD_BATCH_SIZE,
        )
    _rpc(xbmc_module, "Playlist.Clear", {"playlistid": PICTURE_PLAYLIST_ID})
    try:
        batch_total = (len(items) + PLAYLIST_ADD_BATCH_SIZE - 1) // PLAYLIST_ADD_BATCH_SIZE
        for batch_index, offset in enumerate(
            range(0, len(items), PLAYLIST_ADD_BATCH_SIZE),
            start=1,
        ):
            batch = items[offset : offset + PLAYLIST_ADD_BATCH_SIZE]
            if logger is not None:
                logger.debug(
                    "Mixed slideshow Playlist.Add batch %d/%d: items=%d",
                    batch_index,
                    batch_total,
                    len(batch),
                )
            _rpc(
                xbmc_module,
                "Playlist.Add",
                {
                    "playlistid": PICTURE_PLAYLIST_ID,
                    "item": batch,
                },
            )
        if logger is not None:
            logger.debug("Mixed slideshow Player.Open: position=%d", open_position)
        _rpc(
            xbmc_module,
            "Player.Open",
            {"item": {"playlistid": PICTURE_PLAYLIST_ID, "position": open_position}},
        )
        if logger is not None:
            logger.debug("Mixed slideshow Player.Open accepted by Kodi")
        if probe_position is not None:
            _verify_picture_playlist_player(
                xbmc_module,
                str(items[probe_position]["file"]),
                logger=logger,
            )
            if position != probe_position:
                if logger is not None:
                    logger.debug(
                        "Mixed slideshow Player.Open requested start after probe: "
                        "position=%d",
                        position,
                    )
                _rpc(
                    xbmc_module,
                    "Player.Open",
                    {
                        "item": {
                            "playlistid": PICTURE_PLAYLIST_ID,
                            "position": position,
                        }
                    },
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
    logger: Optional[Any] = None,
) -> None:
    """Use Kodi's native folder slideshow for a picture-only album tree.

    Mixed album trees are routed through the explicit JSON-RPC playlist so
    video handling does not depend on platform-specific native slideshow
    behaviour.
    """

    uri = str(folder_uri or "").strip()
    if not uri:
        raise SlideshowError("Folder URI is empty")
    arguments = [_quote_builtin_argument(uri)]
    if recursive:
        arguments.append("recursive")
    arguments.append("notrandom")
    if logger is not None:
        logger.debug(
            "Native picture slideshow: recursive=%s",
            "true" if recursive else "false",
        )
    xbmc_module.executebuiltin("SlideShow(%s)" % ",".join(arguments))
