from __future__ import annotations

import json

import pytest

from mypicsdb3.slideshow import (
    PICTURE_PLAYLIST_ID,
    PLAYLIST_ADD_BATCH_SIZE,
    SlideshowError,
    SlideshowPlayerMismatchError,
    start_mixed_slideshow,
    start_native_folder_slideshow,
)


class FakeLogger:
    def __init__(self):
        self.messages = []

    def debug(self, message, *args):
        self.messages.append(message % args if args else message)


class FakeXbmc:
    def __init__(self):
        self.requests = []
        self.builtins = []

    def executeJSONRPC(self, payload):
        self.requests.append(json.loads(payload))
        return json.dumps({"jsonrpc": "2.0", "id": 1, "result": "OK"})

    def executebuiltin(self, command):
        self.builtins.append(command)

    def sleep(self, milliseconds):
        pass


def test_mixed_slideshow_uses_picture_playlist_and_start_position() -> None:
    xbmc = FakeXbmc()

    count = start_mixed_slideshow(
        xbmc,
        ["/photos/a.jpg", "/photos/clip.mp4", ""],
        start_position=1,
    )

    assert count == 2
    assert [request["method"] for request in xbmc.requests] == [
        "Playlist.Clear",
        "Playlist.Add",
        "Player.Open",
    ]
    assert xbmc.requests[0]["params"] == {"playlistid": PICTURE_PLAYLIST_ID}
    assert xbmc.requests[1]["params"]["item"] == [
        {"file": "/photos/a.jpg"},
        {"file": "/photos/clip.mp4"},
    ]
    assert xbmc.requests[2]["params"]["item"] == {
        "playlistid": PICTURE_PLAYLIST_ID,
        "position": 1,
    }


def test_mixed_slideshow_drops_empty_and_duplicate_uris() -> None:
    xbmc = FakeXbmc()

    count = start_mixed_slideshow(
        xbmc,
        ["/photos/a.jpg", "", "/photos/a.jpg", "/other/b.jpg"],
        start_position=1,
    )

    assert count == 2
    assert xbmc.requests[1]["params"]["item"] == [
        {"file": "/photos/a.jpg"},
        {"file": "/other/b.jpg"},
    ]
    assert xbmc.requests[2]["params"]["item"]["position"] == 1


def test_large_mixed_slideshow_is_added_in_bounded_batches() -> None:
    xbmc = FakeXbmc()
    uris = ["/album-%04d/image.jpg" % index for index in range(PLAYLIST_ADD_BATCH_SIZE + 1)]

    count = start_mixed_slideshow(
        xbmc,
        uris,
        start_position=PLAYLIST_ADD_BATCH_SIZE,
    )

    assert count == PLAYLIST_ADD_BATCH_SIZE + 1
    assert [request["method"] for request in xbmc.requests] == [
        "Playlist.Clear",
        "Playlist.Add",
        "Playlist.Add",
        "Player.Open",
    ]
    assert len(xbmc.requests[1]["params"]["item"]) == PLAYLIST_ADD_BATCH_SIZE
    assert xbmc.requests[2]["params"]["item"] == [
        {"file": "/album-%04d/image.jpg" % PLAYLIST_ADD_BATCH_SIZE}
    ]
    assert xbmc.requests[3]["params"]["item"]["position"] == PLAYLIST_ADD_BATCH_SIZE


def test_failed_playlist_batch_clears_partial_playlist() -> None:
    class FailingXbmc(FakeXbmc):
        def __init__(self):
            super().__init__()
            self.add_calls = 0

        def executeJSONRPC(self, payload):
            request = json.loads(payload)
            self.requests.append(request)
            if request["method"] == "Playlist.Add":
                self.add_calls += 1
                if self.add_calls == 2:
                    return json.dumps(
                        {
                            "jsonrpc": "2.0",
                            "id": 1,
                            "error": {"code": -1, "message": "add failed"},
                        }
                    )
            return json.dumps({"jsonrpc": "2.0", "id": 1, "result": "OK"})

    xbmc = FailingXbmc()
    uris = ["/album-%04d/image.jpg" % index for index in range(PLAYLIST_ADD_BATCH_SIZE + 1)]

    with pytest.raises(SlideshowError, match="add failed"):
        start_mixed_slideshow(xbmc, uris)

    assert [request["method"] for request in xbmc.requests] == [
        "Playlist.Clear",
        "Playlist.Add",
        "Playlist.Add",
        "Playlist.Clear",
    ]


def test_jsonrpc_transport_failure_is_reported_as_slideshow_error() -> None:
    class BrokenXbmc(FakeXbmc):
        def executeJSONRPC(self, payload):
            request = json.loads(payload)
            self.requests.append(request)
            raise RuntimeError("Kodi is shutting down")

    with pytest.raises(SlideshowError, match="Playlist.Clear"):
        start_mixed_slideshow(BrokenXbmc(), ["/photos/a.jpg"])


def test_native_folder_slideshow_uses_kodi_recursive_slideshow() -> None:
    xbmc = FakeXbmc()

    start_native_folder_slideshow(
        xbmc,
        "smb://nas/Pictures/Trip, summer/",
        recursive=True,
    )

    assert xbmc.builtins == [
        'SlideShow("smb://nas/Pictures/Trip, summer/",recursive,notrandom)'
    ]


def test_mixed_slideshow_emits_opt_in_batch_diagnostics() -> None:
    xbmc = FakeXbmc()
    logger = FakeLogger()

    start_mixed_slideshow(
        xbmc,
        ["/photos/a.jpg", "/photos/clip.mp4"],
        start_position=1,
        logger=logger,
    )

    assert logger.messages == [
        "Mixed slideshow playlist: items=2 start_position=1 batch_size=250",
        "Mixed slideshow Playlist.Add batch 1/1: items=2",
        "Mixed slideshow Player.Open: position=1",
        "Mixed slideshow Player.Open accepted by Kodi",
    ]


def test_mixed_slideshow_probes_picture_player_before_requested_video_start() -> None:
    class PicturePlayerXbmc(FakeXbmc):
        def executeJSONRPC(self, payload):
            request = json.loads(payload)
            self.requests.append(request)
            if request["method"] == "Player.GetActivePlayers":
                result = [{"playerid": 2, "type": "picture"}]
            else:
                result = "OK"
            return json.dumps({"jsonrpc": "2.0", "id": 1, "result": result})

    xbmc = PicturePlayerXbmc()

    count = start_mixed_slideshow(
        xbmc,
        ["/photos/a.jpg", "/photos/clip.mp4"],
        start_position=1,
        probe_picture_position=0,
    )

    assert count == 2
    assert [request["method"] for request in xbmc.requests] == [
        "Playlist.Clear",
        "Playlist.Add",
        "Player.Open",
        "Player.GetActivePlayers",
        "Player.Open",
    ]
    open_positions = [
        request["params"]["item"]["position"]
        for request in xbmc.requests
        if request["method"] == "Player.Open"
    ]
    assert open_positions == [0, 1]


def test_mixed_slideshow_rejects_picture_opened_by_video_player() -> None:
    class VideoPlayerXbmc(FakeXbmc):
        def __init__(self):
            super().__init__()
            self.sleeps = []

        def executeJSONRPC(self, payload):
            request = json.loads(payload)
            self.requests.append(request)
            method = request["method"]
            if method == "Player.GetActivePlayers":
                result = [{"playerid": 1, "type": "video"}]
            elif method == "Player.GetItem":
                result = {"item": {"file": "/photos/a.jpg"}}
            else:
                result = "OK"
            return json.dumps({"jsonrpc": "2.0", "id": 1, "result": result})

        def sleep(self, milliseconds):
            self.sleeps.append(milliseconds)

    xbmc = VideoPlayerXbmc()

    with pytest.raises(
        SlideshowPlayerMismatchError,
        match="picture-playlist probe",
    ):
        start_mixed_slideshow(
            xbmc,
            ["/photos/a.jpg", "/photos/clip.mp4"],
            probe_picture_position=0,
        )

    assert [request["method"] for request in xbmc.requests] == [
        "Playlist.Clear",
        "Playlist.Add",
        "Player.Open",
        "Player.GetActivePlayers",
        "Player.GetItem",
        "Player.Stop",
        "Playlist.Clear",
    ]
    assert xbmc.sleeps == [100]


def test_native_slideshow_emits_opt_in_route_diagnostic() -> None:
    xbmc = FakeXbmc()
    logger = FakeLogger()

    start_native_folder_slideshow(
        xbmc,
        "/photos/album/",
        recursive=True,
        logger=logger,
    )

    assert logger.messages == ["Native picture slideshow: recursive=true"]
