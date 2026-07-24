# ADR 0002: Schema 2 date-browsing index

- Status: Accepted
- Date: 2026-07-23

## Context

The migration foundation introduced in version 0.2.13 deliberately retained
schema version 1. The Years browser later needed a stable year → month → day
hierarchy that performs consistently on both SQLite and MySQL/MariaDB without
rewriting picture metadata or introducing a broader query language.

The existing picture rows already store normalized capture-date components.
The missing piece was an index matching the browser predicates and ordering.

## Decision

Raise the catalogue to schema version 2 and add
`idx_pictures_date_browse` on:

```text
(is_missing, taken_year, taken_month, taken_day, taken_at)
```

The migration checks whether the index already exists before creating it. This
keeps the step safe to retry on MySQL/MariaDB, where DDL may commit implicitly.
The same complete index definition is included in the fresh-database schema.

Use the index for a year-first browser that drills down through month and day
before listing pictures. Pictures without an embedded capture date are exposed
through a separate **No date** folder. This change does not add saved queries,
search, collections or generic metadata filtering.

## Consequences

Fresh and upgraded catalogues share schema version 2 and the same logical
index on both supported database backends. Date browsing avoids broad scans of
the pictures table and can be benchmarked independently before introducing a
common Query Model.

Existing schema-1 SQLite catalogues receive the migration runner's verified
backup before the index is added. MySQL/MariaDB operators must create and verify
an external backup. Real Kodi migration, backup/restore and large-library
performance still require documented manual validation.
