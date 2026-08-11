from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Iterable, Tuple

from .query_model import PictureQuery, parse_picture_query


@dataclass(frozen=True)
class AttentionPreset:
    key: str
    string_id: int
    fallback: str
    query: PictureQuery


def _query(children: Iterable[dict]) -> PictureQuery:
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
                    *list(children),
                ],
            },
            "sort": [{"field": "discovered_at", "direction": "desc"}],
            "scope": {
                "source_ids": [],
                "include_missing": False,
                "include_excluded": False,
            },
            # Keep the same user-selected minimum-rating display policy as the
            # rest of interactive catalogue browsing.
            "default_policy": {"apply_min_rating": True},
        }
    )


ATTENTION_PRESETS: Tuple[AttentionPreset, ...] = (
    AttentionPreset(
        "missing-date",
        32946,
        "Pictures without date",
        _query([{"type": "rule", "field": "taken_date", "operator": "is_null"}]),
    ),
    AttentionPreset(
        "missing-camera",
        32947,
        "Pictures without camera",
        _query([{"type": "rule", "field": "camera", "operator": "is_null"}]),
    ),
    AttentionPreset(
        "missing-location",
        32948,
        "Pictures without location",
        _query(
            [
                {"type": "rule", "field": field, "operator": "is_null"}
                for field in ("country", "state", "city", "sublocation")
            ]
        ),
    ),
    AttentionPreset(
        "missing-keywords",
        32949,
        "Pictures without keywords",
        _query([{"type": "rule", "field": "keyword", "operator": "is_null"}]),
    ),
)

ATTENTION_BY_KEY: Dict[str, AttentionPreset] = {item.key: item for item in ATTENTION_PRESETS}


def attention_preset(key: str) -> AttentionPreset:
    try:
        return ATTENTION_BY_KEY[str(key)]
    except KeyError as exc:
        raise ValueError("Unknown Needs attention preset %r" % key) from exc
