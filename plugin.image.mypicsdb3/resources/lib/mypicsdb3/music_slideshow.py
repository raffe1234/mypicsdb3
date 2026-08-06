from __future__ import annotations

from typing import Any

from .music_playlists import normalize_music_playlist_uri


class MusicSlideshowError(RuntimeError):
    """Raised when Kodi cannot load or start an assigned music playlist."""


def start_music_playlist(xbmc_module: Any, playlist_uri: str, logger=None) -> int:
    """Load one ordinary Kodi music playlist and start it from the beginning."""

    uri = normalize_music_playlist_uri(playlist_uri)
    try:
        playlist = xbmc_module.PlayList(xbmc_module.PLAYLIST_MUSIC)
        loaded = bool(playlist.load(uri))
    except Exception as exc:
        raise MusicSlideshowError("Kodi could not load the music playlist") from exc
    if not loaded:
        raise MusicSlideshowError("Kodi could not load the music playlist")
    try:
        count = int(playlist.size())
    except Exception as exc:
        raise MusicSlideshowError("Kodi could not read the music playlist") from exc
    if count <= 0:
        raise MusicSlideshowError("The music playlist is empty")
    try:
        xbmc_module.Player().play(playlist, startpos=0)
    except TypeError:
        # Older test doubles and Kodi-compatible shims may not expose keyword
        # arguments even though Kodi's Python API does.
        xbmc_module.Player().play(playlist)
    except Exception as exc:
        raise MusicSlideshowError("Kodi could not start the music playlist") from exc
    if logger:
        logger.info("Collection music playlist started: items=%d", count)
    return count


def stop_music_player(kodi_context, logger=None, active_players=None) -> bool:
    """Stop Kodi's active audio player and leave video/picture players alone.

    A caller that already queried active players may pass that snapshot. This
    avoids a second JSON-RPC poll in the service monitor and closes the race in
    which the audio player disappears or changes between detection and stop.
    """

    if active_players is None:
        result = kodi_context.execute_jsonrpc("Player.GetActivePlayers")
        players = result if isinstance(result, list) else []
    else:
        players = active_players if isinstance(active_players, list) else []
    stopped = False
    for player in players:
        if not isinstance(player, dict) or str(player.get("type") or "") != "audio":
            continue
        try:
            player_id = int(player.get("playerid", -1))
        except (TypeError, ValueError):
            continue
        if player_id < 0:
            continue
        kodi_context.execute_jsonrpc(
            "Player.Stop", {"playerid": player_id}
        )
        stopped = True
    if logger and stopped:
        logger.info("Collection slideshow music stopped")
    return stopped
