from __future__ import annotations

import json

from mypicsdb3.slideshow import PICTURE_PLAYLIST_ID, start_mixed_slideshow


class FakeXbmc:
    def __init__(self):
        self.requests = []

    def executeJSONRPC(self, payload):
        self.requests.append(json.loads(payload))
        return json.dumps({"jsonrpc": "2.0", "id": 1, "result": "OK"})


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
