from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any, Dict, List, Optional, Sequence, Tuple, Union

from .rating_policy import RATING_POLICY_ALL, rating_sql_predicate


QUERY_MODEL_VERSION = 1
MAX_GROUP_DEPTH = 3
MAX_RULES = 50
MAX_LIST_VALUES = 100
MAX_STRING_LENGTH = 512
MAX_SORT_FIELDS = 5


class QueryValidationError(ValueError):
    """Raised when untrusted query-model data is invalid or unsupported."""


@dataclass(frozen=True)
class CameraValue:
    make: Optional[str] = None
    model: Optional[str] = None


@dataclass(frozen=True)
class QueryRule:
    field: str
    operator: str
    value: Any = None


@dataclass(frozen=True)
class QueryGroup:
    match: str
    negated: bool
    children: Tuple["QueryNode", ...]


QueryNode = Union[QueryRule, QueryGroup]


@dataclass(frozen=True)
class QuerySort:
    field: str
    direction: str


@dataclass(frozen=True)
class QueryScope:
    source_ids: Tuple[int, ...] = ()
    include_missing: bool = False
    include_excluded: bool = False


@dataclass(frozen=True)
class QueryDefaultPolicy:
    apply_min_rating: bool = True


@dataclass(frozen=True)
class PictureQuery:
    version: int
    root: QueryGroup
    sort: Tuple[QuerySort, ...]
    scope: QueryScope
    default_policy: QueryDefaultPolicy


@dataclass(frozen=True)
class CompiledPictureQuery:
    where_sql: str
    params: Tuple[Any, ...]
    order_by_sql: str


_SORT_COLUMNS = {
    "taken_at": "p.taken_at",
    "discovered_at": "p.discovered_at",
    "rating": "p.rating",
    "filename": "p.filename",
    "id": "p.id",
}

_FIELD_OPERATORS = {
    "rating": frozenset({"eq", "gte", "lte", "between", "is_null", "is_not_null"}),
    "favorite": frozenset({"eq"}),
    "source": frozenset({"eq", "in"}),
    "album": frozenset({"eq", "in"}),
    "taken_date": frozenset({"between"}),
    "camera": frozenset({"eq"}),
    "keyword": frozenset({"eq", "in"}),
}


def _path_message(path: str, message: str) -> QueryValidationError:
    return QueryValidationError("%s: %s" % (path, message))


def _mapping(value: Any, path: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise _path_message(path, "must be an object")
    return value


def _reject_unknown(value: Mapping[str, Any], allowed: Sequence[str], path: str) -> None:
    unknown = sorted(set(value) - set(allowed))
    if unknown:
        raise _path_message(path, "unknown field(s): %s" % ", ".join(unknown))


def _strict_bool(value: Any, path: str) -> bool:
    if type(value) is not bool:
        raise _path_message(path, "must be a boolean")
    return value


def _strict_int(value: Any, path: str, minimum: Optional[int] = None, maximum: Optional[int] = None) -> int:
    if type(value) is not int:
        raise _path_message(path, "must be an integer")
    if minimum is not None and value < minimum:
        raise _path_message(path, "must be at least %d" % minimum)
    if maximum is not None and value > maximum:
        raise _path_message(path, "must be at most %d" % maximum)
    return value


def _string(value: Any, path: str, maximum: int = MAX_STRING_LENGTH) -> str:
    if not isinstance(value, str):
        raise _path_message(path, "must be a string")
    text = value.strip()
    if not text:
        raise _path_message(path, "must not be empty")
    if len(text) > maximum:
        raise _path_message(path, "must contain at most %d characters" % maximum)
    return text


def _date_string(value: Any, path: str) -> str:
    text = _string(value, path, maximum=10)
    try:
        parsed = date.fromisoformat(text)
    except ValueError as exc:
        raise _path_message(path, "must use YYYY-MM-DD") from exc
    if parsed.isoformat() != text:
        raise _path_message(path, "must use YYYY-MM-DD")
    return text


def _positive_id(value: Any, path: str) -> int:
    return _strict_int(value, path, minimum=1)


def _id_list(value: Any, path: str) -> Tuple[int, ...]:
    if not isinstance(value, list):
        raise _path_message(path, "must be a list")
    if not value:
        raise _path_message(path, "must not be empty")
    if len(value) > MAX_LIST_VALUES:
        raise _path_message(path, "must contain at most %d values" % MAX_LIST_VALUES)
    return tuple(sorted({_positive_id(item, "%s[%d]" % (path, index)) for index, item in enumerate(value)}))


def _keyword_list(value: Any, path: str) -> Tuple[str, ...]:
    if not isinstance(value, list):
        raise _path_message(path, "must be a list")
    if not value:
        raise _path_message(path, "must not be empty")
    if len(value) > MAX_LIST_VALUES:
        raise _path_message(path, "must contain at most %d values" % MAX_LIST_VALUES)
    normalized = {
        _string(item, "%s[%d]" % (path, index), maximum=191).casefold()
        for index, item in enumerate(value)
    }
    return tuple(sorted(normalized))


def _camera_value(value: Any, path: str) -> CameraValue:
    mapping = _mapping(value, path)
    _reject_unknown(mapping, ("make", "model"), path)
    make = _string(mapping["make"], path + ".make") if "make" in mapping else None
    model = _string(mapping["model"], path + ".model") if "model" in mapping else None
    if make is None and model is None:
        raise _path_message(path, "must contain make and/or model")
    return CameraValue(make=make, model=model)


def _parse_rule(value: Any, path: str, rule_counter: List[int]) -> QueryRule:
    mapping = _mapping(value, path)
    _reject_unknown(mapping, ("type", "field", "operator", "value", "from", "to"), path)
    if mapping.get("type") != "rule":
        raise _path_message(path + ".type", "must be 'rule'")
    field = _string(mapping.get("field"), path + ".field", maximum=64)
    operator = _string(mapping.get("operator"), path + ".operator", maximum=32)
    if field not in _FIELD_OPERATORS:
        raise _path_message(path + ".field", "unsupported field %r" % field)
    if operator not in _FIELD_OPERATORS[field]:
        raise _path_message(
            path + ".operator",
            "operator %r is not allowed for field %r" % (operator, field),
        )

    rule_counter[0] += 1
    if rule_counter[0] > MAX_RULES:
        raise _path_message(path, "query contains more than %d rules" % MAX_RULES)

    if operator in {"is_null", "is_not_null"}:
        if any(name in mapping for name in ("value", "from", "to")):
            raise _path_message(path, "%s does not accept a value" % operator)
        return QueryRule(field=field, operator=operator)

    if operator == "between":
        if "value" in mapping:
            raise _path_message(path, "between uses 'from' and 'to', not 'value'")
        if "from" not in mapping or "to" not in mapping:
            raise _path_message(path, "between requires both 'from' and 'to'")
        if field == "rating":
            start = _strict_int(mapping["from"], path + ".from", minimum=0, maximum=5)
            end = _strict_int(mapping["to"], path + ".to", minimum=0, maximum=5)
        elif field == "taken_date":
            start = _date_string(mapping["from"], path + ".from")
            end = _date_string(mapping["to"], path + ".to")
            if date.fromisoformat(end) == date.max:
                raise _path_message(path + ".to", "must be before 9999-12-31")
        else:
            raise _path_message(path + ".operator", "between is not implemented for %r" % field)
        if start > end:
            raise _path_message(path, "'from' must not be greater than 'to'")
        return QueryRule(field=field, operator=operator, value=(start, end))

    if "from" in mapping or "to" in mapping:
        raise _path_message(path, "%s uses 'value', not 'from' or 'to'" % operator)
    if "value" not in mapping:
        raise _path_message(path, "%s requires 'value'" % operator)
    raw = mapping["value"]

    if field == "rating":
        parsed: Any = _strict_int(raw, path + ".value", minimum=0, maximum=5)
    elif field == "favorite":
        parsed = _strict_bool(raw, path + ".value")
    elif field in {"source", "album"}:
        parsed = _id_list(raw, path + ".value") if operator == "in" else _positive_id(raw, path + ".value")
    elif field == "camera":
        parsed = _camera_value(raw, path + ".value")
    elif field == "keyword":
        parsed = _keyword_list(raw, path + ".value") if operator == "in" else _string(raw, path + ".value", maximum=191).casefold()
    else:
        raise _path_message(path + ".field", "unsupported field %r" % field)
    return QueryRule(field=field, operator=operator, value=parsed)


def _parse_group(value: Any, path: str, depth: int, rule_counter: List[int]) -> QueryGroup:
    if depth > MAX_GROUP_DEPTH:
        raise _path_message(path, "query groups may be nested at most %d levels" % MAX_GROUP_DEPTH)
    mapping = _mapping(value, path)
    _reject_unknown(mapping, ("type", "match", "negated", "children"), path)
    if mapping.get("type") != "group":
        raise _path_message(path + ".type", "must be 'group'")
    match = mapping.get("match", "all")
    if match not in {"all", "any"}:
        raise _path_message(path + ".match", "must be 'all' or 'any'")
    negated = _strict_bool(mapping.get("negated", False), path + ".negated")
    raw_children = mapping.get("children", [])
    if not isinstance(raw_children, list):
        raise _path_message(path + ".children", "must be a list")
    children: List[QueryNode] = []
    for index, child in enumerate(raw_children):
        child_path = "%s.children[%d]" % (path, index)
        child_mapping = _mapping(child, child_path)
        child_type = child_mapping.get("type")
        if child_type == "rule":
            children.append(_parse_rule(child_mapping, child_path, rule_counter))
        elif child_type == "group":
            children.append(_parse_group(child_mapping, child_path, depth + 1, rule_counter))
        else:
            raise _path_message(child_path + ".type", "must be 'group' or 'rule'")
    return QueryGroup(match=match, negated=negated, children=tuple(children))


def _parse_sort(value: Any, path: str) -> Tuple[QuerySort, ...]:
    if value is None:
        raw_sort: List[Any] = []
    elif isinstance(value, list):
        raw_sort = value
    else:
        raise _path_message(path, "must be a list")
    if len(raw_sort) > MAX_SORT_FIELDS:
        raise _path_message(path, "must contain at most %d fields" % MAX_SORT_FIELDS)

    parsed: List[QuerySort] = []
    seen = set()
    id_direction: Optional[str] = None
    for index, raw in enumerate(raw_sort):
        item_path = "%s[%d]" % (path, index)
        mapping = _mapping(raw, item_path)
        _reject_unknown(mapping, ("field", "direction"), item_path)
        field = _string(mapping.get("field"), item_path + ".field", maximum=64)
        direction = _string(mapping.get("direction", "asc"), item_path + ".direction", maximum=16).lower()
        if field not in _SORT_COLUMNS:
            raise _path_message(item_path + ".field", "unsupported sort field %r" % field)
        if direction not in {"asc", "desc"}:
            raise _path_message(item_path + ".direction", "must be 'asc' or 'desc'")
        if field in seen:
            raise _path_message(item_path + ".field", "duplicate sort field %r" % field)
        seen.add(field)
        if field == "id":
            id_direction = direction
        else:
            parsed.append(QuerySort(field=field, direction=direction))

    if not parsed and id_direction is None:
        parsed.append(QuerySort(field="taken_at", direction="desc"))
    tie_direction = id_direction or (parsed[-1].direction if parsed else "desc")
    parsed.append(QuerySort(field="id", direction=tie_direction))
    return tuple(parsed)


def _parse_scope(value: Any, path: str) -> QueryScope:
    if value is None:
        mapping: Mapping[str, Any] = {}
    else:
        mapping = _mapping(value, path)
    _reject_unknown(mapping, ("source_ids", "include_missing", "include_excluded"), path)
    raw_source_ids = mapping.get("source_ids", [])
    if not isinstance(raw_source_ids, list):
        raise _path_message(path + ".source_ids", "must be a list")
    if len(raw_source_ids) > MAX_LIST_VALUES:
        raise _path_message(path + ".source_ids", "must contain at most %d values" % MAX_LIST_VALUES)
    source_ids = tuple(sorted({_positive_id(item, "%s.source_ids[%d]" % (path, index)) for index, item in enumerate(raw_source_ids)}))
    include_missing = _strict_bool(mapping.get("include_missing", False), path + ".include_missing")
    include_excluded = _strict_bool(mapping.get("include_excluded", False), path + ".include_excluded")
    if include_excluded:
        raise _path_message(path + ".include_excluded", "is reserved and must be false in query model version 1")
    return QueryScope(
        source_ids=source_ids,
        include_missing=include_missing,
        include_excluded=include_excluded,
    )


def _parse_default_policy(value: Any, path: str) -> QueryDefaultPolicy:
    if value is None:
        mapping: Mapping[str, Any] = {}
    else:
        mapping = _mapping(value, path)
    _reject_unknown(mapping, ("apply_min_rating",), path)
    return QueryDefaultPolicy(
        apply_min_rating=_strict_bool(mapping.get("apply_min_rating", True), path + ".apply_min_rating")
    )


def parse_picture_query(value: Mapping[str, Any]) -> PictureQuery:
    """Validate untrusted query JSON and return a normalized version-1 model."""
    mapping = _mapping(value, "query")
    _reject_unknown(mapping, ("version", "root", "sort", "scope", "default_policy"), "query")
    version = _strict_int(mapping.get("version"), "query.version")
    if version != QUERY_MODEL_VERSION:
        raise _path_message(
            "query.version",
            "unsupported query model version %d (expected %d)" % (version, QUERY_MODEL_VERSION),
        )
    root_value = mapping.get(
        "root",
        {"type": "group", "match": "all", "negated": False, "children": []},
    )
    root = _parse_group(root_value, "query.root", depth=1, rule_counter=[0])
    return PictureQuery(
        version=version,
        root=root,
        sort=_parse_sort(mapping.get("sort"), "query.sort"),
        scope=_parse_scope(mapping.get("scope"), "query.scope"),
        default_policy=_parse_default_policy(mapping.get("default_policy"), "query.default_policy"),
    )


def ensure_picture_query(value: Union[PictureQuery, Mapping[str, Any]]) -> PictureQuery:
    return value if isinstance(value, PictureQuery) else parse_picture_query(value)


def _node_to_dict(node: QueryNode) -> Dict[str, Any]:
    if isinstance(node, QueryGroup):
        return {
            "type": "group",
            "match": node.match,
            "negated": node.negated,
            "children": [_node_to_dict(child) for child in node.children],
        }
    result: Dict[str, Any] = {
        "type": "rule",
        "field": node.field,
        "operator": node.operator,
    }
    if node.operator == "between":
        result["from"], result["to"] = node.value
    elif node.operator not in {"is_null", "is_not_null"}:
        value = node.value
        if isinstance(value, CameraValue):
            value = {
                key: item
                for key, item in (("make", value.make), ("model", value.model))
                if item is not None
            }
        elif isinstance(value, tuple):
            value = list(value)
        result["value"] = value
    return result


def picture_query_to_dict(value: Union[PictureQuery, Mapping[str, Any]]) -> Dict[str, Any]:
    query = ensure_picture_query(value)
    return {
        "version": query.version,
        "root": _node_to_dict(query.root),
        "sort": [
            {"field": item.field, "direction": item.direction}
            for item in query.sort
        ],
        "scope": {
            "source_ids": list(query.scope.source_ids),
            "include_missing": query.scope.include_missing,
            "include_excluded": query.scope.include_excluded,
        },
        "default_policy": {
            "apply_min_rating": query.default_policy.apply_min_rating,
        },
    }


def canonical_picture_query_json(value: Union[PictureQuery, Mapping[str, Any]]) -> str:
    """Return compact, deterministic UTF-8 JSON for hashing or future storage."""
    return json.dumps(
        picture_query_to_dict(value),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _placeholders(values: Sequence[Any]) -> str:
    return ",".join("?" for _ in values)


def _compile_rule(rule: QueryRule) -> Tuple[str, Tuple[Any, ...]]:
    field = rule.field
    operator = rule.operator
    value = rule.value

    if field == "rating":
        column = "p.rating"
        if operator == "is_null":
            return column + " IS NULL", ()
        if operator == "is_not_null":
            return column + " IS NOT NULL", ()
        if operator == "between":
            return column + ">=? AND " + column + "<=?", tuple(value)
        sql_operator = {"eq": "=", "gte": ">=", "lte": "<="}[operator]
        return column + sql_operator + "?", (value,)

    if field == "favorite":
        return "p.favorite=?", (1 if value else 0,)

    if field in {"source", "album"}:
        column = "p.source_id" if field == "source" else "p.folder_id"
        if operator == "eq":
            return column + "=?", (value,)
        return column + " IN (" + _placeholders(value) + ")", tuple(value)

    if field == "taken_date":
        start_text, end_text = value
        start = date.fromisoformat(start_text)
        end_exclusive = date.fromisoformat(end_text) + timedelta(days=1)
        return "p.taken_at>=? AND p.taken_at<?", (
            start.isoformat() + " 00:00:00",
            end_exclusive.isoformat() + " 00:00:00",
        )

    if field == "camera":
        camera: CameraValue = value
        predicates: List[str] = []
        params: List[Any] = []
        if camera.make is not None:
            predicates.append("COALESCE(p.camera_make,'')=?")
            params.append(camera.make)
        if camera.model is not None:
            predicates.append("COALESCE(p.camera_model,'')=?")
            params.append(camera.model)
        return " AND ".join(predicates), tuple(params)

    if field == "keyword":
        if operator == "eq":
            predicate = "t.normalized_name=?"
            params = (value,)
        else:
            predicate = "t.normalized_name IN (" + _placeholders(value) + ")"
            params = tuple(value)
        return (
            "EXISTS (SELECT 1 FROM picture_tags pt "
            "JOIN tags t ON t.id=pt.tag_id "
            "WHERE pt.picture_id=p.id AND %s)" % predicate,
            params,
        )

    raise QueryValidationError("Compiler has no implementation for field %r" % field)


def _compile_group(group: QueryGroup) -> Tuple[str, Tuple[Any, ...]]:
    compiled = [_compile_group(child) if isinstance(child, QueryGroup) else _compile_rule(child) for child in group.children]
    if not compiled:
        sql = "1=1" if group.match == "all" else "1=0"
        params: Tuple[Any, ...] = ()
    else:
        separator = " AND " if group.match == "all" else " OR "
        sql = separator.join("(%s)" % child_sql for child_sql, _ in compiled)
        params = tuple(item for _, child_params in compiled for item in child_params)
    if group.negated:
        sql = "NOT (%s)" % sql
    return sql, params


def compile_picture_query(
    value: Union[PictureQuery, Mapping[str, Any]],
    minimum_rating_policy: str = RATING_POLICY_ALL,
) -> CompiledPictureQuery:
    """Compile a validated query to trusted SQL fragments and bound parameters.

    The returned SQL uses the internal picture alias ``p`` and ``?`` placeholders.
    ``DatabaseEngine`` translates placeholders for MySQL/MariaDB. No user-provided
    table, column, operator or sort fragment is copied into SQL.
    """
    query = ensure_picture_query(value)
    predicates: List[str] = []
    params: List[Any] = []

    if not query.scope.include_missing:
        predicates.append("p.is_missing=0")
    if query.scope.source_ids:
        predicates.append("p.source_id IN (%s)" % _placeholders(query.scope.source_ids))
        params.extend(query.scope.source_ids)
    if query.default_policy.apply_min_rating:
        rating_sql, rating_params = rating_sql_predicate(minimum_rating_policy, "p.rating")
        if rating_sql:
            predicates.append(rating_sql)
            params.extend(rating_params)

    root_sql, root_params = _compile_group(query.root)
    if root_sql != "1=1":
        predicates.append(root_sql)
        params.extend(root_params)

    where_sql = " AND ".join("(%s)" % predicate for predicate in predicates) or "1=1"
    order_by_sql = ", ".join(
        "%s %s" % (_SORT_COLUMNS[item.field], item.direction.upper())
        for item in query.sort
    )
    return CompiledPictureQuery(
        where_sql=where_sql,
        params=tuple(params),
        order_by_sql=order_by_sql,
    )
