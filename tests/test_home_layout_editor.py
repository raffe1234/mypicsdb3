from __future__ import annotations

from pathlib import Path

from mypicsdb3.home_layout_editor import HomeLayoutState


def test_home_layout_state_toggles_and_moves_rows() -> None:
    state = HomeLayoutState(
        [
            "recent_taken",
            "recent_added",
            "random_memories",
            "recent_albums",
            "random_albums",
            "on_this_day",
            "favorites",
            "rated",
            "geotagged",
        ],
        {"recent_taken", "recent_added"},
    )

    state.toggle(6)
    target = state.move(6, -1)

    order, enabled = state.snapshot()
    assert target == 5
    assert order[5] == "favorites"
    assert "favorites" in enabled


def test_home_layout_state_defaults_enable_first_six_rows() -> None:
    state = HomeLayoutState(["geotagged"], {"geotagged"})

    state.reset()

    order, enabled = state.snapshot()
    assert order[:6] == (
        "recent_taken",
        "recent_added",
        "random_memories",
        "recent_albums",
        "random_albums",
        "on_this_day",
    )
    assert enabled == frozenset(order[:6])


def test_home_layout_editor_media_is_packaged() -> None:
    media = (
        Path(__file__).resolve().parents[1]
        / "plugin.image.mypicsdb3"
        / "resources"
        / "media"
    )
    expected = {
        "home-editor-background.png",
        "home-editor-panel.png",
        "home-editor-focus.png",
        "home-editor-toggle-on.png",
        "home-editor-toggle-on-focus.png",
        "home-editor-toggle-off.png",
        "home-editor-toggle-off-focus.png",
    }
    assert expected <= {path.name for path in media.glob("*.png")}
