# ADR 0005: Schema 3 normalized global-search documents

- Status: Accepted
- Date: 2026-07-24
- Add-on version: 0.2.19
- Database schema: 3

## Context

Global search must handle about 135,000 pictures, preserve Swedish and other
Unicode letters, use AND semantics for multiple words, and behave the same on
SQLite and MySQL/MariaDB. Searching every raw metadata column with independent
`LIKE` expressions would duplicate query logic, make Unicode normalization
backend-dependent and repeatedly join keyword tables.

SQLite FTS5 and MySQL FULLTEXT are not guaranteed to be available or to provide
identical token behavior. The project also requires small, reviewable schema
migrations and no raw SQL in user query data.

## Decision

Raise the catalogue to schema 3 and add exactly one
`picture_search_documents` row per picture. Build a bounded, space-padded token
document in Python using NFKC normalization, Unicode case folding and the same
tokenizer used for query input.

Index filename, caption, keywords, URI/path parts, camera make/model and stored
location fields. Maintain the document on picture insert/update and backfill
existing pictures in batches during the schema-2-to-3 migration.

Extend Query Model version 1 with the allowlisted `text` field and
`contains_tokens` operator. Compile it to bound `LIKE` parameters over the
normalized document. Multiple tokens are ANDed.

Do not require FTS/FULLTEXT, add phrase or fuzzy semantics, store local search
history in the shared database, or add generic metadata facets in this release.

## Consequences

- Search semantics and Unicode normalization are backend-neutral.
- Existing SQLite catalogues receive the normal verified migration backup.
- MySQL/MariaDB operators must have an external backup before upgrade.
- Migration performs a bounded batch backfill and can be retried; the table is
  rebuilt from authoritative picture and keyword data.
- Search performs a scan of compact documents. Large-library performance must
  be measured before deciding whether an optional accelerator is needed.
- Future saved views can reuse the same Query Model rule without storing raw
  SQL or Kodi-specific URLs.
