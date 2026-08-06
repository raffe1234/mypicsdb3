from __future__ import annotations

import pytest

from mypicsdb3.music_playlists import (
    MAX_MUSIC_PLAYLIST_URI_LENGTH,
    MUSIC_TARGET_MANUAL,
    MUSIC_TARGET_SMART,
    MusicPlaylistValidationError,
    music_playlist_label,
    normalize_music_playlist_uri,
    normalize_music_target_type,
)


def test_music_target_type_is_normalized() -> None:
    assert normalize_music_target_type(" SMART ") == MUSIC_TARGET_SMART
    assert normalize_music_target_type("manual") == MUSIC_TARGET_MANUAL


@pytest.mark.parametrize("value", [None, "", "album", 7])
def test_invalid_music_target_type_is_rejected(value) -> None:
    with pytest.raises(MusicPlaylistValidationError):
        normalize_music_target_type(value)


def test_music_playlist_uri_is_trimmed_and_bounded() -> None:
    assert normalize_music_playlist_uri("  special://music/family.m3u  ") == (
        "special://music/family.m3u"
    )
    with pytest.raises(MusicPlaylistValidationError):
        normalize_music_playlist_uri(123)
    with pytest.raises(MusicPlaylistValidationError):
        normalize_music_playlist_uri("   ")
    with pytest.raises(MusicPlaylistValidationError):
        normalize_music_playlist_uri("x" * (MAX_MUSIC_PLAYLIST_URI_LENGTH + 1))


def test_music_playlist_label_supports_kodi_and_windows_paths() -> None:
    assert music_playlist_label("special://music/family.m3u") == "family.m3u"
    assert music_playlist_label(r"C:\\Music\\holiday.pls") == "holiday.pls"
    assert music_playlist_label("") == ""
