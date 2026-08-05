from __future__ import annotations

import traceback
from typing import Optional, Sequence, Tuple


class ActionListDialogUnavailable(RuntimeError):
    """Raised when Kodi cannot load the XML-backed action-list dialog."""


def show_action_list_dialog(
    heading: str,
    rows: Sequence[str],
    actions: Sequence[Tuple[str, str]],
    selected_index: int = 0,
):
    """Show a dynamic list with up to three persistent buttons on the right.

    Returns ``("row", index)`` for a selected list row, ``("action", key)``
    for a right-hand button, or ``None`` when the dialog is dismissed.
    ``ActionListDialogUnavailable`` lets callers fall back to ordinary Kodi
    select dialogs if the XML window cannot be created.
    """

    if len(actions) > 3:
        raise ValueError("The action-list dialog supports at most three actions")

    try:
        import xbmc  # type: ignore
        import xbmcaddon  # type: ignore
        import xbmcgui  # type: ignore
    except ImportError as exc:  # pragma: no cover - Kodi-only path
        raise ActionListDialogUnavailable(str(exc)) from exc

    action_controls = (1401, 1402, 1403)
    back_actions = {9, 10, 92}

    class ActionListDialog(xbmcgui.WindowXMLDialog):
        def configure(self) -> None:
            self.heading = str(heading)
            self.rows = [str(value) for value in rows]
            self.actions = list(actions)
            self.selected_index = max(0, int(selected_index or 0))
            self.result = None
            self._ready = False

        def onInit(self) -> None:  # noqa: N802 - Kodi callback name
            try:
                self.getControl(100).setLabel(self.heading)
                list_control = self.getControl(1000)
                list_control.reset()
                for label in self.rows:
                    list_control.addItem(xbmcgui.ListItem(label=label))

                for offset, control_id in enumerate(action_controls):
                    control = self.getControl(control_id)
                    visible = offset < len(self.actions)
                    control.setVisible(visible)
                    control.setEnabled(visible)
                    if visible:
                        control.setLabel(self.actions[offset][1])

                if self.rows:
                    index = min(self.selected_index, len(self.rows) - 1)
                    list_control.selectItem(index)
                    self.setFocusId(1000)
                elif self.actions:
                    self.setFocusId(action_controls[0])
                self._ready = True
            except Exception:
                xbmc.log(
                    "MyPicsDB 3 action-list dialog onInit failed:\n%s"
                    % traceback.format_exc(),
                    xbmc.LOGERROR,
                )
                self.close()

        def onClick(self, control_id: int) -> None:  # noqa: N802 - Kodi callback name
            if control_id == 1000:
                index = self.getControl(1000).getSelectedPosition()
                if 0 <= index < len(self.rows):
                    self.result = ("row", index)
                    self.close()
                return
            if control_id in action_controls:
                offset = action_controls.index(control_id)
                if offset < len(self.actions):
                    self.result = ("action", self.actions[offset][0])
                    self.close()

        def onAction(self, action) -> None:  # noqa: N802 - Kodi callback name
            if action.getId() in back_actions:
                self.close()

    dialog = None
    try:
        addon_path = xbmcaddon.Addon().getAddonInfo("path")
        dialog = ActionListDialog(
            "action_list_dialog.xml",
            addon_path,
            "Default",
            "1080i",
        )
        dialog.configure()
        dialog.doModal()
        if not getattr(dialog, "_ready", False):
            raise ActionListDialogUnavailable("The XML action-list dialog did not initialize")
        return dialog.result
    except ActionListDialogUnavailable:
        raise
    except Exception as exc:
        xbmc.log(
            "MyPicsDB 3 XML action-list dialog failed:\n%s"
            % traceback.format_exc(),
            xbmc.LOGERROR,
        )
        raise ActionListDialogUnavailable(str(exc)) from exc
    finally:
        if dialog is not None:
            del dialog
