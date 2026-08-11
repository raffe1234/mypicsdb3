from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Tuple

from .query_model import PictureQuery, parse_picture_query


@dataclass(frozen=True)
class MetadataBrowserCategory:
    key: str
    string_id: int
    fallback: str
    facet_keys: Tuple[str, ...]


@dataclass(frozen=True)
class MetadataBrowserFacet:
    key: str
    string_id: int
    fallback: str
    catalog_field: str


FACETS: Tuple[MetadataBrowserFacet, ...] = (
    MetadataBrowserFacet("camera_make", 32922, "Camera make", "camera_make"),
    MetadataBrowserFacet("camera_model", 32923, "Camera model", "camera_model"),
    MetadataBrowserFacet("country", 32876, "Country", "country"),
    MetadataBrowserFacet("state", 32877, "State or region", "state"),
    MetadataBrowserFacet("city", 32878, "City", "city"),
    MetadataBrowserFacet("sublocation", 32879, "Sublocation", "sublocation"),
    MetadataBrowserFacet("taken_year", 32956, "Capture year", "taken_year"),
    MetadataBrowserFacet("extension", 32875, "File extension", "extension"),
    MetadataBrowserFacet("mime_type", 32931, "MIME type", "mime_type"),
    MetadataBrowserFacet("aspect", 32880, "Image shape", "aspect"),
    MetadataBrowserFacet("rating", 32924, "Rating", "rating"),
    MetadataBrowserFacet("keyword", 30009, "Keywords", "keyword"),
)

FACET_BY_KEY: Dict[str, MetadataBrowserFacet] = {facet.key: facet for facet in FACETS}

CATEGORIES: Tuple[MetadataBrowserCategory, ...] = (
    MetadataBrowserCategory("camera", 32951, "Camera", ("camera_make", "camera_model")),
    MetadataBrowserCategory("location", 32952, "Location", ("country", "state", "city", "sublocation")),
    MetadataBrowserCategory("capture", 32953, "Capture", ("taken_year",)),
    MetadataBrowserCategory("image", 32954, "Image", ("extension", "mime_type", "aspect", "rating")),
    MetadataBrowserCategory("keywords", 30009, "Keywords", ("keyword",)),
)

CATEGORY_BY_KEY: Dict[str, MetadataBrowserCategory] = {
    category.key: category for category in CATEGORIES
}


def metadata_browser_base_query() -> PictureQuery:
    """Return the picture-only selection used for metadata facet counts.

    The user's configured minimum-rating policy remains enabled so counts and
    opened result pages describe the same interactive catalogue selection.
    """
    return parse_picture_query(
        {
            "version": 1,
            "root": {
                "type": "group",
                "match": "all",
                "negated": False,
                "children": [
                    {
                        "type": "rule",
                        "field": "media_type",
                        "operator": "eq",
                        "value": "picture",
                    }
                ],
            },
            "sort": [{"field": "discovered_at", "direction": "desc"}],
            "scope": {
                "source_ids": [],
                "include_missing": False,
                "include_excluded": False,
            },
            "default_policy": {"apply_min_rating": True},
        }
    )


def metadata_value_query(facet_key: str, raw_value: object) -> PictureQuery:
    """Build a validated Query Model v1 selection for one browser facet value."""
    if facet_key not in FACET_BY_KEY:
        raise ValueError("Unknown metadata browser facet %r" % facet_key)

    value = str(raw_value or "").strip()
    if not value:
        raise ValueError("Metadata browser values must not be empty")

    if facet_key == "camera_make":
        rule = {"field": "camera", "operator": "eq", "value": {"make": value}}
    elif facet_key == "camera_model":
        rule = {"field": "camera", "operator": "eq", "value": {"model": value}}
    elif facet_key == "taken_year":
        try:
            year = int(value)
        except (TypeError, ValueError) as exc:
            raise ValueError("Capture year must be an integer") from exc
        if year < 1 or year > 9998:
            raise ValueError("Capture year is outside the supported range")
        rule = {
            "field": "taken_date",
            "operator": "between",
            "from": "%04d-01-01" % year,
            "to": "%04d-12-31" % year,
        }
    elif facet_key == "rating":
        try:
            rating = int(value)
        except (TypeError, ValueError) as exc:
            raise ValueError("Rating must be an integer") from exc
        rule = {"field": "rating", "operator": "eq", "value": rating}
    else:
        rule = {"field": facet_key, "operator": "eq", "value": value}

    return parse_picture_query(
        {
            "version": 1,
            "root": {
                "type": "group",
                "match": "all",
                "negated": False,
                "children": [
                    {
                        "type": "rule",
                        "field": "media_type",
                        "operator": "eq",
                        "value": "picture",
                    },
                    {"type": "rule", **rule},
                ],
            },
            "sort": [{"field": "discovered_at", "direction": "desc"}],
            "scope": {
                "source_ids": [],
                "include_missing": False,
                "include_excluded": False,
            },
            "default_policy": {"apply_min_rating": True},
        }
    )


def category_by_key(key: str) -> MetadataBrowserCategory:
    try:
        return CATEGORY_BY_KEY[str(key)]
    except KeyError as exc:
        raise ValueError("Unknown metadata browser category %r" % key) from exc


def facet_by_key(key: str) -> MetadataBrowserFacet:
    try:
        return FACET_BY_KEY[str(key)]
    except KeyError as exc:
        raise ValueError("Unknown metadata browser facet %r" % key) from exc
