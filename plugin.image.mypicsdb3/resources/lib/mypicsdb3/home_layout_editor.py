from __future__ import annotations

import traceback
from dataclasses import dataclass
from typing import Dict, FrozenSet, Iterable, List, Optional, Sequence, Set, Tuple

from .preferences import (
    DEFAULT_HOME_ROWS,
    HOME_ROW_COUNT,
    HOME_VIEW_KEYS,
    normalize_home_layout,
)


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
        self.enabled: Set[str] = set(
            [key for key in self.order if key in enabled_keys][:HOME_ROW_COUNT]
        )

    def toggle(self, index: int) -> None:
        key = self.order[index]
        if key in self.enabled:
            self.enabled.remove(key)
        elif len(self.enabled) < HOME_ROW_COUNT:
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
    """Show the XML-based home-view editor, with a safe dialog fallback."""
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
                self.getControl(104).setVisible(False)
                for control_id in (1404, 1405):
                    self.getControl(control_id).setVisible(False)
                    self.getControl(control_id).setEnabled(False)
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


@dataclass(frozen=True)
class SmartHomeEditorText:
    heading: str
    row_heading: str
    visible_heading: str
    order_heading: str
    on: str
    off: str
    move_up: str
    move_down: str
    save: str
    cancel: str
    defaults: str
    add_collection: str
    remove_collection: str
    maximum_rows: str
    no_collections: str


class SmartHomeLayoutState:
    """Mutable mixed built-in/saved-search home layout state."""

    def __init__(self, items):
        from .preferences import (
            DEFAULT_SMART_HOME_MODE,
            HOME_ROW_COUNT,
            HomeLayoutItem,
        )

        self.items = [
            HomeLayoutItem(
                kind=item.kind,
                key=item.key,
                saved_search_id=item.saved_search_id,
                enabled=bool(item.enabled),
                # Per-row display modes were removed in 0.4.11. Keep the
                # compatibility field normalized so older layouts downgrade
                # safely and old square/wide values cannot leak back into Home.
                mode=DEFAULT_SMART_HOME_MODE,
            )
            for item in items
        ]
        enabled_seen = 0
        normalized = []
        for item in self.items:
            enabled = bool(item.enabled) and enabled_seen < HOME_ROW_COUNT
            if enabled:
                enabled_seen += 1
            normalized.append(
                HomeLayoutItem(
                    kind=item.kind,
                    key=item.key,
                    saved_search_id=item.saved_search_id,
                    enabled=enabled,
                    mode=DEFAULT_SMART_HOME_MODE,
                )
            )
        self.items = normalized

    def toggle(self, index: int) -> bool:
        from .preferences import HOME_ROW_COUNT, HomeLayoutItem

        item = self.items[index]
        if item.enabled:
            enabled = False
        else:
            if sum(1 for value in self.items if value.enabled) >= HOME_ROW_COUNT:
                return False
            enabled = True
        self.items[index] = HomeLayoutItem(
            kind=item.kind,
            key=item.key,
            saved_search_id=item.saved_search_id,
            enabled=enabled,
            mode=item.mode,
        )
        return True

    def move(self, index: int, offset: int) -> int:
        target = index + offset
        if target < 0 or target >= len(self.items):
            return index
        self.items[index], self.items[target] = self.items[target], self.items[index]
        return target

    def add_smart(self, saved_search_id: int) -> bool:
        from .preferences import (
            DEFAULT_SMART_HOME_MODE,
            HOME_ROW_COUNT,
            HomeLayoutItem,
        )

        if any(
            item.kind == "smart" and item.saved_search_id == saved_search_id
            for item in self.items
        ):
            return False
        enabled = sum(1 for item in self.items if item.enabled) < HOME_ROW_COUNT
        self.items.append(
            HomeLayoutItem(
                kind="smart",
                saved_search_id=int(saved_search_id),
                enabled=enabled,
                mode=DEFAULT_SMART_HOME_MODE,
            )
        )
        return True

    def remove(self, index: int) -> bool:
        if self.items[index].kind != "smart":
            return False
        del self.items[index]
        return True

    def reset(self) -> None:
        from .preferences import default_home_layout_items

        self.items = list(default_home_layout_items())

    def snapshot(self):
        return tuple(self.items)


def _smart_home_item_name(item, builtin_labels, saved_search_names) -> str:
    if item.kind == "smart":
        return saved_search_names.get(
            item.saved_search_id,
            "#%d" % item.saved_search_id,
        )
    return builtin_labels.get(item.key, item.key)


def _smart_home_item_label(item, builtin_labels, saved_search_names, text) -> str:
    return "%s  %s" % (
        text.on if item.enabled else text.off,
        _smart_home_item_name(item, builtin_labels, saved_search_names),
    )


def _add_smart_home_collection(
    state, saved_search_names, text, dialog
) -> Optional[int]:
    existing = {
        item.saved_search_id
        for item in state.items
        if item.kind == "smart"
    }
    available = [
        (saved_id, name)
        for saved_id, name in saved_search_names.items()
        if saved_id not in existing
    ]
    if not available:
        dialog.ok(text.heading, text.no_collections)
        return None
    choice = dialog.select(
        text.add_collection,
        [name for _saved_id, name in available],
    )
    if choice < 0:
        return None
    saved_search_id = available[choice][0]
    if not state.add_smart(saved_search_id):
        return None
    return next(
        index
        for index, item in enumerate(state.items)
        if item.kind == "smart" and item.saved_search_id == saved_search_id
    )


def _edit_smart_home_row(
    state, index, builtin_labels, saved_search_names, text, dialog
) -> int:
    item = state.items[index]
    row_actions = [
        text.off if item.enabled else text.on,
        text.move_up,
        text.move_down,
    ]
    if item.kind == "smart":
        row_actions.append(text.remove_collection)
    action = dialog.select(
        _smart_home_item_label(
            item, builtin_labels, saved_search_names, text
        ),
        row_actions,
    )
    if action == 0:
        if not state.toggle(index):
            dialog.ok(text.heading, text.maximum_rows)
    elif action == 1:
        index = state.move(index, -1)
    elif action == 2:
        index = state.move(index, 1)
    elif item.kind == "smart" and action == 3:
        state.remove(index)
        index = min(index, max(0, len(state.items) - 1))
    return index


def _show_smart_home_fallback(
    state, builtin_labels, saved_search_names, text, dialog
):
    """Fallback for platforms that cannot load the XML row-controls editor."""

    while True:
        rows = [
            _smart_home_item_label(
                item, builtin_labels, saved_search_names, text
            )
            for item in state.items
        ]
        # Kodi's select dialog already supplies its own Cancel button.
        actions = [text.add_collection, text.save, text.defaults]
        selected = dialog.select(text.heading, rows + actions)
        if selected < 0:
            return None
        if selected == len(rows):
            _add_smart_home_collection(
                state, saved_search_names, text, dialog
            )
            continue
        if selected == len(rows) + 1:
            return state.snapshot()
        if selected == len(rows) + 2:
            state.reset()
            continue
        _edit_smart_home_row(
            state,
            selected,
            builtin_labels,
            saved_search_names,
            text,
            dialog,
        )


def show_smart_home_layout_editor(
    items,
    builtin_labels: Dict[str, str],
    saved_search_names: Dict[int, str],
    text: SmartHomeEditorText,
    xbmcgui_module=None,
):
    """Edit Home rows with inline On/Off and move controls.

    Kodi uses the XML-backed editor when available. Ten row slots are visible at
    once; moving past the first or last visible slot scrolls the mixed built-in
    and smart-collection list. Smart collections use the normal album default
    when opened and therefore have no separate display-mode action.
    """

    custom_dialog = xbmcgui_module is None
    if xbmcgui_module is None:
        import xbmcgui as xbmcgui_module  # type: ignore

    dialog = xbmcgui_module.Dialog()
    state = SmartHomeLayoutState(items)
    if not custom_dialog:
        return _show_smart_home_fallback(
            state,
            builtin_labels,
            saved_search_names,
            text,
            dialog,
        )

    import xbmc  # type: ignore
    import xbmcaddon  # type: ignore

    visible_row_count = 10
    back_actions = {9, 10, 92}
    action_move_left = 1
    action_move_up = 3
    action_move_down = 4
    action_page_up = 5
    action_page_down = 6
    action_mouse_wheel_up = 104
    action_mouse_wheel_down = 105
    side_controls = {1401, 1402, 1403, 1404, 1405}

    class SmartHomeLayoutDialog(xbmcgui_module.WindowXMLDialog):
        def configure(self) -> None:
            self.state = state
            self.builtin_labels = builtin_labels
            self.saved_search_names = saved_search_names
            self.editor_text = text
            self.dialog = dialog
            self.result = None
            self.top_index = 0
            self.selected_index = 0
            self._ready = False

        @staticmethod
        def _row_control(control_id: int):
            for base in (1101, 1201, 1301):
                if base <= control_id < base + visible_row_count:
                    return base, control_id - base
            return None

        def _ensure_visible(self, index: int) -> None:
            if not self.state.items:
                self.top_index = 0
                return
            index = max(0, min(index, len(self.state.items) - 1))
            if index < self.top_index:
                self.top_index = index
            elif index >= self.top_index + visible_row_count:
                self.top_index = index - visible_row_count + 1
            maximum = max(0, len(self.state.items) - visible_row_count)
            self.top_index = max(0, min(self.top_index, maximum))

        def _selected_item(self):
            if 0 <= self.selected_index < len(self.state.items):
                return self.state.items[self.selected_index]
            return None

        def _update_remove_action(self) -> None:
            item = self._selected_item()
            visible = item is not None and item.kind == "smart"
            control = self.getControl(1405)
            control.setVisible(visible)
            control.setEnabled(visible)

        def _refresh_rows(self) -> None:
            count = len(self.state.items)
            if count:
                first = self.top_index + 1
                last = min(count, self.top_index + visible_row_count)
                self.getControl(104).setLabel("%d–%d / %d" % (first, last, count))
            else:
                self.getControl(104).setLabel("0 / 0")

            for slot in range(visible_row_count):
                index = self.top_index + slot
                visible = index < count
                label = self.getControl(1001 + slot)
                toggle = self.getControl(1101 + slot)
                move_up = self.getControl(1201 + slot)
                move_down = self.getControl(1301 + slot)
                for control in (label, toggle, move_up, move_down):
                    control.setVisible(visible)
                if not visible:
                    continue

                item = self.state.items[index]
                label.setLabel(
                    _smart_home_item_name(
                        item,
                        self.builtin_labels,
                        self.saved_search_names,
                    )
                )
                toggle.setEnabled(True)
                toggle.setLabel(
                    self.editor_text.on if item.enabled else self.editor_text.off
                )
                toggle.setSelected(bool(item.enabled))
                move_up.setEnabled(index > 0)
                move_down.setEnabled(index < count - 1)
            self._update_remove_action()

        def _focus_row(self, base: int, index: int) -> None:
            if not self.state.items:
                self.setFocusId(1404)
                return
            self.selected_index = max(0, min(index, len(self.state.items) - 1))
            self._ensure_visible(self.selected_index)
            self._refresh_rows()
            self.setFocusId(base + self.selected_index - self.top_index)

        def onInit(self) -> None:  # noqa: N802 - Kodi callback name
            try:
                self.getControl(100).setLabel(self.editor_text.heading)
                self.getControl(101).setLabel(self.editor_text.row_heading)
                self.getControl(102).setLabel(self.editor_text.visible_heading)
                self.getControl(103).setLabel(self.editor_text.order_heading)
                self.getControl(104).setVisible(True)
                self.getControl(1401).setLabel(self.editor_text.save)
                self.getControl(1402).setLabel(self.editor_text.cancel)
                self.getControl(1403).setLabel(self.editor_text.defaults)
                self.getControl(1404).setLabel(self.editor_text.add_collection)
                self.getControl(1404).setVisible(True)
                self.getControl(1404).setEnabled(True)
                self.getControl(1405).setLabel(self.editor_text.remove_collection)
                for index in range(visible_row_count):
                    self.getControl(1201 + index).setLabel("▲")
                    self.getControl(1301 + index).setLabel("▼")
                self._refresh_rows()
                self._ready = True
                self._focus_row(1101, 0)
            except Exception:
                xbmc.log(
                    "MyPicsDB 3 smart home editor onInit failed:\n%s"
                    % traceback.format_exc(),
                    xbmc.LOGERROR,
                )
                self.close()

        def onFocus(self, control_id: int) -> None:  # noqa: N802
            row_control = self._row_control(control_id)
            if row_control is None:
                return
            _base, slot = row_control
            index = self.top_index + slot
            if index < len(self.state.items):
                self.selected_index = index
                self._update_remove_action()

        def onClick(self, control_id: int) -> None:  # noqa: N802
            if control_id == 1401:
                self.result = self.state.snapshot()
                self.close()
                return
            if control_id == 1402:
                self.close()
                return
            if control_id == 1403:
                self.state.reset()
                self.top_index = 0
                self._focus_row(1101, 0)
                return
            if control_id == 1404:
                added_index = _add_smart_home_collection(
                    self.state,
                    self.saved_search_names,
                    self.editor_text,
                    self.dialog,
                )
                if added_index is not None:
                    self._focus_row(1101, added_index)
                else:
                    self._refresh_rows()
                return
            if control_id == 1405:
                if self.state.items and self.state.remove(self.selected_index):
                    target = min(
                        self.selected_index,
                        max(0, len(self.state.items) - 1),
                    )
                    self._focus_row(1101, target)
                return

            row_control = self._row_control(control_id)
            if row_control is None:
                return
            base, slot = row_control
            index = self.top_index + slot
            if index >= len(self.state.items):
                return
            self.selected_index = index
            if base == 1101:
                if not self.state.toggle(index):
                    self.dialog.ok(
                        self.editor_text.heading,
                        self.editor_text.maximum_rows,
                    )
                self._focus_row(base, index)
                return
            offset = -1 if base == 1201 else 1
            target = self.state.move(index, offset)
            self._focus_row(base, target)

        def onAction(self, action) -> None:  # noqa: N802 - Kodi callback name
            action_id = action.getId()
            if action_id in back_actions:
                self.close()
                return

            focus_id = self.getFocusId()
            if focus_id in side_controls:
                if action_id == action_move_left:
                    self._focus_row(1301, self.selected_index)
                    return
                if action_id in (action_move_up, action_move_down):
                    ordered = [1401, 1402, 1403, 1404]
                    selected_item = self._selected_item()
                    if selected_item is not None and selected_item.kind == "smart":
                        ordered.append(1405)
                    current = ordered.index(focus_id) if focus_id in ordered else 0
                    offset = -1 if action_id == action_move_up else 1
                    self.setFocusId(ordered[(current + offset) % len(ordered)])
                    return

            row_control = self._row_control(focus_id)
            if row_control is None:
                return
            base, slot = row_control
            index = self.top_index + slot
            if action_id in (action_move_up, action_mouse_wheel_up):
                if slot == 0 and index > 0:
                    self._focus_row(base, index - 1)
                return
            if action_id in (action_move_down, action_mouse_wheel_down):
                if slot == visible_row_count - 1 and index + 1 < len(self.state.items):
                    self._focus_row(base, index + 1)
                return
            if action_id == action_page_up:
                self._focus_row(base, max(0, index - visible_row_count))
                return
            if action_id == action_page_down:
                self._focus_row(
                    base,
                    min(len(self.state.items) - 1, index + visible_row_count),
                )

    xml_dialog = None
    try:
        addon_path = xbmcaddon.Addon().getAddonInfo("path")
        xml_dialog = SmartHomeLayoutDialog(
            "home_layout_editor.xml",
            addon_path,
            "Default",
            "1080i",
        )
        xml_dialog.configure()
        xml_dialog.doModal()
        if getattr(xml_dialog, "_ready", False):
            return xml_dialog.result
    except Exception:
        xbmc.log(
            "MyPicsDB 3 XML smart home editor failed; using fallback:\n%s"
            % traceback.format_exc(),
            xbmc.LOGERROR,
        )
    finally:
        if xml_dialog is not None:
            del xml_dialog

    return _show_smart_home_fallback(
        state,
        builtin_labels,
        saved_search_names,
        text,
        dialog,
    )
