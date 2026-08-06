from __future__ import annotations

from mypicsdb3.service_loop import (
    MUSIC_SLIDESHOW_END_IDLE_POLLS,
    MUSIC_SLIDESHOW_STARTUP_IDLE_POLLS,
    MusicSlideshowMonitor,
)


class FakeLog:
    def __init__(self):
        self.info_messages = []
        self.warnings = []

    def info(self, message, *args):
        self.info_messages.append(message % args if args else message)

    def warning(self, message, *args):
        self.warnings.append(message % args if args else message)


class FakeKodi:
    def __init__(self, player_states, fingerprints, token="session"):
        self.player_states = iter(player_states)
        self.fingerprints = iter(fingerprints)
        self.token = token
        self.cleared = []
        self.calls = []
        self.log = FakeLog()

    def music_slideshow_session(self):
        if not self.token:
            return {}
        return {"token": self.token, "playlist_fingerprint": "owned"}

    def execute_jsonrpc(self, method, params=None):
        self.calls.append((method, params))
        if method == "Player.GetActivePlayers":
            return next(self.player_states)
        if method == "Player.Stop":
            return "OK"
        raise AssertionError(method)

    def music_playlist_fingerprint(self):
        return next(self.fingerprints)

    def clear_music_slideshow_session(self, token=""):
        self.cleared.append(token)
        if not token or token == self.token:
            self.token = ""


def test_monitor_stops_owned_music_after_picture_slideshow_ends() -> None:
    kodi = FakeKodi(
        [[{"playerid": 2, "type": "picture"}]]
        + [[{"playerid": 0, "type": "audio"}]] * MUSIC_SLIDESHOW_END_IDLE_POLLS,
        ["owned"],
    )
    monitor = MusicSlideshowMonitor(kodi)

    for _ in range(1 + MUSIC_SLIDESHOW_END_IDLE_POLLS):
        monitor.tick()

    assert ("Player.Stop", {"playerid": 0}) in kodi.calls
    assert kodi.cleared == ["session"]


def test_monitor_leaves_replacement_music_playing() -> None:
    kodi = FakeKodi(
        [[{"playerid": 2, "type": "picture"}]]
        + [[{"playerid": 0, "type": "audio"}]] * MUSIC_SLIDESHOW_END_IDLE_POLLS,
        ["replacement"],
    )
    monitor = MusicSlideshowMonitor(kodi)

    for _ in range(1 + MUSIC_SLIDESHOW_END_IDLE_POLLS):
        monitor.tick()

    assert all(method != "Player.Stop" for method, _params in kodi.calls)
    assert kodi.cleared == ["session"]
    assert any("replacement audio" in message for message in kodi.log.info_messages)


def test_monitor_allows_native_slideshow_startup_grace() -> None:
    kodi = FakeKodi(
        [[{"playerid": 0, "type": "audio"}]]
        * MUSIC_SLIDESHOW_STARTUP_IDLE_POLLS,
        ["owned"],
    )
    monitor = MusicSlideshowMonitor(kodi)

    for _ in range(MUSIC_SLIDESHOW_STARTUP_IDLE_POLLS - 1):
        monitor.tick()

    assert kodi.cleared == []
    assert all(method != "Player.Stop" for method, _params in kodi.calls)

    monitor.tick()

    assert ("Player.Stop", {"playerid": 0}) in kodi.calls
    assert kodi.cleared == ["session"]
