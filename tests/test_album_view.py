from __future__ import annotations

from types import SimpleNamespace

from mypicsdb3.album_view import detect_current_album_view_mode, save_current_album_view


class FakeWindow:
    def __init__(self, focus_id):
        self.focus_id = focus_id

    def getFocusId(self):
        return self.focus_id


class FakeDialog:
    def __init__(self, selected):
        self.selected = selected

    def select(self, heading, options, preselect=-1):
        return self.selected


def test_detect_current_album_view_uses_pictures_window_focus() -> None:
    xbmc = SimpleNamespace(getInfoLabel=lambda _label: "")
    xbmcgui = SimpleNamespace(
        getCurrentWindowId=lambda: 10106,
        Window=lambda window_id: FakeWindow(55 if window_id == 10002 else 999),
    )

    assert detect_current_album_view_mode(xbmc, xbmcgui) == 55


def test_save_album_view_offers_choice_when_detection_fails() -> None:
    settings = {}
    notifications = []
    kodi = SimpleNamespace(
        addon=SimpleNamespace(setSetting=lambda key, value: settings.__setitem__(key, value)),
        settings=SimpleNamespace(album_view_mode=55),
        refresh_settings=lambda: None,
        notify=lambda message: notifications.append(message),
    )
    xbmc = SimpleNamespace(getInfoLabel=lambda _label: "Unknown")
    xbmcgui = SimpleNamespace(
        getCurrentWindowId=lambda: 10106,
        Window=lambda _window_id: FakeWindow(999),
        Dialog=lambda: FakeDialog(5),
    )

    saved = save_current_album_view(
        kodi,
        lambda _string_id, fallback: fallback,
        xbmc,
        xbmcgui,
    )

    assert saved == 500
    assert settings["album_view_mode"] == "500"
    assert notifications[-1] == "Album default view saved: Wall"
