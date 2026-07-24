from __future__ import annotations

from pathlib import Path

import pytest

from mypicsdb3.config import Settings
from mypicsdb3.db.catalog import Catalog
from mypicsdb3.db.engine import DatabaseEngine
from mypicsdb3.query_model import (
    QueryValidationError,
    canonical_picture_query_json,
    compile_picture_query,
    parse_picture_query,
)
from mypicsdb3.search import build_global_search_request
from mypicsdb3.search_index import (
    MAX_SEARCH_DOCUMENT_BYTES,
    MAX_SEARCH_QUERY_TOKENS,
    SearchTextError,
    build_picture_search_document,
    normalize_search_query,
)
from mypicsdb3.utils import utc_now


def make_catalog(tmp_path: Path) -> Catalog:
    catalog = Catalog(
        DatabaseEngine(
            Settings(profile_path=str(tmp_path), database_backend="sqlite")
        )
    )
    catalog.initialize()
    return catalog


def add_picture(
    catalog: Catalog,
    source_id: int,
    folder_id: int,
    *,
    name: str,
    caption: str,
    camera_make: str,
    camera_model: str,
    city: str,
    country: str,
    keywords,
    rating,
) -> int:
    now = utc_now()
    with catalog.engine.transaction() as connection:
        return catalog.insert_picture(
            connection,
            {
                "source_id": source_id,
                "folder_id": folder_id,
                "uri": "/srv/Foton/Åland/" + name,
                "filename": name,
                "extension": "jpg",
                "file_size": 100,
                "file_mtime": 1.0,
                "discovered_at": now,
                "last_seen_at": now,
                "taken_at": "2024-07-17 10:00:00",
                "taken_source": "EXIF",
                "camera_make": camera_make,
                "camera_model": camera_model,
                "rating": rating,
                "city": city,
                "country": country,
                "caption": caption,
                "metadata_hash": name,
                "thumb_uri": "/srv/Foton/Åland/" + name,
            },
            keywords,
        )


def test_search_tokenizer_normalizes_unicode_and_builds_bounded_documents() -> None:
    text, tokens = normalize_search_query("  ÅLAND  Sommar! åland  ")
    assert text == "åland sommar"
    assert tokens == ("åland", "sommar")

    document = build_picture_search_document(
        {
            "filename": "Åland-Sommar_2024.jpg",
            "uri": "smb://NAS/Foton/Åland/Åland-Sommar_2024.jpg",
            "caption": "Blå båt",
            "camera_make": "FUJIFILM",
            "camera_model": "X-T5",
            "city": "Göteborg",
            "country": "Sverige",
        },
        ["Familj", "Sjö"],
    )
    for token in (
        " åland ",
        " sommar ",
        " 2024 ",
        " familj ",
        " sjö ",
        " blå ",
        " båt ",
        " fujifilm ",
        " göteborg ",
    ):
        assert token in document

    large_document = build_picture_search_document(
        {"caption": " ".join("å" * 191 + str(index) for index in range(400))},
    )
    assert len(large_document.encode("utf-8")) <= MAX_SEARCH_DOCUMENT_BYTES

    with pytest.raises(SearchTextError, match="letters or numbers"):
        normalize_search_query("--- %%%")
    with pytest.raises(SearchTextError, match="different words"):
        normalize_search_query(
            " ".join("word%d" % index for index in range(MAX_SEARCH_QUERY_TOKENS + 1))
        )


def test_text_rule_is_canonical_parameterized_and_uses_and_tokens() -> None:
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
                        "value": " ÅLAND summer%_! ",
                    }
                ],
            },
        }
    )
    compiled = compile_picture_query(query)

    assert "ÅLAND" not in compiled.where_sql
    assert "summer" not in compiled.where_sql
    assert "picture_search_documents" in compiled.where_sql
    assert compiled.where_sql.count("LIKE ?") == 2
    assert compiled.params == ("% åland %", "% summer %")
    canonical = canonical_picture_query_json(query)
    assert '"value":"åland summer"' in canonical
    assert canonical_picture_query_json(parse_picture_query(__import__("json").loads(canonical))) == canonical

    with pytest.raises(QueryValidationError, match="not allowed"):
        parse_picture_query(
            {
                "version": 1,
                "root": {
                    "type": "group",
                    "children": [
                        {"type": "rule", "field": "text", "operator": "eq", "value": "x"}
                    ],
                },
            }
        )


def test_global_search_matches_all_tokens_fields_updates_and_rating_policy(tmp_path: Path) -> None:
    catalog = make_catalog(tmp_path)
    source = catalog.sync_sources([{"label": "Photos", "uri": "/srv/Foton"}])[0]
    now = utc_now()
    with catalog.engine.transaction() as connection:
        folder_id = catalog.upsert_folder(
            connection,
            source.id,
            "/srv/Foton/Åland/",
            "",
            "Åland",
            now,
        )

    selected = add_picture(
        catalog,
        source.id,
        folder_id,
        name="Sommar_2024.jpg",
        caption="Blå båt i skärgården",
        camera_make="Fujifilm",
        camera_model="X-T5",
        city="Göteborg",
        country="Sverige",
        keywords=["Familj", "Semester"],
        rating=5,
    )
    low = add_picture(
        catalog,
        source.id,
        folder_id,
        name="Sommar_låg.jpg",
        caption="Badstrand",
        camera_make="Canon",
        camera_model="R6",
        city="Visby",
        country="Sverige",
        keywords=["Familj"],
        rating=2,
    )
    add_picture(
        catalog,
        source.id,
        folder_id,
        name="Vinter.jpg",
        caption="Snö",
        camera_make="Nikon",
        camera_model="Z6",
        city="Kiruna",
        country="Sverige",
        keywords=["Vinter"],
        rating=5,
    )

    request = build_global_search_request("ÅLAND familj")
    assert request.text == "åland familj"
    assert {row["id"] for row in catalog.query_pictures(request.query, 10)} == {
        selected,
        low,
    }
    assert catalog.count_query_pictures(request.query) == 2

    fields = build_global_search_request("fujifilm göteborg blå")
    assert [row["id"] for row in catalog.query_pictures(fields.query, 10)] == [selected]

    no_match = build_global_search_request("sommar vinter")
    assert catalog.query_pictures(no_match.query, 10) == []

    catalog.set_rating_policy("3")
    assert [row["id"] for row in catalog.query_pictures(request.query, 10)] == [selected]
    assert catalog.count_query_pictures(request.query) == 1

    with catalog.engine.transaction() as connection:
        row = catalog.engine.fetchone(
            connection,
            "SELECT * FROM pictures WHERE id=?",
            (selected,),
        )
        assert row is not None
        row.update(
            {
                "caption": "Midnattssol",
                "metadata_hash": "updated-search",
                "last_seen_at": utc_now(),
            }
        )
        catalog.update_picture(connection, selected, row, ["Norrland"])

    assert catalog.query_pictures(build_global_search_request("blå").query, 10) == []
    assert [row["id"] for row in catalog.query_pictures(
        build_global_search_request("midnattssol norrland").query,
        10,
    )] == [selected]
