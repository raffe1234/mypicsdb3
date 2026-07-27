from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from .query_model import (
    QUERY_MODEL_VERSION,
    PictureQuery,
    QueryValidationError,
    parse_picture_query,
)


MAX_SAVED_SEARCH_NAME_LENGTH = 191


class SavedSearchValidationError(ValueError):
    """Raised when stored saved-search data is malformed or unsupported."""


@dataclass(frozen=True)
class SavedSearch:
    id: int
    name: str
    query_version: int
    query: PictureQuery
    created_at: str
    updated_at: str


def normalize_saved_search_name(value: Any) -> str:
    if not isinstance(value, str):
        raise SavedSearchValidationError("Saved-search name must be text")
    name = value.strip()
    if not name:
        raise SavedSearchValidationError("Saved-search name must not be empty")
    if len(name) > MAX_SAVED_SEARCH_NAME_LENGTH:
        raise SavedSearchValidationError(
            "Saved-search name must contain at most %d characters"
            % MAX_SAVED_SEARCH_NAME_LENGTH
        )
    return name


def parse_stored_saved_search(row: Mapping[str, Any]) -> SavedSearch:
    """Validate the stored query version and JSON every time it is opened."""
    try:
        saved_id = int(row["id"])
        name = normalize_saved_search_name(row["name"])
        query_version = int(row["query_version"])
        raw_json = row["query_json"]
    except (KeyError, TypeError, ValueError) as exc:
        raise SavedSearchValidationError("Saved search metadata is invalid") from exc

    if query_version != QUERY_MODEL_VERSION:
        raise SavedSearchValidationError(
            "Saved search uses unsupported query model version %d" % query_version
        )
    if not isinstance(raw_json, str):
        raise SavedSearchValidationError("Saved search query JSON must be text")
    try:
        payload = json.loads(raw_json)
    except (TypeError, ValueError) as exc:
        raise SavedSearchValidationError("Saved search query JSON is invalid") from exc
    if not isinstance(payload, Mapping):
        raise SavedSearchValidationError("Saved search query JSON must contain an object")
    try:
        query = parse_picture_query(payload)
    except QueryValidationError as exc:
        raise SavedSearchValidationError("Saved search query is invalid: %s" % exc) from exc
    if query.version != query_version:
        raise SavedSearchValidationError(
            "Saved search query version does not match its database record"
        )

    return SavedSearch(
        id=saved_id,
        name=name,
        query_version=query_version,
        query=query,
        created_at=str(row.get("created_at") or ""),
        updated_at=str(row.get("updated_at") or ""),
    )
