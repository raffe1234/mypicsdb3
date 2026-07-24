# ADR 0003: Global minimum rating is a display policy

- Status: accepted
- Date: 2026-07-24
- Add-on version: 0.2.16
- Database schema: 2, unchanged

## Context

Picture ratings are extracted from embedded metadata and stored in the shared
catalogue. Different Kodi clients can still need different visibility rules.
Filtering during scanning would discard useful metadata, make shared-database
behaviour surprising and require a rescan whenever the preference changes.

The catalogue also distinguishes two states that are easy to conflate:

- `NULL`: no rating was found in the indexed metadata;
- `0`: an explicit zero rating was found.

## Decision

The global minimum-rating threshold is stored as a local Kodi add-on setting and
is applied only when reading normal browser and widget data.

The supported policies are:

- all pictures: `NULL`, 0 and 1 through 5;
- rated and unrated: `NULL` and 1 through 5, excluding explicit 0;
- 1+, 2+, 3+, 4+ and 5.

A single validated helper creates the backend-neutral SQL predicate. Counts,
pagination and representative artwork use the same predicate as picture rows.
The policy applies to albums, date navigation, camera and keyword navigation,
favorites, rated and geotagged views, and home-screen widgets.

Status, diagnostics, maintenance, scanning and metadata storage do not use the
policy. The active policy is visible in Kodi. A route-local `all` override lets
the user browse all pictures temporarily without changing the saved setting.

## Consequences

- No database migration or rescan is required.
- SQLite and MySQL/MariaDB retain the same logical behaviour.
- A shared catalogue can have different local display policies on different
  Kodi clients.
- Future Query Model requests can add an explicit `apply_min_rating` flag
  without changing the meaning of the local default policy.
