from __future__ import annotations

from mypicsdb3 import kodi


class SettingsApi:
    def __init__(self, values):
        self.values = dict(values)

    def getInt(self, setting_id):
        return int(self.values.get(setting_id, 0))

    def getBool(self, setting_id):
        return bool(self.values.get(setting_id, False))

    def getString(self, setting_id):
        return str(self.values.get(setting_id, ""))

    def setInt(self, setting_id, value):
        self.values[setting_id] = int(value)

    def setBool(self, setting_id, value):
        self.values[setting_id] = bool(value)


class Addon:
    def __init__(self, values):
        self.settings_api = SettingsApi(values)

    def getSettings(self):
        return self.settings_api

    def getSetting(self, setting_id):
        return str(self.settings_api.values.get(setting_id, ""))

    def setSetting(self, setting_id, value):
        self.settings_api.values[setting_id] = value
        return True


def context(values):
    result = kodi.KodiContext.__new__(kodi.KodiContext)
    result.addon = Addon(values)
    result.profile_path = "/tmp/mypicsdb3"
    return result


def test_migration_restores_pre_035_value_39_and_marks_complete():
    ctx = context(
        {
            "widget_limit": 39,
            "home_widget_limit": 10,
            "home_widget_limit_migrated_v2": False,
        }
    )

    migration = ctx._migrate_home_widget_limit_setting()

    assert migration == (39, 10, 39, True)
    assert ctx.addon.settings_api.values["widget_limit"] == 39
    assert ctx.addon.settings_api.values["home_widget_limit"] == 39
    assert ctx.addon.settings_api.values["home_widget_limit_migrated_v2"] is True
    settings = ctx.load_settings()
    assert settings.widget_limit == 39
    assert settings.home_widget_limit == 39


def test_migration_preserves_newer_value_when_original_is_old_default():
    ctx = context(
        {
            "widget_limit": 15,
            "home_widget_limit": 32,
            "home_widget_limit_migrated_v2": False,
        }
    )

    migration = ctx._migrate_home_widget_limit_setting()

    assert migration == (15, 32, 32, True)
    assert ctx.load_settings().home_widget_limit == 32


def test_completed_migration_uses_visible_widget_setting_only():
    ctx = context(
        {
            "widget_limit": 4,
            "home_widget_limit": 39,
            "home_widget_limit_migrated_v2": True,
        }
    )

    assert ctx._migrate_home_widget_limit_setting() is None
    settings = ctx.load_settings()
    assert settings.widget_limit == 4
    assert settings.home_widget_limit == 4
