from __future__ import annotations

from types import SimpleNamespace

from mypicsdb3.view_mode import set_view_mode_when_container_ready


class FakeXbmc:
    def __init__(self, categories, contents):
        self.categories = list(categories)
        self.contents = list(contents)
        self.commands = []
        self.sleeps = []

    def getInfoLabel(self, label):
        if label == "Container.PluginCategory":
            values = self.categories
        elif label == "Container.Content":
            values = self.contents
        else:
            return ""
        if len(values) > 1:
            return values.pop(0)
        return values[0] if values else ""

    def executebuiltin(self, command):
        self.commands.append(command)

    def sleep(self, milliseconds):
        self.sleeps.append(milliseconds)


def test_view_mode_waits_for_matching_category_and_content() -> None:
    xbmc = FakeXbmc(
        ["MyPicsDB 3", "MyPicsDB 3", "Search results: Torrevieja"],
        ["files", "files", "images"],
    )

    changed = set_view_mode_when_container_ready(
        xbmc,
        500,
        "Search results: Torrevieja",
        "images",
    )

    assert changed is True
    assert xbmc.commands == ["Container.SetViewMode(500)"]
    assert xbmc.sleeps == [50, 50]


def test_view_mode_compares_category_without_kodi_formatting() -> None:
    xbmc = FakeXbmc(
        ["Recent pictures (Minimum rating: 3 stars)"],
        ["IMAGES"],
    )

    changed = set_view_mode_when_container_ready(
        xbmc,
        54,
        "Recent pictures  [COLOR=grey](Minimum rating: 3 stars)[/COLOR]",
        "images",
    )

    assert changed is True
    assert xbmc.commands == ["Container.SetViewMode(54)"]


def test_view_mode_times_out_without_touching_parent_container() -> None:
    xbmc = FakeXbmc(["MyPicsDB 3"], ["files"])

    changed = set_view_mode_when_container_ready(
        xbmc,
        500,
        "Search results: Torrevieja",
        "images",
        timeout_ms=100,
        poll_interval_ms=50,
    )

    assert changed is False
    assert xbmc.commands == []
    assert xbmc.sleeps == [50, 50]


def test_view_mode_ignores_disabled_or_incomplete_requests() -> None:
    xbmc = SimpleNamespace(
        getInfoLabel=lambda _label: "",
        executebuiltin=lambda _command: (_ for _ in ()).throw(AssertionError()),
        sleep=lambda _milliseconds: (_ for _ in ()).throw(AssertionError()),
    )

    assert set_view_mode_when_container_ready(xbmc, 0, "Pictures", "images") is False
    assert set_view_mode_when_container_ready(xbmc, 500, "", "images") is False
