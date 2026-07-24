from __future__ import annotations

from pathlib import Path

from mypicsdb3.config import Settings, from_getter
from mypicsdb3.db.catalog import Catalog
from mypicsdb3.db.engine import DatabaseEngine
from mypicsdb3.rating_policy import (
    RATING_POLICY_ALL,
    RATING_POLICY_RATED_AND_UNRATED,
    normalize_rating_policy,
    rating_policy_label,
    rating_sql_predicate,
)

from test_catalog import add_picture


def make_catalog(tmp_path: Path) -> Catalog:
    settings = Settings(profile_path=str(tmp_path), database_backend="sqlite")
    catalog = Catalog(DatabaseEngine(settings))
    catalog.initialize()
    return catalog


def add_rating_fixture(catalog: Catalog, root: Path) -> dict[str, int]:
    rows = {}
    for index, (name, rating) in enumerate(
        (
            ("unrated.jpg", None),
            ("zero.jpg", 0),
            ("one.jpg", 1),
            ("three.jpg", 3),
            ("five.jpg", 5),
        ),
        start=1,
    ):
        rows[name] = add_picture(
            catalog,
            root,
            name=name,
            taken_at="2020-07-17 %02d:00:00" % (10 + index),
            discovered_at="2026-07-17 %02d:00:00" % (10 + index),
            rating=rating,
        )
    return rows


def test_rating_policy_normalization_and_sql_are_bounded() -> None:
    assert normalize_rating_policy(None) == RATING_POLICY_ALL
    assert normalize_rating_policy("rated-unrated") == RATING_POLICY_RATED_AND_UNRATED
    assert normalize_rating_policy("3") == "3"
    assert normalize_rating_policy("999") == RATING_POLICY_ALL
    assert rating_policy_label("4") == "4+"
    assert rating_sql_predicate("all") == ("", ())
    assert rating_sql_predicate("rated_and_unrated", "rating") == (
        "(rating IS NULL OR rating>=1)",
        (),
    )
    assert rating_sql_predicate("3", "rating") == ("rating>=?", (3,))


def test_setting_distinguishes_unrated_from_explicit_zero() -> None:
    rated_and_unrated = from_getter(
        lambda key: {"minimum_rating_policy": "rated_and_unrated"}.get(key, ""),
        "/tmp/mypicsdb3",
    )
    invalid = from_getter(
        lambda key: {"minimum_rating_policy": "invalid"}.get(key, ""),
        "/tmp/mypicsdb3",
    )

    assert rated_and_unrated.minimum_rating_policy == RATING_POLICY_RATED_AND_UNRATED
    assert invalid.minimum_rating_policy == RATING_POLICY_ALL


def test_catalog_applies_rating_policy_to_lists_groups_counts_and_art(tmp_path: Path) -> None:
    catalog = make_catalog(tmp_path)
    root = tmp_path / "photos"
    rows = add_rating_fixture(catalog, root)

    assert len(catalog.recent_added(20)) == 5
    assert catalog.overview()["pictures"] == 5

    catalog.set_rating_policy(RATING_POLICY_RATED_AND_UNRATED)
    assert {row["id"] for row in catalog.recent_added(20)} == {
        rows["unrated.jpg"],
        rows["one.jpg"],
        rows["three.jpg"],
        rows["five.jpg"],
    }

    catalog.set_rating_policy("3")
    assert [row["filename"] for row in catalog.recent_added(20)] == [
        "five.jpg",
        "three.jpg",
    ]
    assert [row["filename"] for row in catalog.recent_added(1, offset=1)] == [
        "three.jpg"
    ]
    assert catalog.years()[0]["picture_count"] == 2
    assert catalog.months_for_year(2020)[0]["picture_count"] == 2
    assert catalog.days_for_month(2020, 7)[0]["picture_count"] == 2
    assert catalog.cameras()[0]["picture_count"] == 2
    assert {row["picture_count"] for row in catalog.tags()} == {2}
    assert catalog.recent_folders(10)[0]["picture_count"] == 2
    assert catalog.recent_folders(10)[0]["representative_uri"].endswith("five.jpg")
    assert {row["rating"] for row in catalog.random_pictures(10)} == {3, 5}
    assert catalog.overview()["pictures"] == 5

    catalog.set_rating_policy("5")
    assert [row["id"] for row in catalog.pictures_in_folder(
        catalog.recent_folders(10)[0]["id"], 20
    )] == [rows["five.jpg"]]

    catalog.set_rating_policy(RATING_POLICY_ALL)
    assert len(catalog.recent_added(20)) == 5
