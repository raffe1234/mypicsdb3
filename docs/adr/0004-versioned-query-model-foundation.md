# ADR 0004: Use one versioned Query Model for future dynamic picture queries

- Status: accepted
- Date: 2026-07-24
- Add-on version: 0.2.18
- Database schema: 2, unchanged

## Context

Global search, smart filters, saved views and smart collections all need to
select pictures dynamically. Implementing a separate SQL builder for each
feature would create inconsistent semantics, duplicate backend-specific code
and risk storing raw SQL fragments in shared data.

The project must support both SQLite and MySQL/MariaDB, retain stable
pagination, respect the local minimum-rating display policy when requested and
reject malformed or hostile query data before database execution.

## Decision

Introduce Query Model version 1 as a strict JSON-compatible representation with:

- nested `all` and `any` groups plus group negation;
- an allowlist of fields, operators and sort columns;
- strict value types and bounded depth, rule counts, lists and strings;
- normalized, deterministic JSON;
- backend-neutral `?` placeholders converted by `DatabaseEngine`;
- a stable unique-ID sort tie-breaker;
- scope for source IDs and missing pictures;
- an explicit `apply_min_rating` default-policy flag.

The initial field set covers rating, favorite, source, album/folder, capture-date
range, exact camera and exact keyword rules. The catalogue exposes page and
count methods that consume only validated Query Model data.

Do not add query storage, search indexes, saved views, collections or a Kodi
query editor in this release. Keep database schema 2 unchanged.

## Consequences

Future dynamic features have one validation and compilation boundary instead of
embedding their own SQL. User values are always bound parameters, while table,
column, operator and sort fragments come only from code allowlists.

Unknown versions and unsupported fields fail explicitly. Adding semantics that
cannot be represented compatibly requires a later model version. Search,
preview, facets and saved views can build on the same compiled predicate and
stable ordering in separate patches.
