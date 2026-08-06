from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping


MAX_COLLECTION_NAME_LENGTH = 191


class CollectionValidationError(ValueError):
    """Raised when a manual collection name or stored record is invalid."""


@dataclass(frozen=True)
class StaticCollection:
    id: int
    name: str
    created_at: str
    updated_at: str


def normalize_collection_name(value: Any) -> str:
    if not isinstance(value, str):
        raise CollectionValidationError("Collection name must be text")
    name = value.strip()
    if not name:
        raise CollectionValidationError("Collection name must not be empty")
    if len(name) > MAX_COLLECTION_NAME_LENGTH:
        raise CollectionValidationError(
            "Collection name must contain at most %d characters"
            % MAX_COLLECTION_NAME_LENGTH
        )
    return name


def parse_stored_collection(row: Mapping[str, Any]) -> StaticCollection:
    try:
        collection_id = int(row["id"])
        name = normalize_collection_name(row["name"])
    except (KeyError, TypeError, ValueError) as exc:
        raise CollectionValidationError("Collection metadata is invalid") from exc
    if collection_id <= 0:
        raise CollectionValidationError("Collection ID is invalid")
    return StaticCollection(
        id=collection_id,
        name=name,
        created_at=str(row.get("created_at") or ""),
        updated_at=str(row.get("updated_at") or ""),
    )
