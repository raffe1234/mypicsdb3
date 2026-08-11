from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence, Tuple

from .action_list_dialog import ActionListDialogUnavailable, show_action_list_dialog
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

    def _main_rows(self) -> Tuple[List[str], int]:
        rule_count = len(self.draft.rules)
        rows = [
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
        rows.extend(self._rule_label(rule) for rule in self.draft.rules)
        add_index = len(rows)
        rows.extend(
            [
                self.text(32747, "Add criterion"),
                self.text(32748, "Preview results"),
            ]
        )
        assert add_index == 3 + rule_count
        return rows, add_index

    def run(self) -> Optional[SmartFilterResult]:
        custom_dialog = True
        selected_index = 0
        while True:
            rows, add_index = self._main_rows()
            selected = -1
            save_requested = False

            if custom_dialog:
                try:
                    selection = show_action_list_dialog(
                        self.text(32741, "Smart filter editor"),
                        rows,
                        (
                            ("cancel", self.text(32750, "Cancel")),
                            ("save", self.text(32749, "Save smart collection")),
                        ),
                        selected_index=selected_index,
                    )
                except ActionListDialogUnavailable:
                    custom_dialog = False
                    continue

                if selection is None:
                    return None
                kind, value = selection
                if kind == "action":
                    if value == "cancel":
                        return None
                    save_requested = value == "save"
                elif kind == "row":
                    selected = int(value)
                    selected_index = selected
            else:
                # Kodi's native select dialog already displays Cancel. Keep only
                # the primary Save action in the scrolling fallback list.
                options = rows + [self.text(32749, "Save smart collection")]
                selected = self.dialog.select(
                    self.text(32741, "Smart filter editor"),
                    options,
                )
                if selected < 0:
                    return None
                save_requested = selected == len(rows)

            if save_requested:
                result = self._save_result()
                if result is not None:
                    return result
                continue
            if selected == 0:
                self.draft.match = "any" if self.draft.match == "all" else "all"
                continue
            if selected == 1:
                self._choose_sort()
                continue
            if selected == 2:
                self.draft.apply_min_rating = not self.draft.apply_min_rating
                continue
            rule_count = len(self.draft.rules)
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

    @staticmethod
    def _rule_core(payload: Optional[RulePayload]) -> Tuple[RulePayload, bool]:
        """Return the editable rule and whether it is wrapped in a NOT group.

        Query Model v1 already supports negated groups. The editor uses a
        single-child negated group to express user-facing ``is not`` without
        adding a second set of SQL operators or changing the Query Model
        version.
        """
        if not payload:
            return {}, False
        if (
            payload.get("type") == "group"
            and bool(payload.get("negated"))
            and payload.get("match", "all") == "all"
        ):
            children = payload.get("children")
            if isinstance(children, list) and len(children) == 1 and isinstance(children[0], dict):
                child = children[0]
                if child.get("type") == "rule":
                    return child, True
        return payload, False

    @staticmethod
    def _wrap_rule(rule: RulePayload, negated: bool = False) -> RulePayload:
        if not negated:
            return rule
        return {
            "type": "group",
            "match": "all",
            "negated": True,
            "children": [rule],
        }

    def _choose_operator(
        self,
        heading: str,
        options: Sequence[Tuple[str, str]],
        existing: Optional[RulePayload],
        *,
        default: str,
    ) -> Optional[str]:
        core, negated = self._rule_core(existing)
        current = str(core.get("operator") or default)
        if negated and current in {"eq", "contains_tokens"}:
            current = "not_eq"
        preselect = next((index for index, item in enumerate(options) if item[0] == current), 0)
        selected = self.dialog.select(heading, [item[1] for item in options], preselect=preselect)
        if selected < 0:
            return None
        return options[selected][0]

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
            ("extension", self.text(32875, "File extension")),
            ("mime_type", self.text(32931, "MIME type")),
            ("country", self.text(32876, "Country")),
            ("state", self.text(32877, "State or region")),
            ("city", self.text(32878, "City")),
            ("sublocation", self.text(32879, "Sublocation")),
            ("aspect", self.text(32880, "Image shape")),
        )
        preselect = -1
        if existing is not None:
            existing_rule, _negated = self._rule_core(existing)
            existing_field = str(existing_rule.get("field") or "")
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
        return editor(existing if existing is not None and existing_field == field_name else None)

    def _rule_text(self, existing: Optional[RulePayload]) -> Optional[RulePayload]:
        core, negated = self._rule_core(existing)
        operator = self._choose_operator(
            self.text(32751, "Text contains words"),
            (
                ("contains_tokens", self.text(32932, "Contains")),
                ("not_eq", self.text(32933, "Does not contain")),
            ),
            existing,
            default="contains_tokens",
        )
        if operator is None:
            return None
        default = str(core.get("value") or "")
        value = self.dialog.input(self.text(32765, "Filter text"), defaultt=default)
        if not value:
            return None
        rule = {"type": "rule", "field": "text", "operator": "contains_tokens", "value": value}
        return self._wrap_rule(rule, negated=(operator == "not_eq"))

    def _rule_taken_date(self, existing: Optional[RulePayload]) -> Optional[RulePayload]:
        core, _negated = self._rule_core(existing)
        operator = self._choose_operator(
            self.text(32934, "Date"),
            (
                ("between", self.text(32935, "Is between")),
                ("is_not_null", self.text(32936, "Exists")),
                ("is_null", self.text(32937, "Missing")),
            ),
            existing,
            default="between",
        )
        if operator is None:
            return None
        if operator in {"is_null", "is_not_null"}:
            return {"type": "rule", "field": "taken_date", "operator": operator}
        start = str(core.get("from") or "")
        end = str(core.get("to") or "")
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
        core, _negated = self._rule_core(existing)
        operator = self._choose_operator(
            self.text(32924, "Rating"),
            (
                ("gte", self.text(32938, "At least")),
                ("lte", self.text(32939, "At most")),
                ("eq", self.text(32940, "Exactly")),
                ("between", self.text(32935, "Is between")),
                ("is_not_null", self.text(32936, "Exists")),
                ("is_null", self.text(32937, "Missing")),
            ),
            existing,
            default="gte",
        )
        if operator is None:
            return None
        if operator in {"is_null", "is_not_null"}:
            return {"type": "rule", "field": "rating", "operator": operator}
        if operator == "between":
            current_from = int(core.get("from") or 1)
            current_to = int(core.get("to") or 5)
            start = self.dialog.select(
                self.text(32941, "Minimum rating"),
                [str(value) for value in range(0, 6)],
                preselect=max(0, min(5, current_from)),
            )
            if start < 0:
                return None
            end = self.dialog.select(
                self.text(32942, "Maximum rating"),
                [str(value) for value in range(0, 6)],
                preselect=max(0, min(5, current_to)),
            )
            if end < 0:
                return None
            candidate = {"type": "rule", "field": "rating", "operator": "between", "from": start, "to": end}
            return candidate if self._validate_candidate(candidate) else None
        current = int(core.get("value") if core.get("value") is not None else 1)
        selected = self.dialog.select(
            self.text(32924, "Rating"),
            [str(value) for value in range(0, 6)],
            preselect=max(0, min(5, current)),
        )
        if selected < 0:
            return None
        return {"type": "rule", "field": "rating", "operator": operator, "value": selected}

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
        core, _negated = self._rule_core(existing)
        operator = self._choose_operator(
            self.text(32755, "Picture source"),
            (("eq", self.text(32943, "Is")), ("not_eq", self.text(32944, "Is not"))),
            existing,
            default="eq",
        )
        if operator is None:
            return None
        rows = list(self.catalog.get_sources())
        if not rows:
            self._show_message(self.text(32755, "Picture source"), self.text(32766, "No values available"))
            return None
        current = int(core.get("value") or 0)
        preselect = next((index for index, row in enumerate(rows) if int(_value(row, "id", 0)) == current), -1)
        selected = self.dialog.select(
            self.text(32755, "Picture source"),
            [str(_value(row, "label", _value(row, "uri", ""))) for row in rows],
            preselect=preselect,
        )
        if selected < 0:
            return None
        rule = {"type": "rule", "field": "source", "operator": "eq", "value": int(_value(rows[selected], "id"))}
        return self._wrap_rule(rule, negated=(operator == "not_eq"))

    def _rule_camera(self, existing: Optional[RulePayload]) -> Optional[RulePayload]:
        core, _negated = self._rule_core(existing)
        operator = self._choose_operator(
            self.text(32756, "Camera"),
            (
                ("eq", self.text(32943, "Is")),
                ("not_eq", self.text(32944, "Is not")),
                ("is_not_null", self.text(32936, "Exists")),
                ("is_null", self.text(32937, "Missing")),
            ),
            existing,
            default="eq",
        )
        if operator is None:
            return None
        if operator in {"is_null", "is_not_null"}:
            return {"type": "rule", "field": "camera", "operator": operator}
        rows = list(self.catalog.cameras())
        if not rows:
            self._show_message(self.text(32756, "Camera"), self.text(32766, "No values available"))
            return None
        current = core.get("value") or {}
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
        rule = {"type": "rule", "field": "camera", "operator": "eq", "value": value}
        return self._wrap_rule(rule, negated=(operator == "not_eq"))

    def _rule_keyword(self, existing: Optional[RulePayload]) -> Optional[RulePayload]:
        core, _negated = self._rule_core(existing)
        operator = self._choose_operator(
            self.text(32757, "Keyword"),
            (
                ("eq", self.text(32943, "Is")),
                ("not_eq", self.text(32944, "Is not")),
                ("is_not_null", self.text(32936, "Exists")),
                ("is_null", self.text(32937, "Missing")),
            ),
            existing,
            default="eq",
        )
        if operator is None:
            return None
        if operator in {"is_null", "is_not_null"}:
            return {"type": "rule", "field": "keyword", "operator": operator}
        rows = list(self.catalog.tags())
        if not rows:
            self._show_message(self.text(32757, "Keyword"), self.text(32766, "No values available"))
            return None
        current = str(core.get("value") or "").casefold()
        names = [str(_value(row, "name", "")) for row in rows]
        preselect = next((index for index, name in enumerate(names) if name.casefold() == current), -1)
        selected = self.dialog.select(self.text(32757, "Keyword"), names, preselect=preselect)
        if selected < 0:
            return None
        rule = {"type": "rule", "field": "keyword", "operator": "eq", "value": names[selected]}
        return self._wrap_rule(rule, negated=(operator == "not_eq"))

    def _rule_media_type(self, existing: Optional[RulePayload]) -> Optional[RulePayload]:
        core, _negated = self._rule_core(existing)
        operator = self._choose_operator(
            self.text(32758, "Media type"),
            (("eq", self.text(32943, "Is")), ("not_eq", self.text(32944, "Is not"))),
            existing,
            default="eq",
        )
        if operator is None:
            return None
        current = str(core.get("value") or "picture")
        selected = self.dialog.select(
            self.text(32758, "Media type"),
            [self.text(32759, "Pictures"), self.text(32760, "Videos")],
            preselect=1 if current == "video" else 0,
        )
        if selected < 0:
            return None
        rule = {
            "type": "rule",
            "field": "media_type",
            "operator": "eq",
            "value": "video" if selected == 1 else "picture",
        }
        return self._wrap_rule(rule, negated=(operator == "not_eq"))

    def _facet_rows(self, field_name: str, existing: Optional[RulePayload]) -> List[Any]:
        original = self.draft.rules
        try:
            if self.draft.match == "all" and existing is not None:
                self.draft.rules = [rule for rule in original if rule is not existing]
            elif self.draft.match == "any":
                # An added OR criterion can expand beyond the current matches, so
                # show values from the full validated base selection instead of
                # hiding values that do not already satisfy another OR branch.
                self.draft.rules = []
            query = self.build_query()
            return list(self.catalog.query_facet_counts(query, field_name, 200))
        except (QueryValidationError, ValueError, RuntimeError) as exc:
            self._show_message(self.text(32741, "Smart filter editor"), str(exc))
            return []
        finally:
            self.draft.rules = original

    def _rule_scalar_facet(
        self,
        field_name: str,
        heading: str,
        existing: Optional[RulePayload],
        prefix: str = "",
        allow_presence: bool = False,
    ) -> Optional[RulePayload]:
        core, _negated = self._rule_core(existing)
        operators: List[Tuple[str, str]] = [
            ("eq", self.text(32943, "Is")),
            ("not_eq", self.text(32944, "Is not")),
        ]
        if allow_presence:
            operators.extend(
                [
                    ("is_not_null", self.text(32936, "Exists")),
                    ("is_null", self.text(32937, "Missing")),
                ]
            )
        operator = self._choose_operator(heading, operators, existing, default="eq")
        if operator is None:
            return None
        if operator in {"is_null", "is_not_null"}:
            return {"type": "rule", "field": field_name, "operator": operator}
        rows = self._facet_rows(field_name, existing)
        if not rows:
            self._show_message(heading, self.text(32766, "No values available"))
            return None
        current = str(core.get("value") or "")
        values = [str(_value(row, "value", "") or "") for row in rows]
        labels = [
            self.text(32884, "%s (%d items)")
            % (prefix + value, int(_value(row, "picture_count", 0) or 0))
            for value, row in zip(values, rows)
        ]
        preselect = values.index(current) if current in values else -1
        selected = self.dialog.select(heading, labels, preselect=preselect)
        if selected < 0:
            return None
        rule = {"type": "rule", "field": field_name, "operator": "eq", "value": values[selected]}
        return self._wrap_rule(rule, negated=(operator == "not_eq"))

    def _rule_extension(self, existing: Optional[RulePayload]) -> Optional[RulePayload]:
        return self._rule_scalar_facet(
            "extension", self.text(32875, "File extension"), existing, prefix="."
        )

    def _rule_mime_type(self, existing: Optional[RulePayload]) -> Optional[RulePayload]:
        return self._rule_scalar_facet(
            "mime_type", self.text(32931, "MIME type"), existing, allow_presence=True
        )

    def _rule_country(self, existing: Optional[RulePayload]) -> Optional[RulePayload]:
        return self._rule_scalar_facet("country", self.text(32876, "Country"), existing, allow_presence=True)

    def _rule_state(self, existing: Optional[RulePayload]) -> Optional[RulePayload]:
        return self._rule_scalar_facet("state", self.text(32877, "State or region"), existing, allow_presence=True)

    def _rule_city(self, existing: Optional[RulePayload]) -> Optional[RulePayload]:
        return self._rule_scalar_facet("city", self.text(32878, "City"), existing, allow_presence=True)

    def _rule_sublocation(self, existing: Optional[RulePayload]) -> Optional[RulePayload]:
        return self._rule_scalar_facet("sublocation", self.text(32879, "Sublocation"), existing, allow_presence=True)

    def _rule_aspect(self, existing: Optional[RulePayload]) -> Optional[RulePayload]:
        core, _negated = self._rule_core(existing)
        operator = self._choose_operator(
            self.text(32880, "Image shape"),
            (("eq", self.text(32943, "Is")), ("not_eq", self.text(32944, "Is not"))),
            existing,
            default="eq",
        )
        if operator is None:
            return None
        values = ("landscape", "portrait", "square")
        labels = [
            self.text(32881, "Landscape"),
            self.text(32882, "Portrait"),
            self.text(32883, "Square"),
        ]
        current = str(core.get("value") or "landscape")
        preselect = values.index(current) if current in values else 0
        selected = self.dialog.select(self.text(32880, "Image shape"), labels, preselect=preselect)
        if selected < 0:
            return None
        rule = {"type": "rule", "field": "aspect", "operator": "eq", "value": values[selected]}
        return self._wrap_rule(rule, negated=(operator == "not_eq"))

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
        core, negated = self._rule_core(rule)
        field_name = str(core.get("field") or "")
        operator = str(core.get("operator") or "")
        relation = self.text(32944, "Is not") if negated else self.text(32943, "Is")
        if operator == "is_null":
            relation = self.text(32937, "Missing")
        elif operator == "is_not_null":
            relation = self.text(32936, "Exists")
        if field_name == "text":
            label = self.text(32933, "Does not contain") if negated else self.text(32932, "Contains")
            return "%s: %s" % (label, core.get("value", ""))
        if field_name == "taken_date":
            if operator in {"is_null", "is_not_null"}:
                return "%s: %s" % (self.text(32934, "Date"), relation)
            return "%s: %s – %s" % (self.text(32752, "Date range"), core.get("from", ""), core.get("to", ""))
        if field_name == "rating":
            if operator in {"is_null", "is_not_null"}:
                return "%s: %s" % (self.text(32924, "Rating"), relation)
            if operator == "between":
                return "%s: %s–%s" % (self.text(32924, "Rating"), core.get("from", ""), core.get("to", ""))
            rating_relation = {
                "gte": self.text(32938, "At least"),
                "lte": self.text(32939, "At most"),
                "eq": self.text(32940, "Exactly"),
            }.get(operator, operator)
            return "%s: %s %s" % (self.text(32924, "Rating"), rating_relation, core.get("value", ""))
        if field_name == "favorite":
            return self.text(32761, "Favorites only") if core.get("value") else self.text(32762, "Not favorites")
        if field_name == "source":
            source_id = int(core.get("value") or 0)
            source = next((row for row in self.catalog.get_sources() if int(_value(row, "id", 0)) == source_id), None)
            return "%s: %s %s" % (self.text(32755, "Picture source"), relation, _value(source, "label", source_id))
        if field_name == "camera":
            if operator in {"is_null", "is_not_null"}:
                return "%s: %s" % (self.text(32756, "Camera"), relation)
            return "%s: %s %s" % (self.text(32756, "Camera"), relation, self._camera_label(core.get("value") or {}))
        if field_name == "keyword":
            if operator in {"is_null", "is_not_null"}:
                return "%s: %s" % (self.text(32757, "Keyword"), relation)
            return "%s: %s %s" % (self.text(32757, "Keyword"), relation, core.get("value", ""))
        if field_name == "media_type":
            label = self.text(32760, "Videos") if core.get("value") == "video" else self.text(32759, "Pictures")
            return "%s: %s %s" % (self.text(32758, "Media type"), relation, label)
        facet_labels = {
            "extension": self.text(32875, "File extension"),
            "mime_type": self.text(32931, "MIME type"),
            "country": self.text(32876, "Country"),
            "state": self.text(32877, "State or region"),
            "city": self.text(32878, "City"),
            "sublocation": self.text(32879, "Sublocation"),
        }
        if field_name in facet_labels:
            if operator in {"is_null", "is_not_null"}:
                return "%s: %s" % (facet_labels[field_name], relation)
            value = str(core.get("value") or "")
            if field_name == "extension":
                value = "." + value.lstrip(".")
            return "%s: %s %s" % (facet_labels[field_name], relation, value)
        if field_name == "aspect":
            aspect_labels = {
                "landscape": self.text(32881, "Landscape"),
                "portrait": self.text(32882, "Portrait"),
                "square": self.text(32883, "Square"),
            }
            return "%s: %s" % (
                self.text(32880, "Image shape"),
                "%s %s" % (
                    relation,
                    aspect_labels.get(str(core.get("value") or ""), str(core.get("value") or "")),
                ),
            )
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
