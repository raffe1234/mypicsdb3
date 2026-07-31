# Search, Query Model and saved smart collections

This guide connects text search, validated dynamic filters, saved searches and
smart home-screen rows.

## Two search paths

MyPicsDB 3 supports two related but distinct paths:

```text
plain global search text
→ tokenize and normalize
→ normalized per-media search document
→ AND match in the catalogue

smart filter editor or saved query JSON
→ parse and validate Query Model
→ allowlisted SQL predicates and sort
→ catalogue results
```

Both paths return normal catalogue rows, which `PluginUI` renders with the same
pagination, media-item and slideshow support as other views.

## Files and responsibilities

| File | Responsibility |
| --- | --- |
| `search.py` | Plain search terms and Query Model construction for global search |
| `search_index.py` | Normalization and per-media searchable document content |
| `query_model.py` | Versioned fields, operators, limits, parsing and SQL compilation |
| `saved_searches.py` | Saved-search name and record validation |
| `smart_filter_editor.py` | Kodi dialogs for building a validated query |
| `db/catalog.py` | Query execution, counts and saved-search persistence |
| `views.py` | Search UI, saved-search routes, rename/delete and smart row actions |
| `preferences.py`, `home_layout_editor.py` | Placement of saved smart collections on the home screen |

## Global text search

```text
user enters text
→ views.PluginUI.search()
→ search module normalizes terms
→ a versioned picture query is built
→ Catalog.query_pictures(query, limit, offset)
→ query_model compiles validated conditions
→ search-document rows are matched
→ normal paged Kodi result list
```

The indexed search document can include normalized filename, caption, keywords,
path parts, camera and stored location fields. Multiple search words use AND
semantics for the same media row.

Schema changes to the search document require migration and backfill planning;
see `docs/GLOBAL_SEARCH.md` and `docs/DATABASE_MIGRATIONS.md`.

## Query Model boundary

The Query Model is a security and compatibility contract. It defines:

- a model version;
- all/any group semantics;
- allowed fields;
- allowed operators per field;
- allowed sort keys and directions;
- length and rule-count limits;
- deterministic JSON representation.

A route or saved record must never provide raw SQL. SQL fragments and parameters
are compiled only after full validation against allowlists.

## Saved search lifecycle

```text
validated PictureQuery
→ deterministic JSON
→ Catalog.create_saved_search(name, query)
→ database record stores query version + JSON

open saved search
→ Catalog.get_saved_search(id)
→ saved_searches validates metadata
→ parse JSON
→ query_model validates again
→ execute current supported query
```

Stored queries are revalidated each time they are opened. This prevents corrupt,
unsupported or manually altered records from bypassing current limits.

Rename and delete operations also synchronize home-layout references so that a
home row does not silently point to a removed saved collection.

## Smart-filter editor

`SmartFilterEditor` is a Kodi UI builder for Query Model rules. It does not
construct SQL. It creates a draft, validates each candidate rule, previews the
count through the catalogue and returns a valid `PictureQuery` for saving.

When adding a filter field:

1. define and validate it in `query_model.py`;
2. add backend-neutral compilation and tests;
3. expose it in `smart_filter_editor.py` only when the Kodi UI can represent it
   clearly;
4. update docs and localization;
5. test saved-query reopen and invalid stored input.

## Smart home rows

A saved smart collection can be added to the Estuary MyPicsDB 3 home layout.
The row stores a reference to the saved search, not a frozen set of picture
IDs. Each widget reload runs the query again, so newly scanned matching media
appears automatically.

Changes can span:

- saved-search persistence;
- home-layout preference serialization;
- provider URL generation;
- widget item limits and artwork;
- Estuary templates and tests.

## Useful tests

- `tests/test_query_model.py`;
- `tests/test_global_search.py`;
- `tests/test_saved_searches.py`;
- `tests/test_smart_filter_editor.py`;
- `tests/test_catalog.py`;
- `tests/test_home_layout_editor.py`;
- `tests/test_home_screen_settings.py`;
- widget/Estuary tests for smart row changes.

## Invariants

- Raw SQL never crosses the route, setting or saved-search boundary.
- Stored JSON is revalidated on every open.
- Query compilation is deterministic and backend-neutral.
- Validation limits prevent unbounded rule trees and oversized values.
- Search-document schema changes include migration and backfill tests.
- Deleting or renaming a saved query keeps home-layout references consistent.
- Smart rows remain live queries rather than cached media-ID lists.
