from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence, Tuple

from .query_model import PictureQuery, QueryValidationError, parse_picture_query


RulePayload = Dict[str, Any]
Localize = Callable[[int, str], str]


@dataclass
class SmartFilterDraft:
    match: str = "all"
    rules: List[RulePayload] = field(default_factory=list)
    sort_field: str = "taken_at"
    sort_direction: str = "desc"
    apply_min_rating: bool = True


@dataclass(frozen=True)
class SmartFilterResult:
    name: str
    query: PictureQuery


def _value(row: Any, key: str, default: Any = None) -> Any:
    if isinstance(row, Mapping):
        return row.get(key, default)
    return getattr(row, key, default)


class SmartFilterEditor:
    """Small Kodi-dialog editor that produces only validated Query Model data."""

    def __init__(self, catalog: Any, dialog: Any, localize: Localize):
        self.catalog = catalog
        self.dialog = dialog
        self.text = localize
        self.draft = SmartFilterDraft()

    def run(self) -> Optional[SmartFilterResult]:
        while True:
            rule_count = len(self.draft.rules)
            options = [
                "%s: %s" % (
                    self.text(32742, "Match"),
                    self.text(32743, "All criteria")
                    if self.draft.match == "all"
                    else self.text(32744, "Any criterion"),
                ),
                "%s: %s" % (self.text(32745, "Sort"), self._sort_label()),
                "%s: %s" % (
                    self.text(32746, "Use global minimum rating"),
                    self.text(32775, "Yes")
                    if self.draft.apply_min_rating
                    else self.text(32776, "No"),
                ),
            ]
            options.extend(self._rule_label(rule) for rule in self.draft.rules)
            add_index = len(options)
            options.extend(
                [
                    self.text(32747, "Add criterion"),
                    self.text(32748, "Preview results"),
                    self.text(32749, "Save smart collection"),
                    self.text(32750, "Cancel"),
                ]
            )
            selected = self.dialog.select(
                self.text(32741, "Smart filter editor"),
                options,
            )
            if selected < 0 or selected == add_index + 3:
                return None
            if selected == 0:
                self.draft.match = "any" if self.draft.match == "all" else "all"
                continue
            if selected == 1:
                self._choose_sort()
                continue
            if selected == 2:
                self.draft.apply_min_rating = not self.draft.apply_min_rating
                continue
            if 3 <= selected < 3 + rule_count:
                self._edit_rule(selected - 3)
                continue
            if selected == add_index:
                rule = self._choose_rule()
                if rule is not None:
                    self.draft.rules.append(rule)
                continue
            if selected == add_index + 1:
                self._preview()
                continue
            if selected == add_index + 2:
                result = self._save_result()
                if result is not None:
                    return result

    def build_query(self) -> PictureQuery:
        return parse_picture_query(
            {
                "version": 1,
                "root": {
                    "type": "group",
                    "match": self.draft.match,
                    "negated": False,
                    "children": list(self.draft.rules),
                },
                "sort": [
                    {
                        "field": self.draft.sort_field,
                        "direction": self.draft.sort_direction,
                    }
                ],
                "scope": {
                    "source_ids": [],
                    "include_missing": False,
                    "include_excluded": False,
                },
                "default_policy": {
                    "apply_min_rating": self.draft.apply_min_rating,
                },
            }
        )

    def _show_message(self, heading: str, message: str) -> None:
        viewer = getattr(self.dialog, "textviewer", None)
        if callable(viewer):
            viewer(heading, message)
            return
        ok = getattr(self.dialog, "ok", None)
        if callable(ok):
            ok(heading, message)

    def _save_result(self) -> Optional[SmartFilterResult]:
        try:
            query = self.build_query()
            total = int(self.catalog.count_query_pictures(query))
        except (QueryValidationError, ValueError, RuntimeError) as exc:
            self._show_message(
                self.text(32770, "Could not save smart collection"),
                str(exc),
            )
            return None
        if total == 0:
            confirm = getattr(self.dialog, "yesno", None)
            if callable(confirm) and not confirm(
                self.text(32749, "Save smart collection"),
                self.text(32771, "No media matches. Save anyway?"),
            ):
                return None
        name = self.dialog.input(self.text(32768, "Smart collection name"))
        if not name:
            return None
        return SmartFilterResult(name=str(name), query=query)

    def _preview(self) -> None:
        try:
            query = self.build_query()
            total = int(self.catalog.count_query_pictures(query))
            rows = self.catalog.query_pictures(query, min(10, max(1, total))) if total else []
        except (QueryValidationError, ValueError, RuntimeError) as exc:
            self._show_message(self.text(32748, "Preview results"), str(exc))
            return
        lines = [self.text(32767, "%d matching media items") % total]
        lines.extend(
            "%d. %s" % (index, str(_value(row, "filename", "") or _value(row, "uri", "")))
            for index, row in enumerate(rows, start=1)
        )
        self._show_message(self.text(32748, "Preview results"), "\n".join(lines))

    def _edit_rule(self, index: int) -> None:
        selected = self.dialog.select(
            self._rule_label(self.draft.rules[index]),
            [
                self.text(32772, "Edit criterion"),
                self.text(32773, "Remove criterion"),
                self.text(32750, "Cancel"),
            ],
        )
        if selected == 1:
            del self.draft.rules[index]
            return
        if selected != 0:
            return
        replacement = self._choose_rule(self.draft.rules[index])
        if replacement is not None:
            self.draft.rules[index] = replacement

    def _choose_rule(self, existing: Optional[RulePayload] = None) -> Optional[RulePayload]:
        types: Sequence[Tuple[str, str]] = (
            ("text", self.text(32751, "Text contains words")),
            ("taken_date", self.text(32752, "Date range")),
            ("rating", self.text(32753, "Minimum rating")),
            ("favorite", self.text(32754, "Favorite")),
            ("source", self.text(32755, "Picture source")),
            ("camera", self.text(32756, "Camera")),
            ("keyword", self.text(32757, "Keyword")),
            ("media_type", self.text(32758, "Media type")),
        )
        preselect = -1
        if existing is not None:
            existing_field = str(existing.get("field") or "")
            preselect = next(
                (index for index, item in enumerate(types) if item[0] == existing_field),
                -1,
            )
        selected = self.dialog.select(
            self.text(32747, "Add criterion"),
            [item[1] for item in types],
            preselect=preselect,
        )
        if selected < 0:
            return None
        field_name = types[selected][0]
        editor = getattr(self, "_rule_" + field_name)
        return editor(existing if existing and existing.get("field") == field_name else None)

    def _rule_text(self, existing: Optional[RulePayload]) -> Optional[RulePayload]:
        default = str((existing or {}).get("value") or "")
        value = self.dialog.input(self.text(32765, "Filter text"), defaultt=default)
        if not value:
            return None
        return {"type": "rule", "field": "text", "operator": "contains_tokens", "value": value}

    def _rule_taken_date(self, existing: Optional[RulePayload]) -> Optional[RulePayload]:
        start = str((existing or {}).get("from") or "")
        end = str((existing or {}).get("to") or "")
        start = self.dialog.input(self.text(32763, "From date (YYYY-MM-DD)"), defaultt=start)
        if not start:
            return None
        end = self.dialog.input(self.text(32764, "To date (YYYY-MM-DD)"), defaultt=end)
        if not end:
            return None
        candidate = {
            "type": "rule",
            "field": "taken_date",
            "operator": "between",
            "from": start,
            "to": end,
        }
        if not self._validate_candidate(candidate):
            return None
        return candidate

    def _rule_rating(self, existing: Optional[RulePayload]) -> Optional[RulePayload]:
        current = int((existing or {}).get("value") or 1)
        selected = self.dialog.select(
            self.text(32753, "Minimum rating"),
            [str(value) for value in range(1, 6)],
            preselect=max(0, min(4, current - 1)),
        )
        if selected < 0:
            return None
        return {"type": "rule", "field": "rating", "operator": "gte", "value": selected + 1}

    def _rule_favorite(self, existing: Optional[RulePayload]) -> Optional[RulePayload]:
        current = bool((existing or {}).get("value", True))
        selected = self.dialog.select(
            self.text(32754, "Favorite"),
            [self.text(32761, "Favorites only"), self.text(32762, "Not favorites")],
            preselect=0 if current else 1,
        )
        if selected < 0:
            return None
        return {"type": "rule", "field": "favorite", "operator": "eq", "value": selected == 0}

    def _rule_source(self, existing: Optional[RulePayload]) -> Optional[RulePayload]:
        rows = list(self.catalog.get_sources())
        if not rows:
            self._show_message(self.text(32755, "Picture source"), self.text(32766, "No values available"))
            return None
        current = int((existing or {}).get("value") or 0)
        preselect = next((index for index, row in enumerate(rows) if int(_value(row, "id", 0)) == current), -1)
        selected = self.dialog.select(
            self.text(32755, "Picture source"),
            [str(_value(row, "label", _value(row, "uri", ""))) for row in rows],
            preselect=preselect,
        )
        if selected < 0:
            return None
        return {"type": "rule", "field": "source", "operator": "eq", "value": int(_value(rows[selected], "id"))}

    def _rule_camera(self, existing: Optional[RulePayload]) -> Optional[RulePayload]:
        rows = list(self.catalog.cameras())
        if not rows:
            self._show_message(self.text(32756, "Camera"), self.text(32766, "No values available"))
            return None
        current = (existing or {}).get("value") or {}
        labels = [self._camera_label(row) for row in rows]
        current_label = self._camera_label(current)
        preselect = labels.index(current_label) if current_label in labels else -1
        selected = self.dialog.select(self.text(32756, "Camera"), labels, preselect=preselect)
        if selected < 0:
            return None
        row = rows[selected]
        value = {
            key: str(_value(row, source_key, "") or "")
            for key, source_key in (("make", "camera_make"), ("model", "camera_model"))
            if str(_value(row, source_key, "") or "")
        }
        return {"type": "rule", "field": "camera", "operator": "eq", "value": value}

    def _rule_keyword(self, existing: Optional[RulePayload]) -> Optional[RulePayload]:
        rows = list(self.catalog.tags())
        if not rows:
            self._show_message(self.text(32757, "Keyword"), self.text(32766, "No values available"))
            return None
        current = str((existing or {}).get("value") or "").casefold()
        names = [str(_value(row, "name", "")) for row in rows]
        preselect = next((index for index, name in enumerate(names) if name.casefold() == current), -1)
        selected = self.dialog.select(self.text(32757, "Keyword"), names, preselect=preselect)
        if selected < 0:
            return None
        return {"type": "rule", "field": "keyword", "operator": "eq", "value": names[selected]}

    def _rule_media_type(self, existing: Optional[RulePayload]) -> Optional[RulePayload]:
        current = str((existing or {}).get("value") or "picture")
        selected = self.dialog.select(
            self.text(32758, "Media type"),
            [self.text(32759, "Pictures"), self.text(32760, "Videos")],
            preselect=1 if current == "video" else 0,
        )
        if selected < 0:
            return None
        return {
            "type": "rule",
            "field": "media_type",
            "operator": "eq",
            "value": "video" if selected == 1 else "picture",
        }

    def _choose_sort(self) -> None:
        options: Sequence[Tuple[str, str, str]] = (
            ("taken_at", "desc", self.text(32777, "Newest taken first")),
            ("taken_at", "asc", self.text(32778, "Oldest taken first")),
            ("discovered_at", "desc", self.text(32779, "Recently added first")),
            ("rating", "desc", self.text(32780, "Highest rating first")),
            ("filename", "asc", self.text(32781, "Filename A-Z")),
        )
        current = (self.draft.sort_field, self.draft.sort_direction)
        preselect = next((index for index, item in enumerate(options) if item[:2] == current), 0)
        selected = self.dialog.select(
            self.text(32745, "Sort"),
            [item[2] for item in options],
            preselect=preselect,
        )
        if selected >= 0:
            self.draft.sort_field, self.draft.sort_direction = options[selected][:2]

    def _sort_label(self) -> str:
        labels = {
            ("taken_at", "desc"): self.text(32777, "Newest taken first"),
            ("taken_at", "asc"): self.text(32778, "Oldest taken first"),
            ("discovered_at", "desc"): self.text(32779, "Recently added first"),
            ("rating", "desc"): self.text(32780, "Highest rating first"),
            ("filename", "asc"): self.text(32781, "Filename A-Z"),
        }
        return labels.get((self.draft.sort_field, self.draft.sort_direction), self.draft.sort_field)

    def _rule_label(self, rule: RulePayload) -> str:
        field_name = str(rule.get("field") or "")
        if field_name == "text":
            return "%s: %s" % (self.text(32751, "Text contains words"), rule.get("value", ""))
        if field_name == "taken_date":
            return "%s: %s – %s" % (self.text(32752, "Date range"), rule.get("from", ""), rule.get("to", ""))
        if field_name == "rating":
            return "%s: %s+" % (self.text(32753, "Minimum rating"), rule.get("value", ""))
        if field_name == "favorite":
            return self.text(32761, "Favorites only") if rule.get("value") else self.text(32762, "Not favorites")
        if field_name == "source":
            source_id = int(rule.get("value") or 0)
            source = next((row for row in self.catalog.get_sources() if int(_value(row, "id", 0)) == source_id), None)
            return "%s: %s" % (self.text(32755, "Picture source"), _value(source, "label", source_id))
        if field_name == "camera":
            return "%s: %s" % (self.text(32756, "Camera"), self._camera_label(rule.get("value") or {}))
        if field_name == "keyword":
            return "%s: %s" % (self.text(32757, "Keyword"), rule.get("value", ""))
        if field_name == "media_type":
            label = self.text(32760, "Videos") if rule.get("value") == "video" else self.text(32759, "Pictures")
            return "%s: %s" % (self.text(32758, "Media type"), label)
        return field_name

    @staticmethod
    def _camera_label(row: Any) -> str:
        make = str(_value(row, "camera_make", _value(row, "make", "")) or "")
        model = str(_value(row, "camera_model", _value(row, "model", "")) or "")
        return " ".join(item for item in (make, model) if item).strip()

    def _validate_candidate(self, candidate: RulePayload) -> bool:
        original = list(self.draft.rules)
        self.draft.rules = [candidate]
        try:
            self.build_query()
            return True
        except QueryValidationError as exc:
            self._show_message(self.text(32741, "Smart filter editor"), str(exc))
            return False
        finally:
            self.draft.rules = original
