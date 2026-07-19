from __future__ import annotations

import types

from mypicsdb3 import kodi


def test_custom_estuary_home_reloads_skin(monkeypatch) -> None:
    commands = []
    fake_xbmc = types.SimpleNamespace(
        getSkinDir=lambda: "skin.estuary.mypicsdb3",
        executebuiltin=commands.append,
    )
    fake_xbmcgui = types.SimpleNamespace(getCurrentWindowId=lambda: 10000)
    monkeypatch.setattr(kodi, "xbmc", fake_xbmc)
    monkeypatch.setattr(kodi, "xbmcgui", fake_xbmcgui)

    kodi.KodiContext.refresh_date_sensitive_views()

    assert commands == ["ReloadSkin()"]


def test_other_windows_refresh_current_container(monkeypatch) -> None:
    commands = []
    fake_xbmc = types.SimpleNamespace(
        getSkinDir=lambda: "skin.estuary.mypicsdb3",
        executebuiltin=commands.append,
    )
    fake_xbmcgui = types.SimpleNamespace(getCurrentWindowId=lambda: 10002)
    monkeypatch.setattr(kodi, "xbmc", fake_xbmc)
    monkeypatch.setattr(kodi, "xbmcgui", fake_xbmcgui)

    kodi.KodiContext.refresh_date_sensitive_views()

    assert commands == ["Container.Refresh"]
