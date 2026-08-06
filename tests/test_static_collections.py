from __future__ import annotations

import pytest

from mypicsdb3.static_collections import (
    CollectionValidationError,
    normalize_collection_name,
    parse_stored_collection,
)


def test_collection_names_are_trimmed_and_bounded() -> None:
    assert normalize_collection_name("  Family  ") == "Family"
    with pytest.raises(CollectionValidationError):
        normalize_collection_name(123)
    with pytest.raises(CollectionValidationError):
        normalize_collection_name("   ")
    with pytest.raises(CollectionValidationError):
        normalize_collection_name("x" * 192)


def test_stored_collection_metadata_is_validated() -> None:
    collection = parse_stored_collection(
        {
            "id": 4,
            "name": "Trips",
            "created_at": "2026-08-06",
            "updated_at": "2026-08-06",
        }
    )
    assert collection.id == 4
    assert collection.name == "Trips"

    with pytest.raises(CollectionValidationError):
        parse_stored_collection({"id": 0, "name": "Trips"})
