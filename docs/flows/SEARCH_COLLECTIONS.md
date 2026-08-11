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
pagination, media-item and slideshow support as other views. From version 0.8.16
these query-backed result pages can also be frozen into a new manual collection;
the snapshot keeps media IDs and order, not the dynamic query.

## Files and responsibilities

| File | Responsibility |
| --- | --- |
| `search.py` | Plain search terms and Query Model construction for global search |
| `search_index.py` | Normalization and per-media searchable document content |
| `query_model.py` | Versioned fields, operators, limits, parsing and SQL compilation |
| `saved_searches.py` | Saved-search name and record validation |
| `smart_filter_editor.py` | Kodi dialogs for building a validated query |
| `attention.py` | Built-in missing-metadata Query Model presets |
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
count through the catalogue and returns a valid `PictureQuery` for saving. Its
main XML dialog keeps Cancel and Save as persistent right-hand buttons while
criteria, Add criterion and Preview results remain in the scrolling list. Small
field/value choices continue to use native Kodi select dialogs.

Version 0.8.13 exposes more of Query Model v1 without adding another query
language. **Is not** uses a controlled one-rule negated group; **Exists** and
**Missing** reuse allowlisted `is_not_null` / `is_null` operators. Rating can be
matched exactly, at least, at most or within an inclusive range. MIME type is a
normal scalar facet alongside file extension and stored location values.

When adding a filter field:

1. define and validate it in `query_model.py`;
2. add backend-neutral compilation and tests;
3. expose it in `smart_filter_editor.py` only when the Kodi UI can represent it
   clearly;
4. update docs and localization;
5. test saved-query reopen and invalid stored input.

## Needs attention presets

`attention.py` defines four built-in, read-only Query Model presets:

- pictures without capture date;
- pictures without camera metadata;
- pictures with no canonical country/state/city/sublocation value;
- pictures without keywords.

`PluginUI.needs_attention()` counts each preset through
`Catalog.count_query_pictures()`, then `needs_attention_result()` pages it with
`Catalog.query_pictures()`. The presets explicitly select pictures rather than
videos, exclude catalogue rows already marked missing and follow the ordinary
minimum-rating display policy. They never trigger scanning or metadata writes.

## Freezing query results into a manual collection

The **Save current results as collection** action is available for global search,
saved smart collections, curated Browse metadata values and Needs attention
presets. Kodi routes carry only enough information to reconstruct the trusted
query (`q`, saved-search ID, metadata facet/value or preset key). `views.py`
revalidates that reference, counts the current result for confirmation and passes
the resulting `PictureQuery` to `Catalog.create_collection_snapshot()`.

The catalogue compiles the Query Model through the normal allowlisted compiler,
selects the complete ordered media-ID list once inside the same transaction that
creates the collection, and stores compact `collection_items.position` values.
Only IDs and timestamps are persisted. The query JSON is not copied into the
manual collection and source media is never copied or modified. A later scan may
change the live smart/search result without changing the snapshot.

This is deliberately different from saving a smart collection: **smart = live
query**, **snapshot = static membership**.

## Exporting a query result

Version 0.8.17 adds **Export current results** to the same query-backed pages.
The route carries only the safe search/saved-search/metadata/preset reference;
`views.py` reconstructs and revalidates the `PictureQuery`, then
`Catalog.ordered_query_picture_ids()` freezes the complete deterministic result
order once. Export therefore follows the same rating-policy override and Query
Model semantics as the page the user is viewing.

Unlike a collection snapshot, export does not write collection membership. The
ordered IDs are passed to the dedicated COPY-only export flow described in
[Safe media export](EXPORT.md). Raw query JSON and SQL never cross the Kodi route
boundary or enter the manifest.

## Dynamic Home rows

A saved smart collection can be added to the Estuary MyPicsDB 3 home layout.
The row stores a reference to the saved search, not a frozen set of picture
IDs. Each widget reload runs the query again, so newly scanned matching media
appears automatically. The same combined editor can add a manual collection,
whose provider preserves its stored media order. Estuary calls fixed
`home-smart?slot=N` and `home-collection?slot=N` providers; the plug-in resolves
the database ID from each materialized slot setting. Cancel, Save and Defaults
remain persistent on the right.

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
- Built-in Needs attention views use the same Query Model compiler as saved
  smart collections; they do not introduce a second filtering path.
- Stored JSON is revalidated on every open.
- Query compilation is deterministic and backend-neutral.
- Validation limits prevent unbounded rule trees and oversized values.
- Search-document schema changes include migration and backfill tests.
- Deleting or renaming a saved query keeps home-layout references consistent.
- Smart rows remain live queries rather than cached media-ID lists.
- Snapshot routes never carry raw Query Model JSON; the query is reconstructed and revalidated.
- A manual snapshot stores only the selected media IDs and deterministic order.
