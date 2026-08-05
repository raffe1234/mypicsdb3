from __future__ import annotations

import traceback
from dataclasses import dataclass
from typing import Dict, FrozenSet, Iterable, List, Optional, Sequence, Set, Tuple

from .action_list_dialog import ActionListDialogUnavailable, show_action_list_dialog
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
    on: str
    off: str
    move_up: str
    move_down: str
    save: str
    cancel: str
    defaults: str
    add_collection: str
    remove_collection: str
    display_mode: str
    poster: str
    square: str
    landscape: str
    maximum_rows: str
    no_collections: str


class SmartHomeLayoutState:
    """Mutable mixed built-in/saved-search home layout state."""

    def __init__(self, items):
        from .preferences import HOME_ROW_COUNT, HomeLayoutItem

        self.items = [
            HomeLayoutItem(
                kind=item.kind,
                key=item.key,
                saved_search_id=item.saved_search_id,
                enabled=bool(item.enabled),
                mode=item.mode,
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
                    mode=item.mode,
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

    def add_smart(self, saved_search_id: int, mode: str = "poster") -> bool:
        from .preferences import HOME_ROW_COUNT, HomeLayoutItem, normalize_smart_home_mode

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
                mode=normalize_smart_home_mode(mode),
            )
        )
        return True

    def remove(self, index: int) -> bool:
        if self.items[index].kind != "smart":
            return False
        del self.items[index]
        return True

    def set_mode(self, index: int, mode: str) -> None:
        from .preferences import HomeLayoutItem, normalize_smart_home_mode

        item = self.items[index]
        if item.kind != "smart":
            return
        self.items[index] = HomeLayoutItem(
            kind=item.kind,
            key=item.key,
            saved_search_id=item.saved_search_id,
            enabled=item.enabled,
            mode=normalize_smart_home_mode(mode),
        )

    def reset(self) -> None:
        from .preferences import default_home_layout_items

        self.items = list(default_home_layout_items())

    def snapshot(self):
        return tuple(self.items)


def _smart_home_item_label(item, builtin_labels, saved_search_names, text, mode_labels) -> str:
    if item.kind == "smart":
        name = saved_search_names.get(item.saved_search_id, "#%d" % item.saved_search_id)
        return "%s  %s  [COLOR=grey](%s)[/COLOR]" % (
            text.on if item.enabled else text.off,
            name,
            mode_labels.get(item.mode, text.poster),
        )
    return "%s  %s" % (
        text.on if item.enabled else text.off,
        builtin_labels.get(item.key, item.key),
    )


def _add_smart_home_collection(
    state, saved_search_names, text, mode_labels, dialog
) -> None:
    from .preferences import SMART_HOME_MODES

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
        return
    choice = dialog.select(
        text.add_collection,
        [name for _saved_id, name in available],
    )
    if choice < 0:
        return
    mode_choice = dialog.select(
        text.display_mode,
        [mode_labels[mode] for mode in SMART_HOME_MODES],
    )
    if mode_choice < 0:
        mode_choice = 0
    state.add_smart(available[choice][0], SMART_HOME_MODES[mode_choice])


def _edit_smart_home_row(
    state, index, builtin_labels, saved_search_names, text, mode_labels, dialog
) -> int:
    from .preferences import SMART_HOME_MODES

    item = state.items[index]
    row_actions = [
        text.off if item.enabled else text.on,
        text.move_up,
        text.move_down,
    ]
    if item.kind == "smart":
        row_actions.extend([text.display_mode, text.remove_collection])
    action = dialog.select(
        _smart_home_item_label(
            item, builtin_labels, saved_search_names, text, mode_labels
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
        current_mode = item.mode if item.mode in SMART_HOME_MODES else "poster"
        preselect = SMART_HOME_MODES.index(current_mode)
        mode_choice = dialog.select(
            text.display_mode,
            [mode_labels[mode] for mode in SMART_HOME_MODES],
            preselect=preselect,
        )
        if mode_choice >= 0:
            state.set_mode(index, SMART_HOME_MODES[mode_choice])
    elif item.kind == "smart" and action == 4:
        state.remove(index)
        index = min(index, max(0, len(state.items) - 1))
    return index


def _show_smart_home_fallback(
    state, builtin_labels, saved_search_names, text, mode_labels, dialog
):
    """Fallback for skins/platforms that cannot load the XML editor."""

    while True:
        rows = [
            _smart_home_item_label(
                item, builtin_labels, saved_search_names, text, mode_labels
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
                state, saved_search_names, text, mode_labels, dialog
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
            mode_labels,
            dialog,
        )


def show_smart_home_layout_editor(
    items,
    builtin_labels: Dict[str, str],
    saved_search_names: Dict[int, str],
    text: SmartHomeEditorText,
    xbmcgui_module=None,
):
    """Edit built-in and smart rows with persistent actions on the right.

    The XML-backed editor keeps Save, Defaults and Cancel out of the scrolling
    content list. Standard Kodi select dialogs remain as a safe fallback and for
    the smaller row/action choices.
    """

    from .preferences import SMART_HOME_MODES

    custom_dialog = xbmcgui_module is None
    if xbmcgui_module is None:
        import xbmcgui as xbmcgui_module  # type: ignore

    dialog = xbmcgui_module.Dialog()
    state = SmartHomeLayoutState(items)
    mode_labels = {
        "poster": text.poster,
        "square": text.square,
        "landscape": text.landscape,
    }
    selected_index = 0

    while custom_dialog:
        rows = [
            _smart_home_item_label(
                item, builtin_labels, saved_search_names, text, mode_labels
            )
            for item in state.items
        ]
        rows.append(text.add_collection)
        try:
            selection = show_action_list_dialog(
                text.heading,
                rows,
                (
                    ("cancel", text.cancel),
                    ("save", text.save),
                    ("defaults", text.defaults),
                ),
                selected_index=selected_index,
            )
        except ActionListDialogUnavailable:
            custom_dialog = False
            break

        if selection is None:
            return None
        kind, value = selection
        if kind == "action":
            if value == "cancel":
                return None
            if value == "save":
                return state.snapshot()
            if value == "defaults":
                state.reset()
                selected_index = 0
                continue
        if kind != "row":
            continue

        selected_index = int(value)
        if selected_index == len(state.items):
            _add_smart_home_collection(
                state, saved_search_names, text, mode_labels, dialog
            )
            selected_index = min(selected_index, len(state.items))
            continue
        selected_index = _edit_smart_home_row(
            state,
            selected_index,
            builtin_labels,
            saved_search_names,
            text,
            mode_labels,
            dialog,
        )

    return _show_smart_home_fallback(
        state,
        builtin_labels,
        saved_search_names,
        text,
        mode_labels,
        dialog,
    )
