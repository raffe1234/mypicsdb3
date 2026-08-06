from __future__ import annotations

import types

from mypicsdb3 import kodi


class FakeWindow:
    def __init__(self):
        self.properties = {}

    def getProperty(self, key):
        return self.properties.get(key, "")

    def setProperty(self, key, value):
        self.properties[key] = value

    def clearProperty(self, key):
        self.properties.pop(key, None)


class FakeLogger:
    def __init__(self):
        self.debug_messages = []
        self.info_messages = []
        self.warning_messages = []

    def debug(self, message, *args):
        self.debug_messages.append(message % args if args else message)

    def info(self, message, *args):
        self.info_messages.append(message % args if args else message)

    def warning(self, message, *args):
        self.warning_messages.append(message % args if args else message)


def context_with_window(monkeypatch, window):
    monkeypatch.setattr(kodi, "xbmcgui", types.SimpleNamespace(Window=lambda _id: window))
    context = object.__new__(kodi.KodiContext)
    context.log = FakeLogger()
    return context


def test_slideshow_start_guard_blocks_parallel_start(monkeypatch):
    window = FakeWindow()
    context = context_with_window(monkeypatch, window)
    monkeypatch.setattr(kodi.time, "time", lambda: 1000.0)
    tokens = iter((types.SimpleNamespace(hex="first"), types.SimpleNamespace(hex="second")))
    monkeypatch.setattr(kodi.uuid, "uuid4", lambda: next(tokens))

    first = context.acquire_slideshow_start()
    second = context.acquire_slideshow_start()

    assert first == "first"
    assert second is None
    assert context.log.info_messages == [
        "Slideshow start ignored: another slideshow is being prepared"
    ]

    context.release_slideshow_start(first)
    assert window.getProperty(kodi.SLIDESHOW_START_PROPERTY) == ""


def test_slideshow_start_guard_replaces_stale_owner(monkeypatch):
    window = FakeWindow()
    window.setProperty(kodi.SLIDESHOW_START_PROPERTY, "old|100.0")
    context = context_with_window(monkeypatch, window)
    monkeypatch.setattr(kodi.time, "time", lambda: 1000.0)
    monkeypatch.setattr(kodi.uuid, "uuid4", lambda: types.SimpleNamespace(hex="new"))

    assert context.acquire_slideshow_start() == "new"
    assert window.getProperty(kodi.SLIDESHOW_START_PROPERTY).startswith("new|")


def test_slideshow_start_guard_only_releases_its_own_token(monkeypatch):
    window = FakeWindow()
    window.setProperty(kodi.SLIDESHOW_START_PROPERTY, "newer|1000.0")
    context = context_with_window(monkeypatch, window)

    context.release_slideshow_start("older")

    assert window.getProperty(kodi.SLIDESHOW_START_PROPERTY) == "newer|1000.0"


def test_music_slideshow_session_roundtrip_and_owner_safe_clear(monkeypatch):
    window = FakeWindow()
    context = context_with_window(monkeypatch, window)

    context.set_music_slideshow_session("owner", "fingerprint")

    assert context.music_slideshow_session() == {
        "token": "owner",
        "playlist_fingerprint": "fingerprint",
    }
    context.clear_music_slideshow_session("newer")
    assert context.music_slideshow_session()["token"] == "owner"
    context.clear_music_slideshow_session("owner")
    assert context.music_slideshow_session() == {}


def test_music_playlist_fingerprint_uses_order_and_total(monkeypatch):
    window = FakeWindow()
    context = context_with_window(monkeypatch, window)
    calls = []

    def execute_jsonrpc(method, params=None):
        calls.append((method, params))
        return {
            "items": [
                {"file": "smb://nas/music/one.flac"},
                {"file": "smb://nas/music/two.flac"},
            ],
            "limits": {"total": 2},
        }

    context.execute_jsonrpc = execute_jsonrpc

    first = context.music_playlist_fingerprint()
    second = context.music_playlist_fingerprint()

    assert first
    assert first == second
    assert calls[0][0] == "Playlist.GetItems"
    assert calls[0][1]["playlistid"] == 0


def test_empty_music_playlist_has_no_fingerprint(monkeypatch):
    window = FakeWindow()
    context = context_with_window(monkeypatch, window)
    context.execute_jsonrpc = lambda _method, _params=None: {
        "items": [],
        "limits": {"total": 0},
    }

    assert context.music_playlist_fingerprint() == ""
