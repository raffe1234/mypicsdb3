from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .query_model import PictureQuery, parse_picture_query
from .search_index import normalize_search_query


@dataclass(frozen=True)
class GlobalSearchRequest:
    text: str
    query: PictureQuery


def build_global_search_request(value: Any) -> GlobalSearchRequest:
    """Normalize user text and build the Query Model used by Kodi search."""
    text, _ = normalize_search_query(value)
    query = parse_picture_query(
        {
            "version": 1,
            "root": {
                "type": "group",
                "match": "all",
                "negated": False,
                "children": [
                    {
                        "type": "rule",
                        "field": "text",
                        "operator": "contains_tokens",
                        "value": text,
                    }
                ],
            },
            "sort": [
                {"field": "taken_at", "direction": "desc"},
                {"field": "id", "direction": "desc"},
            ],
            "scope": {
                "source_ids": [],
                "include_missing": False,
                "include_excluded": False,
            },
            "default_policy": {"apply_min_rating": True},
        }
    )
    return GlobalSearchRequest(text=text, query=query)
