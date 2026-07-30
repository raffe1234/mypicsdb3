from __future__ import annotations

from mypicsdb3 import kodi


class TypedSettings:
    def getInt(self, setting_id):
        if setting_id == "home_widget_limit":
            return 39
        raise KeyError(setting_id)

    def getBool(self, setting_id):
        raise KeyError(setting_id)

    def getString(self, setting_id):
        raise KeyError(setting_id)


class AddonWithTypedSettings:
    def getSettings(self):
        return TypedSettings()

    def getSetting(self, setting_id):
        values = {
            "home_widget_limit": "10",
            "widget_limit": "15",
            "browser_page_size": "100",
        }
        return values.get(setting_id, "")


class LegacyAddon:
    def getSetting(self, setting_id):
        return "27" if setting_id == "home_widget_limit" else ""


def context_for(addon):
    context = kodi.KodiContext.__new__(kodi.KodiContext)
    context.addon = addon
    context.profile_path = "/tmp/mypicsdb3"
    return context


def test_kodi_20_typed_integer_setting_wins_over_stale_legacy_string():
    settings = context_for(AddonWithTypedSettings()).load_settings()

    assert settings.home_widget_limit == 39
    assert settings.widget_limit == 15
    assert settings.browser_page_size == 100


def test_legacy_setting_reader_remains_supported():
    settings = context_for(LegacyAddon()).load_settings()

    assert settings.home_widget_limit == 27
