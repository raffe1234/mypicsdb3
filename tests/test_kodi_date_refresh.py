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
