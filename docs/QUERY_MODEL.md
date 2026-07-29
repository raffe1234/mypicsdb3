# Query Model version 1

MyPicsDB 3 version 0.2.18 introduced an internal, versioned Query Model for
search, smart filters, saved views and smart collections. Version 0.2.19 uses
it for Kodi global search. Version 0.2.34 stores canonical version-1 Query
Model JSON for named saved searches in database schema 5. Version 0.3.0 adds a
Kodi smart-filter editor for a safe, flat all/any subset of the model.

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
| `taken_date` | inclusive ISO dates | `between` |
| `camera` | object with `make` and/or `model` | `eq` |
| `keyword` | exact keyword or keyword list | `eq`, `in` |
| `text` | normalized free text | `contains_tokens` |
| `media_type` | `picture`, `video`, or a list of both | `eq`, `in` |

Keyword matching is exact after `casefold()`, matching the normalized keyword
stored by the scanner. A single `keyword in [...]` rule means any listed
keyword. Multiple keyword rules inside an `all` group require all of them.

The `text` rule uses NFKC normalization, Unicode case folding and alphanumeric
tokens. Multiple words in one `contains_tokens` value mean AND. The compiler
matches bound parameters against schema-3 normalized search documents; raw
search text is never copied into SQL.

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
counts the same selection. Page limits are restricted to 1 through 1000 and
offsets must be non-negative.

The query model's `default_policy.apply_min_rating` flag controls whether the
Kodi client's current local minimum-rating display policy is included. It does
not alter stored ratings or scanner behaviour.

The public compiler result contains reusable `where_sql`, `params` and
`order_by_sql` fragments. Future preview and facet consumers must build on
these fragments rather than introduce separate user-defined SQL paths.

## Kodi editor scope in 0.3.0

The editor exposes one flat group using **all criteria** or **any criterion**.
It supports text, date range, minimum rating, favorite state, source, camera,
keyword and media type, plus sort order and the global-rating-policy toggle. It
previews the count and up to ten filenames before saving the query in schema 5.

Deliberately not included:

- nested or negated groups in the Kodi dialog;
- phrase, fuzzy, prefix or relevance-ranked search;
- raw SQL compatibility mode;
- query JSON in saved-search plugin URLs; they reference a database ID.

Those features can be added in separate reviewable releases while retaining
Query Model version 1 or introducing an explicit later version.
