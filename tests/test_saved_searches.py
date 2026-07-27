from __future__ import annotations

import json
from pathlib import Path

import pytest

from mypicsdb3.config import Settings
from mypicsdb3.db.catalog import Catalog
from mypicsdb3.db.engine import DatabaseEngine
from mypicsdb3.query_model import canonical_picture_query_json
from mypicsdb3.saved_searches import SavedSearchValidationError
from mypicsdb3.search import build_global_search_request


def make_catalog(tmp_path: Path) -> Catalog:
    catalog = Catalog(
        DatabaseEngine(
            Settings(profile_path=str(tmp_path), database_backend="sqlite")
        )
    )
    catalog.initialize()
    return catalog


def test_saved_search_roundtrip_rename_delete_and_canonical_storage(tmp_path: Path) -> None:
    catalog = make_catalog(tmp_path)
    request = build_global_search_request(" ÅLAND  Sommar! ")

    saved_id = catalog.create_saved_search("  Sommarresor  ", request.query)

    assert catalog.list_saved_searches() == [
        {
            "id": saved_id,
            "name": "Sommarresor",
            "query_version": 1,
            "created_at": catalog.list_saved_searches()[0]["created_at"],
            "updated_at": catalog.list_saved_searches()[0]["updated_at"],
        }
    ]
    saved = catalog.get_saved_search(saved_id)
    assert saved is not None
    assert saved.name == "Sommarresor"
    assert canonical_picture_query_json(saved.query) == canonical_picture_query_json(
        request.query
    )

    with catalog.engine.transaction() as connection:
        row = catalog.engine.fetchone(
            connection,
            "SELECT query_version, query_json FROM saved_searches WHERE id=?",
            (saved_id,),
        )
    assert row is not None
    assert row["query_version"] == 1
    assert json.loads(row["query_json"])["version"] == 1
    assert "SELECT" not in row["query_json"].upper()

    assert catalog.rename_saved_search(saved_id, "Östersjön") is True
    assert catalog.get_saved_search(saved_id).name == "Östersjön"
    assert catalog.delete_saved_search(saved_id) is True
    assert catalog.get_saved_search(saved_id) is None
    assert catalog.delete_saved_search(saved_id) is False


def test_saved_search_names_are_bounded_and_unique(tmp_path: Path) -> None:
    catalog = make_catalog(tmp_path)
    query = build_global_search_request("sommar").query
    catalog.create_saved_search("Sommar", query)

    with pytest.raises(SavedSearchValidationError, match="already exists"):
        catalog.create_saved_search("Sommar", query)
    with pytest.raises(SavedSearchValidationError, match="must not be empty"):
        catalog.create_saved_search("   ", query)
    with pytest.raises(SavedSearchValidationError, match="at most 191"):
        catalog.create_saved_search("x" * 192, query)


def test_saved_search_revalidates_version_and_json_on_every_read(tmp_path: Path) -> None:
    catalog = make_catalog(tmp_path)
    saved_id = catalog.create_saved_search(
        "Sommar", build_global_search_request("sommar").query
    )

    with catalog.engine.transaction(immediate=True) as connection:
        catalog.engine.execute(
            connection,
            "UPDATE saved_searches SET query_version=? WHERE id=?",
            (99, saved_id),
        ).close()
    with pytest.raises(SavedSearchValidationError, match="unsupported query model"):
        catalog.get_saved_search(saved_id)

    with catalog.engine.transaction(immediate=True) as connection:
        catalog.engine.execute(
            connection,
            "UPDATE saved_searches SET query_version=?, query_json=? WHERE id=?",
            (1, "{not-json", saved_id),
        ).close()
    with pytest.raises(SavedSearchValidationError, match="JSON is invalid"):
        catalog.get_saved_search(saved_id)

    with catalog.engine.transaction(immediate=True) as connection:
        catalog.engine.execute(
            connection,
            "UPDATE saved_searches SET query_json=? WHERE id=?",
            (json.dumps({"version": 1, "raw_sql": "DROP TABLE pictures"}), saved_id),
        ).close()
    with pytest.raises(SavedSearchValidationError, match="query is invalid"):
        catalog.get_saved_search(saved_id)
