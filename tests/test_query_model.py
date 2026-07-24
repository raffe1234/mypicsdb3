from __future__ import annotations

import json
from pathlib import Path

import pytest

from mypicsdb3.config import Settings
from mypicsdb3.db.catalog import Catalog
from mypicsdb3.db.engine import DatabaseEngine
from mypicsdb3.query_model import (
    MAX_LIST_VALUES,
    MAX_RULES,
    MAX_STRING_LENGTH,
    QUERY_MODEL_VERSION,
    QueryValidationError,
    canonical_picture_query_json,
    compile_picture_query,
    parse_picture_query,
    picture_query_to_dict,
)
from mypicsdb3.utils import utc_now


def empty_query(**overrides):
    value = {
        "version": QUERY_MODEL_VERSION,
        "root": {
            "type": "group",
            "match": "all",
            "negated": False,
            "children": [],
        },
        "sort": [],
        "scope": {
            "source_ids": [],
            "include_missing": False,
            "include_excluded": False,
        },
        "default_policy": {"apply_min_rating": True},
    }
    value.update(overrides)
    return value


def rule(field, operator, value=None, **extra):
    result = {"type": "rule", "field": field, "operator": operator}
    if value is not None:
        result["value"] = value
    result.update(extra)
    return result


def test_query_model_normalizes_defaults_sort_and_canonical_json() -> None:
    query = parse_picture_query(
        {
            "version": 1,
            "scope": {
                "source_ids": [9, 2, 9],
                "include_missing": False,
                "include_excluded": False,
            },
            "sort": [{"field": "filename", "direction": "ASC"}],
            "root": {
                "type": "group",
                "match": "all",
                "negated": False,
                "children": [rule("keyword", "in", ["Summer", "family", "SUMMER"])],
            },
        }
    )

    normalized = picture_query_to_dict(query)
    assert normalized["scope"]["source_ids"] == [2, 9]
    assert normalized["sort"] == [
        {"field": "filename", "direction": "asc"},
        {"field": "id", "direction": "asc"},
    ]
    assert normalized["root"]["children"][0]["value"] == ["family", "summer"]
    assert normalized["default_policy"] == {"apply_min_rating": True}

    first = canonical_picture_query_json(query)
    second = canonical_picture_query_json(json.loads(first))
    assert first == second
    assert first == json.dumps(normalized, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


@pytest.mark.parametrize(
    ("query", "message"),
    [
        ({}, "query.version"),
        ({"version": 2}, "unsupported query model version"),
        ({"version": 1, "unknown": True}, "unknown field"),
        (empty_query(root={"type": "group", "match": "some", "children": []}), "all' or 'any"),
        (empty_query(root={"type": "group", "children": [rule("text", "eq", "x")]}), "unsupported field"),
        (empty_query(root={"type": "group", "children": [rule("favorite", "gte", True)]}), "not allowed"),
        (empty_query(root={"type": "group", "children": [rule("favorite", "eq", 1)]}), "must be a boolean"),
        (empty_query(root={"type": "group", "children": [rule("source", "eq", True)]}), "must be an integer"),
        (empty_query(root={"type": "group", "children": [rule("rating", "between", **{"from": 4, "to": 2})]}), "must not be greater"),
        (empty_query(scope={"source_ids": [], "include_missing": False, "include_excluded": True}), "reserved"),
        (empty_query(sort=[{"field": "sql", "direction": "asc"}]), "unsupported sort field"),
        (empty_query(sort=[{"field": "id", "direction": "sideways"}]), "asc' or 'desc"),
        (empty_query(root={"type": "group", "children": [rule("taken_date", "between", **{"from": "9999-12-30", "to": "9999-12-31"})]}), "before 9999-12-31"),
    ],
)
def test_query_model_rejects_unknown_unsupported_or_wrongly_typed_input(query, message) -> None:
    with pytest.raises(QueryValidationError, match=message):
        parse_picture_query(query)


def test_query_model_enforces_depth_rule_list_and_string_limits() -> None:
    too_deep = {
        "type": "group",
        "children": [{
            "type": "group",
            "children": [{
                "type": "group",
                "children": [{"type": "group", "children": []}],
            }],
        }],
    }
    with pytest.raises(QueryValidationError, match="nested at most"):
        parse_picture_query(empty_query(root=too_deep))

    too_many_rules = {
        "type": "group",
        "children": [rule("rating", "eq", 1) for _ in range(MAX_RULES + 1)],
    }
    with pytest.raises(QueryValidationError, match="more than"):
        parse_picture_query(empty_query(root=too_many_rules))

    with pytest.raises(QueryValidationError, match="at most %d values" % MAX_LIST_VALUES):
        parse_picture_query(
            empty_query(root={"type": "group", "children": [rule("source", "in", list(range(1, MAX_LIST_VALUES + 2)))]})
        )

    with pytest.raises(QueryValidationError, match="at most %d characters" % MAX_STRING_LENGTH):
        parse_picture_query(
            empty_query(root={"type": "group", "children": [rule("camera", "eq", {"make": "x" * (MAX_STRING_LENGTH + 1)})]})
        )


def test_compiler_uses_allowlists_bound_parameters_groups_and_rating_policy() -> None:
    injected = "summer') OR 1=1 --"
    query = empty_query(
        root={
            "type": "group",
            "match": "all",
            "negated": False,
            "children": [
                rule("keyword", "eq", injected),
                {
                    "type": "group",
                    "match": "any",
                    "negated": True,
                    "children": [
                        rule("favorite", "eq", False),
                        rule("rating", "between", **{"from": 3, "to": 5}),
                    ],
                },
                rule("taken_date", "between", **{"from": "2020-01-01", "to": "2020-12-31"}),
                rule("camera", "eq", {"make": "Canon", "model": "EOS R6"}),
            ],
        },
        scope={"source_ids": [4, 2], "include_missing": False, "include_excluded": False},
        sort=[{"field": "rating", "direction": "desc"}],
    )

    compiled = compile_picture_query(query, minimum_rating_policy="4")

    assert injected.casefold() not in compiled.where_sql
    assert "OR 1=1" not in compiled.where_sql
    assert "p.is_missing=0" in compiled.where_sql
    assert "p.source_id IN (?,?)" in compiled.where_sql
    assert "p.rating>=?" in compiled.where_sql
    assert "EXISTS (SELECT 1 FROM picture_tags" in compiled.where_sql
    assert "NOT (" in compiled.where_sql
    assert compiled.order_by_sql == "p.rating DESC, p.id DESC"
    assert compiled.params == (
        2,
        4,
        4,
        injected.casefold(),
        0,
        3,
        5,
        "2020-01-01 00:00:00",
        "2021-01-01 00:00:00",
        "Canon",
        "EOS R6",
    )

    bypass = compile_picture_query(
        empty_query(default_policy={"apply_min_rating": False}),
        minimum_rating_policy="5",
    )
    assert "rating" not in bypass.where_sql
    assert bypass.params == ()


def make_catalog(tmp_path: Path) -> Catalog:
    catalog = Catalog(DatabaseEngine(Settings(profile_path=str(tmp_path), database_backend="sqlite")))
    catalog.initialize()
    return catalog


def insert_picture(
    catalog: Catalog,
    source_id: int,
    folder_id: int,
    root: str,
    name: str,
    rating,
    favorite: bool,
    taken_at: str,
    camera_make: str,
    camera_model: str,
    keywords,
    missing: bool = False,
) -> int:
    now = utc_now()
    with catalog.engine.transaction() as connection:
        picture_id = catalog.insert_picture(
            connection,
            {
                "source_id": source_id,
                "folder_id": folder_id,
                "uri": root + name,
                "filename": name,
                "extension": "jpg",
                "file_size": 100,
                "file_mtime": 1.0,
                "discovered_at": "2026-07-24 12:00:00",
                "last_seen_at": now,
                "taken_at": taken_at,
                "taken_source": "EXIF",
                "camera_make": camera_make,
                "camera_model": camera_model,
                "rating": rating,
                "metadata_hash": name,
                "thumb_uri": root + name,
            },
            keywords,
        )
        if favorite:
            catalog.engine.execute(
                connection,
                "UPDATE pictures SET favorite=1 WHERE id=?",
                (picture_id,),
            ).close()
        if missing:
            catalog.engine.execute(
                connection,
                "UPDATE pictures SET is_missing=1, missing_since=? WHERE id=?",
                (now, picture_id),
            ).close()
    return picture_id


def test_catalog_query_model_page_count_scope_policy_and_pagination(tmp_path: Path) -> None:
    catalog = make_catalog(tmp_path)
    sources = catalog.sync_sources(
        [
            {"label": "Primary", "uri": "/srv/primary"},
            {"label": "Shared", "uri": "/srv/shared"},
        ]
    )
    primary, shared = sources
    now = utc_now()
    with catalog.engine.transaction() as connection:
        primary_folder = catalog.upsert_folder(connection, primary.id, "/srv/primary/", "", "Primary", now)
        shared_folder = catalog.upsert_folder(connection, shared.id, "/srv/shared/", "", "Shared", now)

    selected = insert_picture(
        catalog, primary.id, primary_folder, "/srv/primary/", "a-selected.jpg", 5, True,
        "2020-07-17 10:00:00", "Canon", "EOS R6", ["Summer", "Family"],
    )
    insert_picture(
        catalog, primary.id, primary_folder, "/srv/primary/", "b-low.jpg", 2, False,
        "2019-05-02 11:00:00", "Nikon", "Z6", ["Winter"],
    )
    insert_picture(
        catalog, shared.id, shared_folder, "/srv/shared/", "c-unrated.jpg", None, True,
        "2021-01-01 12:00:00", "Canon", "EOS R6", ["Summer"],
    )
    insert_picture(
        catalog, shared.id, shared_folder, "/srv/shared/", "d-missing.jpg", 5, True,
        "2020-08-01 12:00:00", "Canon", "EOS R6", ["Summer"], missing=True,
    )

    filtered = empty_query(
        root={
            "type": "group",
            "match": "all",
            "negated": False,
            "children": [
                rule("rating", "gte", 3),
                rule("favorite", "eq", True),
                rule("album", "eq", primary_folder),
                rule("taken_date", "between", **{"from": "2020-01-01", "to": "2020-12-31"}),
                rule("camera", "eq", {"make": "Canon", "model": "EOS R6"}),
                rule("keyword", "eq", "SUMMER"),
            ],
        },
        scope={"source_ids": [primary.id], "include_missing": False, "include_excluded": False},
        sort=[{"field": "filename", "direction": "asc"}],
    )
    assert [row["id"] for row in catalog.query_pictures(filtered, 10)] == [selected]
    assert catalog.count_query_pictures(filtered) == 1

    catalog.set_rating_policy("3")
    visible = catalog.query_pictures(empty_query(sort=[{"field": "filename", "direction": "asc"}]), 10)
    assert [row["filename"] for row in visible] == ["a-selected.jpg"]

    all_nonmissing_query = empty_query(
        default_policy={"apply_min_rating": False},
        sort=[{"field": "filename", "direction": "asc"}],
    )
    assert [row["filename"] for row in catalog.query_pictures(all_nonmissing_query, 2)] == [
        "a-selected.jpg",
        "b-low.jpg",
    ]
    assert [row["filename"] for row in catalog.query_pictures(all_nonmissing_query, 2, offset=2)] == [
        "c-unrated.jpg",
    ]
    assert catalog.count_query_pictures(all_nonmissing_query) == 3

    include_missing = empty_query(
        default_policy={"apply_min_rating": False},
        scope={"source_ids": [], "include_missing": True, "include_excluded": False},
        sort=[{"field": "filename", "direction": "asc"}],
    )
    assert catalog.count_query_pictures(include_missing) == 4

    with pytest.raises(ValueError, match="integer"):
        catalog.query_pictures(all_nonmissing_query, True)
    with pytest.raises(ValueError, match="limit"):
        catalog.query_pictures(all_nonmissing_query, 0)
    with pytest.raises(ValueError, match="offset"):
        catalog.query_pictures(all_nonmissing_query, 10, offset=-1)
