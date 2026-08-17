# Query Model version 1

MyPicsDB 3 version 0.2.18 introduced an internal, versioned Query Model for
search, smart filters, saved views and smart collections. Version 0.2.19 uses
it for Kodi global search. Version 0.2.34 stores canonical version-1 Query
Model JSON for named saved searches in database schema 5. Version 0.3.0 adds a
Kodi smart-filter editor for a safe, flat all/any subset of the model. Version
0.8.10 adds backward-compatible metadata facets without changing Query Model
version 1. Version 0.8.12 adds database-global metadata normalization/mapping
upstream of the Query Model; the model itself remains version 1 because queries
continue to target the same canonical catalogue fields. Version 0.8.13 expands
the Kodi editor and built-in consumers only: controlled **Is not** choices use
the model's already-supported negated groups, while existing presence and rating
operators are exposed without changing the stored query format.

## Goals

The model provides one validated representation for picture selection across
SQLite and MySQL/MariaDB. It prevents callers from placing raw SQL, table names,
column names, operators or sort fragments in query data.

A query is parsed into immutable Python objects, normalized, and compiled to:

- a trusted `WHERE` fragment using the internal picture alias `p`;
- a tuple of bound parameters;
- an allowlisted, stable `ORDER BY` fragment ending in `p.id`.

`DatabaseEngine` translates the model's `?` placeholders to `%s` for
MySQL/MariaDB.

## Version 1 JSON

```json
{
  "version": 1,
  "root": {
    "type": "group",
    "match": "all",
    "negated": false,
    "children": [
      {
        "type": "rule",
        "field": "text",
        "operator": "contains_tokens",
        "value": "summer stockholm"
      },
      {
        "type": "rule",
        "field": "taken_date",
        "operator": "between",
        "from": "2018-01-01",
        "to": "2022-12-31"
      },
      {
        "type": "rule",
        "field": "rating",
        "operator": "gte",
        "value": 3
      },
      {
        "type": "rule",
        "field": "keyword",
        "operator": "eq",
        "value": "summer"
      }
    ]
  },
  "sort": [
    {"field": "taken_at", "direction": "desc"},
    {"field": "id", "direction": "desc"}
  ],
  "scope": {
    "source_ids": [],
    "include_missing": false,
    "include_excluded": false
  },
  "default_policy": {
    "apply_min_rating": true
  }
}
```

Groups support `match: all` and `match: any`. Setting `negated` to `true`
negates the whole group. This permits nested all/any/not expressions without
adding operator-specific raw fragments.

## Supported fields and operators

| Field | Value | Operators |
| --- | --- | --- |
| `rating` | integer 0 through 5 | `eq`, `gte`, `lte`, `between`, `is_null`, `is_not_null` |
| `favorite` | boolean | `eq` |
| `source` | positive source ID or ID list | `eq`, `in` |
| `album` | positive folder/album ID or ID list | `eq`, `in` |
| `taken_date` | inclusive ISO dates | `between`, `is_null`, `is_not_null` |
| `camera` | object with `make` and/or `model` | `eq`, `is_null`, `is_not_null` |
| `keyword` | exact keyword or keyword list | `eq`, `in`, `is_null`, `is_not_null` |
| `text` | normalized free text | `contains_tokens` |
| `media_type` | `picture`, `video`, or a list of both | `eq`, `in` |
| `extension` | extension without a required leading dot | `eq`, `in` |
| `mime_type` | normalized MIME string | `eq`, `in`, `is_null`, `is_not_null` |
| `country`, `state`, `city`, `sublocation` | exact stored metadata text | `eq`, `is_null`, `is_not_null` |
| `aspect` | `landscape`, `portrait`, `square`, or a list | `eq`, `in` |

Keyword matching is exact after `casefold()`, matching the normalized keyword
stored by the scanner. A single `keyword in [...]` rule means any listed
keyword. Multiple keyword rules inside an `all` group require all of them.

The `text` rule uses NFKC normalization, Unicode case folding and alphanumeric
tokens. Multiple words in one `contains_tokens` value mean AND. The compiler
matches bound parameters against schema-3 normalized search documents; raw
search text is never copied into SQL.

`extension` and `mime_type` values are normalized to lowercase. Location values
use the exact stored metadata text selected from the catalogue. `aspect` is
derived from stored width and height; EXIF orientations 5 through 8 swap the
display axes before landscape/portrait comparison. Rows without usable
dimensions do not match an aspect rule.


Metadata mapping happens during indexing, before Query Model evaluation. Custom
EXIF/XMP/IPTC rules may therefore change canonical values such as `camera`,
`keyword`, `country`, `state`, `city` or `sublocation` after a reindex without
changing saved query JSON. Saved queries remain structurally compatible and simply
operate on the current canonical catalogue values.

Allowed sort fields are `taken_at`, `discovered_at`, `rating`, `filename` and
`id`, in ascending or descending order. The normalizer always places `id` last
as a deterministic pagination tie-breaker.

## Validation limits

Version 1 enforces:

- at most three group levels;
- at most 50 rules;
- at most 100 values in list rules or source scope;
- at most 512 characters in a normal string or search query;
- at most 12 distinct search words and 191 characters per search word;
- strict booleans and integers, so `true` is not accepted as integer `1`;
- registered fields and operators only;
- no unknown object members;
- ISO `YYYY-MM-DD` capture-date ranges;
- `include_excluded: false` until an exclusion model exists.

Unknown query versions are rejected rather than guessed or silently upgraded.

## Deterministic JSON

`canonical_picture_query_json()` returns normalized UTF-8 JSON with sorted
object keys and compact separators. Source IDs and list-rule values are
normalized and duplicate values removed. Text-search values are serialized as
canonical space-separated tokens. This representation is used by schema-5 saved searches. The stored query model
version and JSON are revalidated every time a saved search is opened.

## Catalogue integration

`Catalog.query_pictures(query, limit, offset)` runs a validated query and
returns the existing picture-row shape. `Catalog.count_query_pictures(query)`
counts the same selection. `Catalog.query_facet_counts(query, field, limit)`
returns bounded counts for allowlisted scalar metadata facets (`extension`,
`mime_type`, `country`, `state`, `city`, `sublocation`) using that same compiled
selection and bound parameters. Page limits are restricted to 1 through 1000;
facet limits are restricted to 1 through 500; offsets must be non-negative.

The query model's `default_policy.apply_min_rating` flag controls whether the
Kodi client's current local minimum-rating display policy is included. It does
not alter stored ratings or scanner behaviour.

The public compiler result contains reusable `where_sql`, `params` and
`order_by_sql` fragments. Future preview and facet consumers must build on
these fragments rather than introduce separate user-defined SQL paths.

## Kodi editor scope in 0.8.13

The editor exposes one flat group using **all criteria** or **any criterion**.
It supports text, date, rating, favorite state, source, camera, keyword, media
type, file extension, MIME type, stored country/state/city/sublocation and image
shape, plus sort order and the global-rating-policy toggle. Value fields can use
**Is** / **Is not** where the UI presents equality; date, rating, camera,
keyword, MIME and location fields expose the Query Model's existing
`is_null`/`is_not_null` checks as **Missing** / **Exists**. Rating also exposes
exact, lower-bound, upper-bound and inclusive-range operators. File, MIME and
location choices use bounded facet counts from the validated query selection.
The editor previews the count and up to ten filenames before saving the query in
schema 5.

The editor does not add a separate `neq` SQL operator. User-facing **Is not** is
serialized as a single-child Query Model group with `negated=true` around the
same validated equality rule. This keeps SQL generation inside the compiler and
keeps already-saved version-1 JSON valid.

Version 0.8.13 also adds **Needs attention** presets. They are ordinary
`PictureQuery` objects for pictures missing capture date, camera, all four
canonical location fields, or keywords. Counts and result pages use
`Catalog.count_query_pictures()` / `Catalog.query_pictures()`; no special raw-SQL
path, rescan or source-file write is introduced.

Deliberately not included:

- arbitrary nested/negated group construction in the Kodi dialog beyond the
  controlled single-rule **Is not** wrapper;
- phrase, fuzzy, prefix or relevance-ranked search;
- raw SQL compatibility mode;
- query JSON in saved-search plugin URLs; they reference a database ID.

Those features can be added in separate reviewable releases while retaining
Query Model version 1 or introducing an explicit later version.
## Browse metadata in 0.8.14

The **Browse metadata** UI does not add Query Model fields or increment the model
version. `metadata_browser.py` exposes curated Camera, Location, Capture, Image and
Keywords facets. `Catalog.query_facet_counts()` enumerates their values through a
separate fixed internal allowlist with a maximum page size and offset; camera make/model,
capture year and aggregate aspect/rating/keyword keys are therefore catalogue facet
identifiers, not persisted query fields. Selecting a value is converted into existing
Query Model v1 rules (for example camera make -> `camera eq`, capture year -> a bounded
`taken_date between`, and keyword -> `keyword eq`) before result rows are fetched.

This separation is intentional: aggregate SQL remains backend-owned and allowlisted,
while every user-visible result selection still crosses the validated Query Model boundary.
## Manual collection snapshots in 0.8.16

Version 0.8.16 can freeze selected query-backed result pages into a manual
collection. The originating query is reconstructed from safe route references,
revalidated and compiled through this same version-1 boundary. The catalogue
then selects the complete ordered media-ID set once inside the collection write
transaction. The manual collection stores only those IDs and positions: it does
not persist a second copy of Query Model JSON and does not become another dynamic
query type.

This preserves the distinction between a saved smart collection (live query) and
a manual snapshot (static membership) without changing Query Model version 1.

## Safe exports in 0.8.17

Export does not add a query language or change Query Model version 1. Query-backed
export routes carry only the same safe references used by interactive result
pages: global search text, saved-search ID, curated metadata facet/value or a
built-in Needs attention key. `views.py` reconstructs and revalidates the
`PictureQuery`, then `Catalog.ordered_query_picture_ids()` compiles it through
the normal allowlisted boundary and freezes the complete deterministic ID order.
Manual collections instead freeze their stored visible order through
`ordered_collection_picture_ids()`.

The exporter receives IDs, not SQL or raw Query Model JSON. The export manifest
does not persist Query Model JSON. This keeps export selection semantics aligned
with normal browsing, including the current minimum-rating display policy,
without changing the stored-query contract.

## Metadata refresh does not change Query Model v1

Version 0.8.23 can explicitly re-read one indexed picture or the still pictures
directly in one indexed folder. Refresh updates the same canonical columns, tags and
normalized search document already consumed by Query Model v1; it does not add a
query field, operator or persisted query shape. A refreshed camera/location value is
therefore immediately visible to existing Browse metadata, Needs attention, saved
smart collections and global search rules without a Query Model version bump.

The diagnostics action is not a query source. Fresh extractor values are displayed
locally for one selected picture and are not queryable until the user explicitly
refreshes the catalogue row.

Version 0.8.27 can recognize additional XMP location/GPS representations during a
metadata read, but it does not add a Query Model field or operator and does not force
a whole-library reindex. Once an explicit refresh stores a newly recognized canonical
location value, existing Query Model v1 facets/searches consume it exactly like any
other stored location metadata.
