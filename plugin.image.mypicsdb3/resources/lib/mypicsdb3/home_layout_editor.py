from __future__ import annotations

import traceback
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


def _show_fallback_editor(
    state: HomeLayoutState,
    labels: Dict[str, str],
    text: HomeLayoutEditorText,
    xbmcgui_module,
) -> Optional[Tuple[Tuple[str, ...], FrozenSet[str]]]:
    """Use ordinary Kodi select dialogs if the XML dialog cannot be loaded."""
    dialog = xbmcgui_module.Dialog()
    while True:
        rows = [
            "%s  %s" % (
                text.on if key in state.enabled else text.off,
                labels.get(key, key),
            )
            for key in state.order
        ]
        actions = [text.save, text.defaults, text.cancel]
        selected = dialog.select(text.heading, rows + actions)
        if selected < 0 or selected == len(rows) + 2:
            return None
        if selected == len(rows):
            return state.snapshot()
        if selected == len(rows) + 1:
            state.reset()
            continue

        row_index = selected
        row_actions = [
            text.off if state.order[row_index] in state.enabled else text.on,
            text.move_up,
            text.move_down,
        ]
        action = dialog.select(labels.get(state.order[row_index], state.order[row_index]), row_actions)
        if action == 0:
            state.toggle(row_index)
        elif action == 1:
            state.move(row_index, -1)
        elif action == 2:
            state.move(row_index, 1)


def show_home_layout_editor(
    order: Sequence[object],
    enabled: Iterable[object],
    labels: Dict[str, str],
    text: HomeLayoutEditorText,
) -> Optional[Tuple[Tuple[str, ...], FrozenSet[str]]]:
    """Show the XML-based nine-row editor, with a safe dialog fallback."""
    import xbmc  # type: ignore
    import xbmcaddon  # type: ignore
    import xbmcgui  # type: ignore

    state = HomeLayoutState(order, enabled)
    back_actions = {9, 10, 92}
    row_count = len(HOME_VIEW_KEYS)

    class HomeLayoutDialog(xbmcgui.WindowXMLDialog):
        def configure(self) -> None:
            self.state = state
            self.labels = labels
            self.editor_text = text
            self.result = None
            self._ready = False

        def onInit(self) -> None:  # noqa: N802 - Kodi callback name
            try:
                self.getControl(100).setLabel(self.editor_text.heading)
                self.getControl(101).setLabel(self.editor_text.view_heading)
                self.getControl(102).setLabel(self.editor_text.visible_heading)
                self.getControl(103).setLabel(self.editor_text.order_heading)
                self.getControl(1401).setLabel(self.editor_text.save)
                self.getControl(1402).setLabel(self.editor_text.cancel)
                self.getControl(1403).setLabel(self.editor_text.defaults)
                for index in range(row_count):
                    self.getControl(1201 + index).setLabel("▲")
                    self.getControl(1301 + index).setLabel("▼")
                self._refresh_rows()
                self._ready = True
                self.setFocusId(1101)
            except Exception:
                xbmc.log(
                    "MyPicsDB 3 home editor onInit failed:\n%s" % traceback.format_exc(),
                    xbmc.LOGERROR,
                )
                self.close()

        def _refresh_rows(self) -> None:
            for index, key in enumerate(self.state.order):
                self.getControl(1001 + index).setLabel(self.labels.get(key, key))
                toggle = self.getControl(1101 + index)
                selected = key in self.state.enabled
                toggle.setLabel(self.editor_text.on if selected else self.editor_text.off)
                toggle.setSelected(selected)
                self.getControl(1201 + index).setEnabled(index > 0)
                self.getControl(1301 + index).setEnabled(index < row_count - 1)

        def onClick(self, control_id: int) -> None:  # noqa: N802 - Kodi callback name
            if control_id == 1401:
                self.result = self.state.snapshot()
                self.close()
                return
            if control_id == 1402:
                self.close()
                return
            if control_id == 1403:
                self.state.reset()
                self._refresh_rows()
                self.setFocusId(1101)
                return

            if 1101 <= control_id < 1101 + row_count:
                index = control_id - 1101
                self.state.toggle(index)
                self._refresh_rows()
                self.setFocusId(control_id)
                return
            if 1201 <= control_id < 1201 + row_count:
                index = control_id - 1201
                target = self.state.move(index, -1)
                self._refresh_rows()
                self.setFocusId(1201 + target)
                return
            if 1301 <= control_id < 1301 + row_count:
                index = control_id - 1301
                target = self.state.move(index, 1)
                self._refresh_rows()
                self.setFocusId(1301 + target)

        def onAction(self, action) -> None:  # noqa: N802 - Kodi callback name
            if action.getId() in back_actions:
                self.close()

    dialog = None
    try:
        addon_path = xbmcaddon.Addon().getAddonInfo("path")
        dialog = HomeLayoutDialog(
            "home_layout_editor.xml",
            addon_path,
            "Default",
            "1080i",
        )
        dialog.configure()
        dialog.doModal()
        if getattr(dialog, "_ready", False):
            return dialog.result
    except Exception:
        xbmc.log(
            "MyPicsDB 3 XML home editor failed; using fallback:\n%s"
            % traceback.format_exc(),
            xbmc.LOGERROR,
        )
    finally:
        if dialog is not None:
            del dialog

    return _show_fallback_editor(state, labels, text, xbmcgui)
