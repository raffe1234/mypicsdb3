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


def test_custom_estuary_home_refreshes_container_when_idle(monkeypatch) -> None:
    commands = []
    monkeypatch.setattr(kodi, "xbmc", fake_xbmc(commands))
    monkeypatch.setattr(
        kodi,
        "xbmcgui",
        types.SimpleNamespace(getCurrentWindowId=lambda: 10000),
    )

    refreshed = kodi.KodiContext.refresh_date_sensitive_views()

    assert refreshed is True
    assert commands == ["Container.Refresh"]


@pytest.mark.parametrize(
    "condition",
    (
        "Container.IsUpdating",
        "Library.IsScanning",
        "Player.HasMedia",
        "System.HasActiveModalDialog",
        "System.ScreenSaverActive",
        "System.DPMSActive",
    ),
)
def test_custom_estuary_home_defers_refresh_while_gui_is_busy(
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


def test_custom_estuary_defers_refresh_until_home_is_active(monkeypatch) -> None:
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


def test_other_skin_refreshes_current_mypicsdb_container(monkeypatch) -> None:
    commands = []
    fake = types.SimpleNamespace(
        getSkinDir=lambda: "skin.estuary",
        getInfoLabel=lambda label: (
            "plugin://plugin.image.mypicsdb3/recent-taken"
            if label == "Container.FolderPath"
            else ""
        ),
        getCondVisibility=lambda _condition: False,
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

    assert commands == [
        "Container.Refresh",
        "ClearProperty(listposition,home)",
        "ReloadSkin()",
    ]


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


def test_other_skin_does_not_refresh_unrelated_container(monkeypatch) -> None:
    commands = []
    fake = types.SimpleNamespace(
        getSkinDir=lambda: "skin.estuary",
        getInfoLabel=lambda _label: "pvr://channels/tv/",
        getCondVisibility=lambda _condition: False,
        executebuiltin=commands.append,
    )
    monkeypatch.setattr(kodi, "xbmc", fake)
    monkeypatch.setattr(
        kodi,
        "xbmcgui",
        types.SimpleNamespace(getCurrentWindowId=lambda: 10002),
    )

    assert kodi.KodiContext.refresh_date_sensitive_views() is True
    assert commands == []


def test_other_skin_defers_mypicsdb_refresh_while_container_updates(monkeypatch) -> None:
    commands = []
    fake = types.SimpleNamespace(
        getSkinDir=lambda: "skin.estuary",
        getInfoLabel=lambda _label: "plugin://plugin.image.mypicsdb3/recent-taken",
        getCondVisibility=lambda condition: condition == "Container.IsUpdating",
        executebuiltin=commands.append,
    )
    monkeypatch.setattr(kodi, "xbmc", fake)
    monkeypatch.setattr(
        kodi,
        "xbmcgui",
        types.SimpleNamespace(getCurrentWindowId=lambda: 10002),
    )

    assert kodi.KodiContext.refresh_date_sensitive_views() is False
    assert commands == []


def test_is_playing_returns_false_when_kodi_player_raises(monkeypatch) -> None:
    class BrokenPlayer:
        def isPlaying(self):
            raise RuntimeError("player unavailable")

    monkeypatch.setattr(
        kodi,
        "xbmc",
        types.SimpleNamespace(Player=lambda: BrokenPlayer()),
    )

    assert kodi.KodiContext.is_playing() is False


def test_notification_failure_is_logged_instead_of_escaping(monkeypatch) -> None:
    class BrokenDialog:
        def notification(self, *_args):
            raise RuntimeError("GUI shutting down")

    warnings = []
    monkeypatch.setattr(
        kodi,
        "xbmcgui",
        types.SimpleNamespace(
            NOTIFICATION_ERROR="error",
            NOTIFICATION_INFO="info",
            Dialog=lambda: BrokenDialog(),
        ),
    )
    context = kodi.KodiContext.__new__(kodi.KodiContext)
    context.settings = types.SimpleNamespace(show_notifications=True)
    context.name = "MyPicsDB 3"
    context.log = types.SimpleNamespace(
        warning=lambda message, *args: warnings.append(
            message % args if args else message
        )
    )

    context.notify("Done")

    assert warnings == ["Could not show notification: GUI shutting down"]


def test_playing_file_skips_info_label_when_kodi_has_no_media(monkeypatch) -> None:
    calls = []
    monkeypatch.setattr(
        kodi,
        "xbmc",
        types.SimpleNamespace(
            getCondVisibility=lambda condition: condition == "Player.HasMedia" and False,
            getInfoLabel=lambda label: calls.append(label) or "unexpected",
        ),
    )

    assert kodi.KodiContext.playing_file() == ""
    assert calls == []


def test_playing_file_uses_info_label_without_querying_player(monkeypatch) -> None:
    class UnexpectedPlayer:
        def __init__(self):
            raise AssertionError("Player() should not be used when getInfoLabel exists")

    monkeypatch.setattr(
        kodi,
        "xbmc",
        types.SimpleNamespace(
            getInfoLabel=lambda label: (
                "smb://nas/photos/clip 01.mp4"
                if label == "Player.Filenameandpath"
                else ""
            ),
            Player=UnexpectedPlayer,
        ),
    )

    assert kodi.KodiContext.playing_file() == "smb://nas/photos/clip 01.mp4"


def test_home_widget_invalidation_increments_home_window_generation(monkeypatch) -> None:
    properties = {}

    class FakeWindow:
        def getProperty(self, key):
            return properties.get(key, "")

        def setProperty(self, key, value):
            properties[key] = value

    monkeypatch.setattr(
        kodi,
        "xbmcgui",
        types.SimpleNamespace(Window=lambda window_id: FakeWindow()),
    )
    context = kodi.KodiContext.__new__(kodi.KodiContext)
    context.settings = types.SimpleNamespace(home_widget_limit=39)
    context.log = types.SimpleNamespace(
        debug=lambda *args: None,
        warning=lambda *args: None,
    )

    assert context.invalidate_home_widgets("test") == 1
    assert context.invalidate_home_widgets("test") == 2
    assert properties[kodi.HOME_WIDGET_GENERATION_PROPERTY] == "2"
    assert properties[kodi.HOME_WIDGET_LIMIT_PROPERTY] == "39"


def test_random_home_widget_invalidation_uses_separate_generation(monkeypatch) -> None:
    properties = {}

    class FakeWindow:
        def getProperty(self, key):
            return properties.get(key, "")

        def setProperty(self, key, value):
            properties[key] = value

    monkeypatch.setattr(
        kodi,
        "xbmcgui",
        types.SimpleNamespace(Window=lambda window_id: FakeWindow()),
    )
    context = kodi.KodiContext.__new__(kodi.KodiContext)
    context.log = types.SimpleNamespace(
        debug=lambda *args: None,
        warning=lambda *args: None,
    )

    assert context.invalidate_random_home_widgets("test") == 1
    assert context.invalidate_random_home_widgets("test") == 2
    assert properties[kodi.RANDOM_HOME_WIDGET_GENERATION_PROPERTY] == "2"
    assert kodi.HOME_WIDGET_GENERATION_PROPERTY not in properties


def test_home_layout_slots_are_published_as_home_window_properties(monkeypatch) -> None:
    properties = {}

    class FakeWindow:
        def setProperty(self, key, value):
            properties[key] = value

    class FakeAddon:
        values = {
            "home_row_1": "smart",
            "home_smart_id_1": "42",
            "home_smart_name_1": "Spain",
            "home_smart_mode_1": "square",
        }

        def getSetting(self, key):
            return self.values.get(key, "")

    monkeypatch.setattr(
        kodi,
        "xbmcgui",
        types.SimpleNamespace(Window=lambda window_id: FakeWindow()),
    )
    context = kodi.KodiContext.__new__(kodi.KodiContext)
    context.addon = FakeAddon()
    context.log = types.SimpleNamespace(warning=lambda *args: None)

    context.publish_home_layout_slots()

    assert properties["MyPicsDB3.HomeRow1"] == "smart"
    assert properties["MyPicsDB3.HomeSmartId1"] == "42"
    assert properties["MyPicsDB3.HomeSmartName1"] == "Spain"
    assert properties["MyPicsDB3.HomeSmartMode1"] == "poster"
    assert properties["MyPicsDB3.HomeRow9"] == "none"
    assert properties["MyPicsDB3.HomeSmartId9"] == "0"


def test_service_context_defers_home_state_until_explicitly_enabled() -> None:
    calls = []
    context = kodi.KodiContext.__new__(kodi.KodiContext)
    context._publish_home_state_on_refresh = False
    context.settings = types.SimpleNamespace(debug_logging=False)
    context.log = types.SimpleNamespace(debug_enabled=True)
    context.load_settings = lambda: types.SimpleNamespace(debug_logging=False)
    context.publish_home_widget_limit = lambda: calls.append("limit")
    context.publish_home_layout_slots = lambda: calls.append("layout")

    context.refresh_settings()

    assert calls == []
    assert context.log.debug_enabled is False

    context.enable_home_state_publishing()

    assert calls == ["limit", "layout"]
    assert context._publish_home_state_on_refresh is True

    context.refresh_settings()

    assert calls == ["limit", "layout", "limit"]
