from __future__ import annotations

import os
from typing import Any


MUSIC_TARGET_SMART = "smart"
MUSIC_TARGET_MANUAL = "manual"
MUSIC_TARGET_TYPES = frozenset((MUSIC_TARGET_SMART, MUSIC_TARGET_MANUAL))
MUSIC_PLAYLIST_MASK = ".m3u|.m3u8|.pls|.b4s|.wpl"
KODI_MUSIC_PLAYLIST_DIRECTORY = "special://profile/playlists/music/"
MAX_MUSIC_PLAYLIST_URI_LENGTH = 4096


class MusicPlaylistValidationError(ValueError):
    """Raised when a collection music-playlist mapping is invalid."""


def normalize_music_target_type(value: Any) -> str:
    target_type = str(value or "").strip().lower()
    if target_type not in MUSIC_TARGET_TYPES:
        raise MusicPlaylistValidationError("Collection type is invalid")
    return target_type


def normalize_music_playlist_uri(value: Any) -> str:
    if not isinstance(value, str):
        raise MusicPlaylistValidationError("Music playlist path must be text")
    uri = value.strip()
    if not uri:
        raise MusicPlaylistValidationError("Music playlist path must not be empty")
    if len(uri) > MAX_MUSIC_PLAYLIST_URI_LENGTH:
        raise MusicPlaylistValidationError(
            "Music playlist path must contain at most %d characters"
            % MAX_MUSIC_PLAYLIST_URI_LENGTH
        )
    return uri


def music_playlist_label(uri: Any) -> str:
    value = str(uri or "").strip()
    if not value:
        return ""
    normalized = value.replace("\\", "/").rstrip("/")
    return os.path.basename(normalized) or value
