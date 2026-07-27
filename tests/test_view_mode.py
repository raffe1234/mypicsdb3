from __future__ import annotations

from types import SimpleNamespace

from mypicsdb3.view_mode import set_view_mode_when_container_ready


class FakeXbmc:
    def __init__(
        self,
        categories,
        contents,
        *,
        current_mode=53,
        late_restore_mode=None,
        late_restore_after_sleeps=0,
    ):
        self.categories = list(categories)
        self.contents = list(contents)
        self.current_mode = int(current_mode)
        self.commands = []
        self.blocking = []
        self.sleeps = []
        self.command_count = 0
        self.post_first_command_sleeps = 0
        self.late_restore_mode = late_restore_mode
        self.late_restore_after_sleeps = int(late_restore_after_sleeps)
        self.late_restore_done = False

    def getInfoLabel(self, label):
        if label == "Container.PluginCategory":
            values = self.categories
        elif label == "Container.Content":
            values = self.contents
        elif label == "Container.Viewmode":
            return {
                50: "List",
                52: "Icon wall",
                53: "Shift",
                54: "Info wall",
                55: "Wide list",
                500: "Wall",
            }.get(self.current_mode, "")
        else:
            return ""
        if len(values) > 1:
            return values.pop(0)
        return values[0] if values else ""

    def executebuiltin(self, command, block=False):
        self.commands.append(command)
        self.blocking.append(bool(block))
        self.command_count += 1
        self.current_mode = int(command.rsplit("(", 1)[1].rstrip(")"))

    def sleep(self, milliseconds):
        self.sleeps.append(milliseconds)
        if self.command_count == 1 and not self.late_restore_done:
            self.post_first_command_sleeps += 1
            if (
                self.late_restore_mode is not None
                and self.post_first_command_sleeps >= self.late_restore_after_sleeps
            ):
                self.current_mode = int(self.late_restore_mode)
                self.late_restore_done = True


class FakeXbmcGui:
    def __init__(self, xbmc):
        self.xbmc = xbmc

    @staticmethod
    def getCurrentWindowId():
        return 10002

    def Window(self, _window_id):
        return SimpleNamespace(getFocusId=lambda: self.xbmc.current_mode)


def test_view_mode_waits_for_matching_container_and_verifies_target() -> None:
    xbmc = FakeXbmc(
        ["MyPicsDB 3", "Search results: Torrevieja"],
        ["files", "images"],
    )

    changed = set_view_mode_when_container_ready(
        xbmc,
        FakeXbmcGui(xbmc),
        500,
        "Search results: Torrevieja",
        "images",
        settle_ms=100,
        verify_ms=100,
    )

    assert changed is True
    assert xbmc.commands == ["Container.SetViewMode(500)"]
    assert xbmc.blocking == [True]
    assert xbmc.current_mode == 500
    assert xbmc.sleeps and all(value == 50 for value in xbmc.sleeps)


def test_view_mode_retries_after_late_kodi_restore() -> None:
    xbmc = FakeXbmc(
        ["Search results: USA"],
        ["images"],
        late_restore_mode=53,
        late_restore_after_sleeps=2,
    )

    changed = set_view_mode_when_container_ready(
        xbmc,
        FakeXbmcGui(xbmc),
        500,
        "Search results: USA",
        "images",
        settle_ms=0,
        verify_ms=150,
        retry_ms=100,
    )

    assert changed is True
    assert xbmc.commands == [
        "Container.SetViewMode(500)",
        "Container.SetViewMode(500)",
    ]
    assert xbmc.blocking == [True, True]
    assert xbmc.current_mode == 500


def test_view_mode_compares_category_without_kodi_formatting() -> None:
    xbmc = FakeXbmc(
        ["Recent pictures (Minimum rating: 3 stars)"],
        ["IMAGES"],
    )

    changed = set_view_mode_when_container_ready(
        xbmc,
        FakeXbmcGui(xbmc),
        54,
        "Recent pictures  [COLOR=grey](Minimum rating: 3 stars)[/COLOR]",
        "images",
        settle_ms=0,
        verify_ms=0,
    )

    assert changed is True
    assert xbmc.commands == ["Container.SetViewMode(54)"]
    assert xbmc.blocking == [True]


def test_view_mode_times_out_without_touching_parent_container() -> None:
    xbmc = FakeXbmc(["MyPicsDB 3"], ["files"])

    changed = set_view_mode_when_container_ready(
        xbmc,
        FakeXbmcGui(xbmc),
        500,
        "Search results: Torrevieja",
        "images",
        timeout_ms=100,
        poll_interval_ms=50,
    )

    assert changed is False
    assert xbmc.commands == []
    assert xbmc.blocking == []
    assert xbmc.sleeps == [50, 50]


def test_view_mode_cancels_retries_after_navigation() -> None:
    xbmc = FakeXbmc(
        ["Search results: USA", "Search results: USA", "MyPicsDB 3"],
        ["images", "images", "files"],
    )

    changed = set_view_mode_when_container_ready(
        xbmc,
        FakeXbmcGui(xbmc),
        500,
        "Search results: USA",
        "images",
        settle_ms=0,
        verify_ms=200,
    )

    assert changed is True
    assert xbmc.commands == ["Container.SetViewMode(500)"]
    assert xbmc.blocking == [True]


def test_view_mode_ignores_disabled_or_incomplete_requests() -> None:
    xbmc = SimpleNamespace(
        getInfoLabel=lambda _label: "",
        executebuiltin=lambda _command: (_ for _ in ()).throw(AssertionError()),
        sleep=lambda _milliseconds: (_ for _ in ()).throw(AssertionError()),
    )
    xbmcgui = SimpleNamespace()

    assert set_view_mode_when_container_ready(xbmc, xbmcgui, 0, "Pictures", "images") is False
    assert set_view_mode_when_container_ready(xbmc, xbmcgui, 500, "", "images") is False
