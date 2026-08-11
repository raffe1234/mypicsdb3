from __future__ import annotations

import pytest

from mypicsdb3.metadata_browser import (
    CATEGORIES,
    category_by_key,
    facet_by_key,
    metadata_browser_base_query,
    metadata_value_query,
)


def test_metadata_browser_exposes_curated_categories_and_facets() -> None:
    assert [category.key for category in CATEGORIES] == [
        "camera",
        "location",
        "capture",
        "image",
        "keywords",
    ]
    assert category_by_key("camera").facet_keys == ("camera_make", "camera_model")
    assert category_by_key("location").facet_keys == (
        "country",
        "state",
        "city",
        "sublocation",
    )
    assert facet_by_key("aspect").catalog_field == "aspect"
    assert facet_by_key("keyword").catalog_field == "keyword"


def test_metadata_browser_base_query_is_picture_only_and_uses_rating_policy() -> None:
    query = metadata_browser_base_query()
    assert query.default_policy.apply_min_rating is True
    assert len(query.root.children) == 1
    rule = query.root.children[0]
    assert rule.field == "media_type"
    assert rule.operator == "eq"
    assert rule.value == "picture"


def test_metadata_value_queries_reuse_query_model_v1() -> None:
    camera = metadata_value_query("camera_make", "Canon")
    assert camera.root.children[1].field == "camera"
    assert camera.root.children[1].value.make == "Canon"
    assert camera.root.children[1].value.model is None

    year = metadata_value_query("taken_year", "2024")
    assert year.root.children[1].field == "taken_date"
    assert year.root.children[1].value == ("2024-01-01", "2024-12-31")

    rating = metadata_value_query("rating", "5")
    assert rating.root.children[1].field == "rating"
    assert rating.root.children[1].value == 5

    keyword = metadata_value_query("keyword", "Family")
    assert keyword.root.children[1].field == "keyword"
    assert keyword.root.children[1].value == "family"


@pytest.mark.parametrize(
    ("facet", "value"),
    [
        ("unknown", "x"),
        ("taken_year", "not-a-year"),
        ("taken_year", "9999"),
        ("rating", "not-a-rating"),
        ("rating", "9"),
        ("country", ""),
    ],
)
def test_metadata_browser_rejects_invalid_routes(facet: str, value: str) -> None:
    with pytest.raises(ValueError):
        metadata_value_query(facet, value)
