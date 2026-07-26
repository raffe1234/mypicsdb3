from __future__ import annotations

from mypicsdb3.service_loop import MixedSlideshowVideoMonitor, VIDEO_IDLE_CLEAR_POLLS


class FakeLog:
    def __init__(self):
        self.info_messages = []
        self.warnings = []

    def info(self, message, *args):
        self.info_messages.append(message % args if args else message)

    def warning(self, message, *args):
        self.warnings.append(message % args if args else message)


class FakeKodi:
    def __init__(self, player_states, playing_file="nfs://nas/photos/clip.mp4"):
        self.player_states = iter(player_states)
        self.current_players = []
        self.current_file = playing_file
        self.calls = []
        self.log = FakeLog()

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


def test_monitor_does_not_advance_after_standalone_video() -> None:
    kodi = FakeKodi(
        [[{"playerid": 1, "type": "video"}]]
        + [[] for _ in range(VIDEO_IDLE_CLEAR_POLLS)]
    )
    monitor = MixedSlideshowVideoMonitor(kodi, FakeCatalog())

    for _ in range(VIDEO_IDLE_CLEAR_POLLS + 1):
        monitor.tick()

    assert all(method != "Player.GoTo" for method, _params in kodi.calls)
    assert monitor.active_video_uri == ""


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
