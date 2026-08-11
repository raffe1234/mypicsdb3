from __future__ import annotations

import pytest

from mypicsdb3.attention import ATTENTION_PRESETS, attention_preset
from mypicsdb3.query_model import picture_query_to_dict


def test_attention_presets_are_bounded_picture_queries() -> None:
    assert [preset.key for preset in ATTENTION_PRESETS] == [
        "missing-date",
        "missing-camera",
        "missing-location",
        "missing-keywords",
    ]

    location = picture_query_to_dict(attention_preset("missing-location").query)
    assert location["scope"] == {
        "source_ids": [],
        "include_missing": False,
        "include_excluded": False,
    }
    assert location["default_policy"] == {"apply_min_rating": True}
    assert location["root"]["match"] == "all"
    assert location["root"]["children"] == [
        {
            "type": "rule",
            "field": "media_type",
            "operator": "eq",
            "value": "picture",
        },
        {"type": "rule", "field": "country", "operator": "is_null"},
        {"type": "rule", "field": "state", "operator": "is_null"},
        {"type": "rule", "field": "city", "operator": "is_null"},
        {"type": "rule", "field": "sublocation", "operator": "is_null"},
    ]


def test_attention_preset_rejects_unknown_key() -> None:
    with pytest.raises(ValueError, match="Unknown Needs attention preset"):
        attention_preset("not-a-preset")
