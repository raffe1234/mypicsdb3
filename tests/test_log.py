from __future__ import annotations

from mypicsdb3.log import Logger


class FakeKodi:
    LOGDEBUG = 0
    LOGINFO = 1
    LOGWARNING = 2
    LOGERROR = 3

    def __init__(self):
        self.messages = []

    def log(self, message, level):
        self.messages.append((message, level))


def test_addon_debug_setting_is_visible_without_global_kodi_debug() -> None:
    kodi = FakeKodi()
    logger = Logger("MyPicsDB 3", debug=True, kodi_module=kodi)

    logger.debug("route=%s videos=%d", "mixed-playlist", 1)

    assert kodi.messages == [
        ("[MyPicsDB 3] route=mixed-playlist videos=1", kodi.LOGINFO)
    ]


def test_disabled_addon_debug_setting_emits_nothing() -> None:
    kodi = FakeKodi()
    logger = Logger("MyPicsDB 3", debug=False, kodi_module=kodi)

    logger.debug("hidden")

    assert kodi.messages == []
