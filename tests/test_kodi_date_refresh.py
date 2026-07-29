from __future__ import annotations

import types

import pytest

from mypicsdb3 import kodi


def fake_xbmc(commands, *, blocked=()):
    blocked = set(blocked)
    return types.SimpleNamespace(
        getSkinDir=lambda: "skin.estuary.mypicsdb3",
        getCondVisibility=lambda condition: condition in blocked,
        executebuiltin=commands.append,
    )


def test_custom_estuary_home_reloads_skin_when_idle(monkeypatch) -> None:
    commands = []
    monkeypatch.setattr(kodi, "xbmc", fake_xbmc(commands))
    monkeypatch.setattr(
        kodi,
        "xbmcgui",
        types.SimpleNamespace(getCurrentWindowId=lambda: 10000),
    )

    refreshed = kodi.KodiContext.refresh_date_sensitive_views()

    assert refreshed is True
    assert commands == ["ReloadSkin()"]


@pytest.mark.parametrize(
    "condition",
    (
        "Library.IsScanning",
        "Player.HasMedia",
        "System.HasActiveModalDialog",
        "System.ScreenSaverActive",
        "System.DPMSActive",
    ),
)
def test_custom_estuary_home_defers_reload_while_gui_is_busy(
    monkeypatch,
    condition,
) -> None:
    commands = []
    monkeypatch.setattr(kodi, "xbmc", fake_xbmc(commands, blocked=(condition,)))
    monkeypatch.setattr(
        kodi,
        "xbmcgui",
        types.SimpleNamespace(getCurrentWindowId=lambda: 10000),
    )

    refreshed = kodi.KodiContext.refresh_date_sensitive_views()

    assert refreshed is False
    assert commands == []


def test_custom_estuary_defers_reload_until_home_is_active(monkeypatch) -> None:
    commands = []
    monkeypatch.setattr(kodi, "xbmc", fake_xbmc(commands))
    monkeypatch.setattr(
        kodi,
        "xbmcgui",
        types.SimpleNamespace(getCurrentWindowId=lambda: 10002),
    )

    refreshed = kodi.KodiContext.refresh_date_sensitive_views()

    assert refreshed is False
    assert commands == []


def test_other_skin_refreshes_current_container(monkeypatch) -> None:
    commands = []
    fake = types.SimpleNamespace(
        getSkinDir=lambda: "skin.estuary",
        executebuiltin=commands.append,
    )
    monkeypatch.setattr(kodi, "xbmc", fake)
    monkeypatch.setattr(
        kodi,
        "xbmcgui",
        types.SimpleNamespace(getCurrentWindowId=lambda: 10002),
    )

    refreshed = kodi.KodiContext.refresh_date_sensitive_views()

    assert refreshed is True
    assert commands == ["Container.Refresh"]


def test_picture_addons_virtual_source_is_not_returned() -> None:
    context = kodi.KodiContext.__new__(kodi.KodiContext)
    context.execute_jsonrpc = lambda method, params: {
        "sources": [
            {"label": "Photos", "file": "smb://server/photos/"},
            {"label": "Picture add-ons", "file": "addons://sources/image/"},
        ]
    }

    assert context.kodi_picture_sources() == [
        {"label": "Photos", "uri": "smb://server/photos/"},
    ]


def test_mixed_slideshow_state_uses_home_window_property(monkeypatch) -> None:
    properties = {}

    class FakeWindow:
        def setProperty(self, key, value):
            properties[key] = value

        def getProperty(self, key):
            return properties.get(key, "")

        def clearProperty(self, key):
            properties.pop(key, None)

    monkeypatch.setattr(
        kodi,
        "xbmcgui",
        types.SimpleNamespace(Window=lambda window_id: FakeWindow()),
    )
    context = kodi.KodiContext.__new__(kodi.KodiContext)
    context.log = types.SimpleNamespace(warning=lambda *args: None)

    context.set_mixed_slideshow_active(True)

    assert kodi.KodiContext.mixed_slideshow_active() is True
    assert properties[kodi.MIXED_SLIDESHOW_PROPERTY] == "true"

    context.set_mixed_slideshow_active(False)

    assert kodi.KodiContext.mixed_slideshow_active() is False
    assert kodi.MIXED_SLIDESHOW_PROPERTY not in properties


def test_picture_playlist_compatibility_uses_home_window_property(monkeypatch) -> None:
    properties = {}

    class FakeWindow:
        def setProperty(self, key, value):
            properties[key] = value

        def getProperty(self, key):
            return properties.get(key, "")

        def clearProperty(self, key):
            properties.pop(key, None)

    monkeypatch.setattr(
        kodi,
        "xbmcgui",
        types.SimpleNamespace(Window=lambda window_id: FakeWindow()),
    )
    context = kodi.KodiContext.__new__(kodi.KodiContext)
    context.log = types.SimpleNamespace(
        warning=lambda *args: None,
        debug=lambda *args: None,
    )

    assert kodi.KodiContext.picture_playlist_compatibility() is None

    context.set_picture_playlist_compatibility(True)
    assert kodi.KodiContext.picture_playlist_compatibility() is True
    assert properties[kodi.PICTURE_PLAYLIST_COMPATIBILITY_PROPERTY] == "compatible"

    context.set_picture_playlist_compatibility(False)
    assert kodi.KodiContext.picture_playlist_compatibility() is False
    assert properties[kodi.PICTURE_PLAYLIST_COMPATIBILITY_PROPERTY] == "incompatible"

    context.set_picture_playlist_compatibility(None)
    assert kodi.KodiContext.picture_playlist_compatibility() is None

def test_random_refresh_reloads_custom_estuary_and_current_container(monkeypatch) -> None:
    commands = []
    monkeypatch.setattr(kodi, "xbmc", fake_xbmc(commands))

    kodi.KodiContext.refresh_random_views()

    assert commands == ["Container.Refresh", "ReloadSkin()"]


def test_random_refresh_only_refreshes_container_for_other_skins(monkeypatch) -> None:
    commands = []
    monkeypatch.setattr(
        kodi,
        "xbmc",
        types.SimpleNamespace(
            getSkinDir=lambda: "skin.estuary",
            executebuiltin=commands.append,
        ),
    )

    kodi.KodiContext.refresh_random_views()

    assert commands == ["Container.Refresh"]
