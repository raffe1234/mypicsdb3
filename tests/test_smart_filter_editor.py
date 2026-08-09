from __future__ import annotations

from mypicsdb3.query_model import picture_query_to_dict
from mypicsdb3.smart_filter_editor import SmartFilterEditor


class FakeDialog:
    def __init__(self, selections, inputs=None, confirmations=None):
        self.selections = list(selections)
        self.inputs = list(inputs or [])
        self.confirmations = list(confirmations or [])
        self.previews = []

    def select(self, heading, options, preselect=-1):
        return self.selections.pop(0)

    def input(self, heading, defaultt=""):
        return self.inputs.pop(0)

    def yesno(self, heading, message):
        return self.confirmations.pop(0)

    def textviewer(self, heading, text):
        self.previews.append((heading, text))


class FakeCatalog:
    def __init__(self):
        self.count_queries = []
        self.page_queries = []

    def get_sources(self):
        return []

    def cameras(self):
        return []

    def tags(self):
        return []

    def query_facet_counts(self, query, field, limit=100):
        values = {
            "extension": [
                {"value": "jpg", "picture_count": 12},
                {"value": "nef", "picture_count": 4},
            ],
            "country": [{"value": "Sweden", "picture_count": 9}],
            "state": [{"value": "Stockholm", "picture_count": 7}],
            "city": [{"value": "Stockholm", "picture_count": 6}],
            "sublocation": [{"value": "Gamla stan", "picture_count": 2}],
        }
        return values.get(field, [])[:limit]

    def count_query_pictures(self, query):
        self.count_queries.append(query)
        return 2

    def query_pictures(self, query, limit, offset=0):
        self.page_queries.append((query, limit, offset))
        return [
            {"filename": "a.mp4"},
            {"filename": "b.mov"},
        ]


def localize(_string_id, fallback):
    return fallback


def test_editor_builds_previews_and_returns_validated_smart_collection() -> None:
    dialog = FakeDialog(
        selections=[
            3,  # Add criterion.
            7,  # Media type.
            1,  # Videos.
            4,  # Add criterion after first rule.
            2,  # Minimum rating.
            3,  # Rating 4.
            6,  # Preview with two rules.
            7,  # Save with two rules.
        ],
        inputs=["Home videos 4+"],
    )
    catalog = FakeCatalog()

    result = SmartFilterEditor(catalog, dialog, localize).run()

    assert result is not None
    assert result.name == "Home videos 4+"
    payload = picture_query_to_dict(result.query)
    assert payload["root"]["match"] == "all"
    assert payload["root"]["children"] == [
        {
            "type": "rule",
            "field": "media_type",
            "operator": "eq",
            "value": "video",
        },
        {
            "type": "rule",
            "field": "rating",
            "operator": "gte",
            "value": 4,
        },
    ]
    assert dialog.previews == [
        ("Preview results", "2 matching media items\n1. a.mp4\n2. b.mov")
    ]
    assert len(catalog.count_queries) == 2
    assert catalog.page_queries[0][1:] == (2, 0)


def test_editor_can_switch_to_any_and_ignore_global_rating_policy() -> None:
    dialog = FakeDialog(
        selections=[
            0,  # Match any.
            2,  # Disable global rating policy.
            3,  # Add criterion.
            3,  # Favorite.
            0,  # Favorites only.
            6,  # Save with one rule.
        ],
        inputs=["Favorites"],
    )
    result = SmartFilterEditor(FakeCatalog(), dialog, localize).run()

    assert result is not None
    payload = picture_query_to_dict(result.query)
    assert payload["root"]["match"] == "any"
    assert payload["default_policy"] == {"apply_min_rating": False}
    assert payload["root"]["children"][0]["field"] == "favorite"


def test_editor_adds_extension_and_orientation_aware_shape_facets() -> None:
    dialog = FakeDialog(
        selections=[
            3,   # Add criterion.
            8,   # File extension.
            1,   # .nef.
            4,   # Add criterion after first rule.
            13,  # Image shape.
            1,   # Portrait.
            7,   # Save with two rules.
        ],
        inputs=["Portrait NEF"],
    )

    result = SmartFilterEditor(FakeCatalog(), dialog, localize).run()

    assert result is not None
    payload = picture_query_to_dict(result.query)
    assert payload["root"]["children"] == [
        {
            "type": "rule",
            "field": "extension",
            "operator": "eq",
            "value": "nef",
        },
        {
            "type": "rule",
            "field": "aspect",
            "operator": "eq",
            "value": "portrait",
        },
    ]
