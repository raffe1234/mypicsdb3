from __future__ import annotations

import types

import pytest

from mypicsdb3.music_slideshow import MusicSlideshowError, start_music_playlist


class FakePlaylist:
    def __init__(self, loaded=True, size=2, load_error=None):
        self.loaded = loaded
        self.item_count = size
        self.load_error = load_error
        self.loaded_uri = ""

    def load(self, uri):
        if self.load_error:
            raise self.load_error
        self.loaded_uri = uri
        return self.loaded

    def size(self):
        return self.item_count


class FakePlayer:
    def __init__(self, error=None):
        self.calls = []
        self.error = error

    def play(self, playlist, startpos=0):
        if self.error:
            raise self.error
        self.calls.append((playlist, startpos))


def fake_xbmc(playlist, player):
    return types.SimpleNamespace(
        PLAYLIST_MUSIC=0,
        PlayList=lambda playlist_id: playlist,
        Player=lambda: player,
    )


def test_music_playlist_is_loaded_and_started_from_beginning() -> None:
    playlist = FakePlaylist(size=3)
    player = FakePlayer()

    count = start_music_playlist(
        fake_xbmc(playlist, player), "special://music/family.m3u"
    )

    assert count == 3
    assert playlist.loaded_uri == "special://music/family.m3u"
    assert player.calls == [(playlist, 0)]


@pytest.mark.parametrize(
    "playlist, expected",
    [
        (FakePlaylist(loaded=False), "could not load"),
        (FakePlaylist(size=0), "empty"),
        (FakePlaylist(load_error=OSError("offline")), "could not load"),
    ],
)
def test_invalid_or_unavailable_playlist_fails_safely(playlist, expected) -> None:
    with pytest.raises(MusicSlideshowError, match=expected):
        start_music_playlist(fake_xbmc(playlist, FakePlayer()), "music.m3u")


def test_player_failure_is_reported() -> None:
    with pytest.raises(MusicSlideshowError, match="could not start"):
        start_music_playlist(
            fake_xbmc(FakePlaylist(), FakePlayer(error=RuntimeError("busy"))),
            "music.m3u",
        )
