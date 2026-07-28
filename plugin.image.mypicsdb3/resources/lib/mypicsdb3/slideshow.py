from __future__ import annotations

import json
from typing import Any, Iterable, List, Optional


VIDEO_PLAYLIST_ID = 1
PICTURE_PLAYLIST_ID = 2
PLAYLIST_ADD_BATCH_SIZE = 250
PICTURE_PLAYER_PROBE_POLLS = 30
PICTURE_PLAYER_PROBE_INTERVAL_MS = 100
PICTURE_PLAYER_CONFIRM_POLLS = 2


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


def stop_active_media_players(xbmc_module, logger: Optional[Any] = None) -> None:
    """Stop an existing picture/video player before a new slideshow starts."""

    try:
        players = _rpc(xbmc_module, "Player.GetActivePlayers")
    except SlideshowError:
        return
    if not isinstance(players, list):
        return
    stopped = 0
    for player in players:
        if not isinstance(player, dict):
            continue
        player_type = str(player.get("type") or "")
        player_id = int(player.get("playerid", -1))
        if player_type not in {"picture", "video"} or player_id < 0:
            continue
        _stop_player_quietly(xbmc_module, player_id)
        stopped += 1
    if stopped and logger is not None:
        logger.debug("Stopped %d active media player(s) before slideshow start", stopped)


def _player_item_uri(xbmc_module, player_id: int) -> str:
    try:
        item_result = _rpc(
            xbmc_module,
            "Player.GetItem",
            {"playerid": int(player_id), "properties": ["file"]},
        )
    except SlideshowError:
        return ""
    item = item_result.get("item", {}) if isinstance(item_result, dict) else {}
    return str(item.get("file") or "") if isinstance(item, dict) else ""


def _stop_matching_players(xbmc_module, expected_uri: str) -> None:
    try:
        players = _rpc(xbmc_module, "Player.GetActivePlayers")
    except SlideshowError:
        return
    if not isinstance(players, list):
        return
    for player in players:
        if not isinstance(player, dict):
            continue
        player_type = str(player.get("type") or "")
        player_id = int(player.get("playerid", -1))
        if player_type not in {"picture", "video"} or player_id < 0:
            continue
        if _same_media_uri(_player_item_uri(xbmc_module, player_id), expected_uri):
            _stop_player_quietly(xbmc_module, player_id)


def _verify_picture_playlist_player(
    xbmc_module,
    expected_picture_uri: str,
    logger: Optional[Any] = None,
) -> None:
    """Detect Kodi builds that route picture playlist 2 through VideoPlayer.

    A stale native slideshow can leave a picture player active while the new
    playlist opens its JPEG through VideoPlayer. Therefore the probe must match
    the exact expected URI, inspect every active player before deciding, and
    give an exact video-player match precedence over a picture-player match.
    """

    confirmed_picture_polls = 0
    for _attempt in range(PICTURE_PLAYER_PROBE_POLLS):
        try:
            players = _rpc(xbmc_module, "Player.GetActivePlayers")
        except SlideshowError:
            confirmed_picture_polls = 0
            _sleep(xbmc_module, PICTURE_PLAYER_PROBE_INTERVAL_MS)
            continue
        if not isinstance(players, list):
            break

        exact_picture_player = False
        exact_video_player_id = -1
        for player in players:
            if not isinstance(player, dict):
                continue
            player_type = str(player.get("type") or "")
            player_id = int(player.get("playerid", -1))
            if player_type not in {"picture", "video"} or player_id < 0:
                continue
            playing_uri = _player_item_uri(xbmc_module, player_id)
            if not _same_media_uri(playing_uri, expected_picture_uri):
                continue
            if player_type == "video":
                exact_video_player_id = player_id
            elif player_type == "picture":
                exact_picture_player = True

        if exact_video_player_id >= 0:
            raise SlideshowPlayerMismatchError(
                "Kodi opened the picture-playlist probe with VideoPlayer"
            )

        if exact_picture_player:
            confirmed_picture_polls += 1
            if confirmed_picture_polls >= PICTURE_PLAYER_CONFIRM_POLLS:
                if logger is not None:
                    logger.debug(
                        "Mixed slideshow picture-player probe succeeded for expected item"
                    )
                return
        else:
            confirmed_picture_polls = 0
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


def _clear_playlist_quietly(xbmc_module, playlist_id: int) -> None:
    try:
        _rpc(xbmc_module, "Playlist.Clear", {"playlistid": int(playlist_id)})
    except SlideshowError:
        pass


def _add_playlist_items(
    xbmc_module,
    playlist_id: int,
    items: List[dict],
    logger: Optional[Any],
    label: str,
) -> None:
    batch_total = (len(items) + PLAYLIST_ADD_BATCH_SIZE - 1) // PLAYLIST_ADD_BATCH_SIZE
    for batch_index, offset in enumerate(
        range(0, len(items), PLAYLIST_ADD_BATCH_SIZE),
        start=1,
    ):
        batch = items[offset : offset + PLAYLIST_ADD_BATCH_SIZE]
        if logger is not None:
            logger.debug(
                "%s Playlist.Add batch %d/%d: items=%d",
                label,
                batch_index,
                batch_total,
                len(batch),
            )
        _rpc(
            xbmc_module,
            "Playlist.Add",
            {"playlistid": int(playlist_id), "item": batch},
        )


def _probe_mixed_picture_playlist(
    xbmc_module,
    expected_picture_uri: str,
    video_uri: str,
    logger: Optional[Any] = None,
) -> None:
    """Probe a minimal picture/video list before building the full playlist.

    Kodi 21 on Windows can play a one-picture playlist correctly but route the
    same picture through VideoPlayer as soon as the picture playlist also
    contains video. The compatibility probe must therefore include both media
    types to exercise the route used by a real mixed slideshow.
    """

    probe_item = [
        {"file": str(expected_picture_uri)},
        {"file": str(video_uri)},
    ]
    _rpc(xbmc_module, "Playlist.Clear", {"playlistid": PICTURE_PLAYLIST_ID})
    try:
        _rpc(
            xbmc_module,
            "Playlist.Add",
            {"playlistid": PICTURE_PLAYLIST_ID, "item": probe_item},
        )
        if logger is not None:
            logger.debug("Mixed slideshow compatibility probe Player.Open")
        _rpc(
            xbmc_module,
            "Player.Open",
            {"item": {"playlistid": PICTURE_PLAYLIST_ID, "position": 0}},
        )
        _verify_picture_playlist_player(
            xbmc_module,
            str(expected_picture_uri),
            logger=logger,
        )
    finally:
        _stop_matching_players(xbmc_module, str(expected_picture_uri))
        _clear_playlist_quietly(xbmc_module, PICTURE_PLAYLIST_ID)


def start_mixed_slideshow(
    xbmc_module,
    uris: Iterable[str],
    start_position: int = 0,
    logger: Optional[Any] = None,
    probe_picture_position: Optional[int] = None,
    probe_video_position: Optional[int] = None,
    verify_picture_position: Optional[int] = None,
) -> int:
    """Build and start one database-backed picture playlist.

    When picture and video positions are supplied, a minimal mixed playlist is
    probed before the full playlist is constructed. This avoids spending
    minutes adding a large playlist on Kodi installations that only fail when
    picture playlist 2 contains both media types.
    """

    items = _playlist_items(uris)
    if not items:
        if logger is not None:
            logger.debug("Mixed slideshow contains no playable media after cleanup")
        return 0
    position = max(0, min(int(start_position), len(items) - 1))
    if probe_picture_position is not None and probe_video_position is not None:
        picture_position = max(
            0, min(int(probe_picture_position), len(items) - 1)
        )
        video_position = max(0, min(int(probe_video_position), len(items) - 1))
        _probe_mixed_picture_playlist(
            xbmc_module,
            str(items[picture_position]["file"]),
            str(items[video_position]["file"]),
            logger=logger,
        )

    if logger is not None:
        logger.debug(
            "Mixed slideshow playlist: items=%d start_position=%d batch_size=%d",
            len(items),
            position,
            PLAYLIST_ADD_BATCH_SIZE,
        )
    _rpc(xbmc_module, "Playlist.Clear", {"playlistid": PICTURE_PLAYLIST_ID})
    try:
        _add_playlist_items(
            xbmc_module,
            PICTURE_PLAYLIST_ID,
            items,
            logger,
            "Mixed slideshow",
        )
        if logger is not None:
            logger.debug("Mixed slideshow Player.Open: position=%d", position)
        _rpc(
            xbmc_module,
            "Player.Open",
            {"item": {"playlistid": PICTURE_PLAYLIST_ID, "position": position}},
        )
        if logger is not None:
            logger.debug("Mixed slideshow Player.Open accepted by Kodi")
        if verify_picture_position is not None:
            verify_position = max(
                0, min(int(verify_picture_position), len(items) - 1)
            )
            _verify_picture_playlist_player(
                xbmc_module,
                str(items[verify_position]["file"]),
                logger=logger,
            )
            if logger is not None:
                logger.debug(
                    "Mixed slideshow full-playlist picture verification succeeded"
                )
    except SlideshowError:
        _clear_playlist_quietly(xbmc_module, PICTURE_PLAYLIST_ID)
        raise
    return len(items)


def start_video_playlist(
    xbmc_module,
    uris: Iterable[str],
    start_position: int = 0,
    logger: Optional[Any] = None,
) -> int:
    """Start a video-only result through Kodi's video playlist."""

    items = _playlist_items(uris)
    if not items:
        return 0
    position = max(0, min(int(start_position), len(items) - 1))
    if logger is not None:
        logger.debug(
            "Video playlist: items=%d start_position=%d batch_size=%d",
            len(items),
            position,
            PLAYLIST_ADD_BATCH_SIZE,
        )
    _rpc(xbmc_module, "Playlist.Clear", {"playlistid": VIDEO_PLAYLIST_ID})
    try:
        _add_playlist_items(
            xbmc_module,
            VIDEO_PLAYLIST_ID,
            items,
            logger,
            "Video playlist",
        )
        _rpc(
            xbmc_module,
            "Player.Open",
            {"item": {"playlistid": VIDEO_PLAYLIST_ID, "position": position}},
        )
    except SlideshowError:
        _clear_playlist_quietly(xbmc_module, VIDEO_PLAYLIST_ID)
        raise
    return len(items)


def start_native_folder_slideshow(
    xbmc_module,
    folder_uri: str,
    *,
    recursive: bool = True,
    logger: Optional[Any] = None,
) -> None:
    """Use Kodi's native folder slideshow for an album tree."""

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
