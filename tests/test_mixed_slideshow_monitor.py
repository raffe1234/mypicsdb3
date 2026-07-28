from __future__ import annotations

from mypicsdb3.service_loop import (
    MIXED_SLIDESHOW_STARTUP_IDLE_POLLS,
    MixedSlideshowVideoMonitor,
    VIDEO_IDLE_CLEAR_POLLS,
)


class FakeLog:
    def __init__(self):
        self.debug_messages = []
        self.info_messages = []
        self.warnings = []

    def debug(self, message, *args):
        self.debug_messages.append(message % args if args else message)

    def info(self, message, *args):
        self.info_messages.append(message % args if args else message)

    def warning(self, message, *args):
        self.warnings.append(message % args if args else message)


class FakeKodi:
    def __init__(
        self,
        player_states,
        playing_file="nfs://nas/photos/clip.mp4",
        active=True,
    ):
        self.player_states = iter(player_states)
        self.current_players = []
        self.current_file = playing_file
        self.calls = []
        self.log = FakeLog()
        self.active = active
        self.state_updates = []

    def mixed_slideshow_active(self):
        return self.active

    def set_mixed_slideshow_active(self, active):
        self.active = bool(active)
        self.state_updates.append(bool(active))

    def execute_jsonrpc(self, method, params=None):
        self.calls.append((method, params))
        if method == "Player.GetActivePlayers":
            self.current_players = next(self.player_states)
            return self.current_players
        if method == "Player.GoTo":
            return "OK"
        raise AssertionError(method)

    def playing_file(self):
        return self.current_file


class FakeCatalog:
    def __init__(self, media_type="video"):
        self.media_type = media_type
        self.lookups = []

    def media_type_for_uri(self, uri):
        self.lookups.append(uri)
        return self.media_type


def test_inactive_monitor_does_not_poll_kodi() -> None:
    kodi = FakeKodi([], active=False)
    monitor = MixedSlideshowVideoMonitor(kodi, FakeCatalog())

    monitor.tick()

    assert kodi.calls == []


def test_monitor_advances_picture_playlist_when_indexed_video_finishes() -> None:
    kodi = FakeKodi(
        [
            [{"playerid": 1, "type": "video"}],
            [{"playerid": 2, "type": "picture"}],
        ]
    )
    catalog = FakeCatalog()
    monitor = MixedSlideshowVideoMonitor(kodi, catalog)

    monitor.tick()
    monitor.tick()

    assert catalog.lookups == ["nfs://nas/photos/clip.mp4"]
    assert ("Player.GoTo", {"playerid": 2, "to": "next"}) in kodi.calls
    assert monitor.active_video_uri == ""
    assert kodi.active is True
    assert kodi.log.info_messages == [
        "Advanced mixed slideshow after indexed video finished"
    ]
    assert all("nfs://" not in message for message in kodi.log.info_messages)


def test_monitor_clears_session_after_player_stops() -> None:
    kodi = FakeKodi(
        [[{"playerid": 1, "type": "video"}]]
        + [[] for _ in range(VIDEO_IDLE_CLEAR_POLLS)]
    )
    monitor = MixedSlideshowVideoMonitor(kodi, FakeCatalog())

    for _ in range(VIDEO_IDLE_CLEAR_POLLS + 1):
        monitor.tick()

    assert all(method != "Player.GoTo" for method, _params in kodi.calls)
    assert monitor.active_video_uri == ""
    assert kodi.active is False
    assert kodi.state_updates == [False]


def test_monitor_allows_player_startup_grace_period() -> None:
    kodi = FakeKodi([[] for _ in range(MIXED_SLIDESHOW_STARTUP_IDLE_POLLS)])
    monitor = MixedSlideshowVideoMonitor(kodi, FakeCatalog())

    for _ in range(MIXED_SLIDESHOW_STARTUP_IDLE_POLLS - 1):
        monitor.tick()

    assert kodi.active is True

    monitor.tick()

    assert kodi.active is False
    assert kodi.state_updates == [False]


def test_monitor_ignores_unindexed_video() -> None:
    kodi = FakeKodi(
        [
            [{"playerid": 1, "type": "video"}],
            [{"playerid": 2, "type": "picture"}],
        ]
    )
    monitor = MixedSlideshowVideoMonitor(kodi, FakeCatalog(media_type=None))

    monitor.tick()
    monitor.tick()

    assert all(method != "Player.GoTo" for method, _params in kodi.calls)
