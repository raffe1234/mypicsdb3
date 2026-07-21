from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Dict, FrozenSet, Iterable, List, Optional, Sequence, Set, Tuple

from .preferences import DEFAULT_HOME_ROWS, HOME_VIEW_KEYS, normalize_home_layout


@dataclass(frozen=True)
class HomeLayoutEditorText:
    heading: str
    view_heading: str
    visible_heading: str
    order_heading: str
    on: str
    off: str
    move_up: str
    move_down: str
    save: str
    cancel: str
    defaults: str


class HomeLayoutState:
    """Mutable state used by the visual home-screen layout editor."""

    def __init__(self, order: Sequence[object], enabled: Iterable[object]):
        normalized_order, _ = normalize_home_layout(order)
        enabled_keys = {
            str(value)
            for value in enabled
            if str(value) in HOME_VIEW_KEYS
        }
        self.order: List[str] = list(normalized_order)
        self.enabled: Set[str] = enabled_keys

    def toggle(self, index: int) -> None:
        key = self.order[index]
        if key in self.enabled:
            self.enabled.remove(key)
        else:
            self.enabled.add(key)

    def move(self, index: int, offset: int) -> int:
        target = index + offset
        if target < 0 or target >= len(self.order):
            return index
        self.order[index], self.order[target] = self.order[target], self.order[index]
        return target

    def reset(self) -> None:
        order, enabled = normalize_home_layout(DEFAULT_HOME_ROWS)
        self.order = list(order)
        self.enabled = set(enabled)

    def snapshot(self) -> Tuple[Tuple[str, ...], FrozenSet[str]]:
        return tuple(self.order), frozenset(self.enabled)


def _media_path(filename: str) -> str:
    resources_dir = os.path.normpath(
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..")
    )
    return os.path.join(resources_dir, "media", filename)


def show_home_layout_editor(
    order: Sequence[object],
    enabled: Iterable[object],
    labels: Dict[str, str],
    text: HomeLayoutEditorText,
) -> Optional[Tuple[Tuple[str, ...], FrozenSet[str]]]:
    """Show a nine-row editor with an on/off button and move arrows per row."""
    import xbmcgui  # type: ignore

    alignment_left_center = 0x00000004
    alignment_center = 0x00000002 | 0x00000004
    back_actions = {9, 10, 92}

    class HomeLayoutDialog(xbmcgui.WindowDialog):
        def __init__(self):
            super().__init__()
            self.state = HomeLayoutState(order, enabled)
            self.result = None
            self.row_label_controls = []
            self.toggle_controls = []
            self.up_controls = []
            self.down_controls = []
            self.save_control = None
            self.cancel_control = None
            self.defaults_control = None

            width = max(int(self.getWidth()), 1)
            height = max(int(self.getHeight()), 1)
            sx = width / 1920.0
            sy = height / 1080.0

            def x(value: int) -> int:
                return int(round(value * sx))

            def y(value: int) -> int:
                return int(round(value * sy))

            background = _media_path("home-editor-background.png")
            panel = _media_path("home-editor-panel.png")
            focus = _media_path("home-editor-focus.png")
            toggle_on = _media_path("home-editor-toggle-on.png")
            toggle_on_focus = _media_path("home-editor-toggle-on-focus.png")
            toggle_off = _media_path("home-editor-toggle-off.png")
            toggle_off_focus = _media_path("home-editor-toggle-off-focus.png")

            controls = [
                xbmcgui.ControlImage(0, 0, width, height, background),
                xbmcgui.ControlImage(0, 0, width, y(86), focus),
                xbmcgui.ControlImage(x(430), y(115), x(1120), y(835), panel),
                xbmcgui.ControlLabel(
                    x(42), y(18), x(1000), y(54), text.heading,
                    font="font20", textColor="0xFFFFFFFF",
                    alignment=alignment_left_center,
                ),
                xbmcgui.ControlLabel(
                    x(500), y(130), x(680), y(48), text.view_heading,
                    font="font13", textColor="0xFFB8C1C4",
                    alignment=alignment_left_center,
                ),
                xbmcgui.ControlLabel(
                    x(1190), y(130), x(150), y(48), text.visible_heading,
                    font="font13", textColor="0xFFB8C1C4",
                    alignment=alignment_center,
                ),
                xbmcgui.ControlLabel(
                    x(1360), y(130), x(150), y(48), text.order_heading,
                    font="font13", textColor="0xFFB8C1C4",
                    alignment=alignment_center,
                ),
            ]

            row_top = 180
            row_step = 78
            row_height = 58
            for index in range(len(HOME_VIEW_KEYS)):
                top = row_top + index * row_step
                label_control = xbmcgui.ControlLabel(
                    x(500), y(top), x(660), y(row_height), "",
                    font="font13", textColor="0xFFD8DDDF",
                    alignment=alignment_left_center,
                )
                toggle_control = xbmcgui.ControlRadioButton(
                    x(1180), y(top), x(170), y(row_height), "",
                    focusOnTexture=toggle_on_focus,
                    noFocusOnTexture=toggle_on,
                    focusOffTexture=toggle_off_focus,
                    noFocusOffTexture=toggle_off,
                    focusTexture=focus, noFocusTexture=panel,
                    alignment=alignment_left_center, font="font13",
                    textColor="0xFFD8DDDF", disabledColor="0xFF6B7376",
                )
                toggle_control.setRadioDimension(
                    x(100), y(8), x(58), y(42)
                )
                up_control = xbmcgui.ControlButton(
                    x(1370), y(top), x(65), y(row_height), "▲",
                    focusTexture=focus, noFocusTexture=panel,
                    alignment=alignment_center, font="font13",
                    textColor="0xFFD8DDDF", disabledColor="0xFF596164",
                    focusedColor="0xFFFFFFFF",
                )
                down_control = xbmcgui.ControlButton(
                    x(1445), y(top), x(65), y(row_height), "▼",
                    focusTexture=focus, noFocusTexture=panel,
                    alignment=alignment_center, font="font13",
                    textColor="0xFFD8DDDF", disabledColor="0xFF596164",
                    focusedColor="0xFFFFFFFF",
                )
                self.row_label_controls.append(label_control)
                self.toggle_controls.append(toggle_control)
                self.up_controls.append(up_control)
                self.down_controls.append(down_control)
                controls.extend((label_control, toggle_control, up_control, down_control))

            self.save_control = xbmcgui.ControlButton(
                x(1590), y(180), x(260), y(72), text.save,
                focusTexture=focus, noFocusTexture=panel,
                alignment=alignment_center, font="font13",
                textColor="0xFFD8DDDF", focusedColor="0xFFFFFFFF",
            )
            self.cancel_control = xbmcgui.ControlButton(
                x(1590), y(270), x(260), y(72), text.cancel,
                focusTexture=focus, noFocusTexture=panel,
                alignment=alignment_center, font="font13",
                textColor="0xFFD8DDDF", focusedColor="0xFFFFFFFF",
            )
            self.defaults_control = xbmcgui.ControlButton(
                x(1590), y(360), x(260), y(72), text.defaults,
                focusTexture=focus, noFocusTexture=panel,
                alignment=alignment_center, font="font13",
                textColor="0xFFD8DDDF", focusedColor="0xFFFFFFFF",
            )
            controls.extend((self.save_control, self.cancel_control, self.defaults_control))
            self.addControls(controls)
            self._refresh_rows()
            self._set_navigation()
            self.setFocus(self.toggle_controls[0])

        def _refresh_rows(self) -> None:
            for index, key in enumerate(self.state.order):
                self.row_label_controls[index].setLabel(labels.get(key, key))
                selected = key in self.state.enabled
                self.toggle_controls[index].setLabel(text.on if selected else text.off)
                self.toggle_controls[index].setSelected(selected)
                self.up_controls[index].setEnabled(index > 0)
                self.down_controls[index].setEnabled(index < len(self.state.order) - 1)

        def _set_navigation(self) -> None:
            last_index = len(self.toggle_controls) - 1
            for index in range(len(self.toggle_controls)):
                upper = max(0, index - 1)
                lower = min(last_index, index + 1)
                toggle = self.toggle_controls[index]
                up_button = self.up_controls[index]
                down_button = self.down_controls[index]
                toggle.setNavigation(
                    self.toggle_controls[upper], self.toggle_controls[lower],
                    toggle, up_button,
                )
                up_button.setNavigation(
                    self.up_controls[upper], self.up_controls[lower],
                    toggle, down_button,
                )
                down_button.setNavigation(
                    self.down_controls[upper], self.down_controls[lower],
                    up_button, self.save_control,
                )

            self.save_control.setNavigation(
                self.defaults_control, self.cancel_control,
                self.down_controls[0], self.save_control,
            )
            self.cancel_control.setNavigation(
                self.save_control, self.defaults_control,
                self.down_controls[1], self.cancel_control,
            )
            self.defaults_control.setNavigation(
                self.cancel_control, self.save_control,
                self.down_controls[2], self.defaults_control,
            )

        def onControl(self, control) -> None:  # noqa: N802 - Kodi callback name
            if control == self.save_control:
                self.result = self.state.snapshot()
                self.close()
                return
            if control == self.cancel_control:
                self.close()
                return
            if control == self.defaults_control:
                self.state.reset()
                self._refresh_rows()
                self.setFocus(self.toggle_controls[0])
                return

            for index, toggle_control in enumerate(self.toggle_controls):
                if control == toggle_control:
                    self.state.toggle(index)
                    self._refresh_rows()
                    self.setFocus(self.toggle_controls[index])
                    return
                if control == self.up_controls[index]:
                    target = self.state.move(index, -1)
                    self._refresh_rows()
                    self.setFocus(self.up_controls[target])
                    return
                if control == self.down_controls[index]:
                    target = self.state.move(index, 1)
                    self._refresh_rows()
                    self.setFocus(self.down_controls[target])
                    return

        def onAction(self, action) -> None:  # noqa: N802 - Kodi callback name
            if action.getId() in back_actions:
                self.close()

    dialog = HomeLayoutDialog()
    try:
        dialog.doModal()
        return dialog.result
    finally:
        del dialog
