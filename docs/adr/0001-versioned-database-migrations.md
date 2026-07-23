# ADR 0001: Versioned database migrations

- Status: Accepted
- Date: 2026-07-23

## Context

The original schema initializer created missing objects before checking whether
the database was newer than the running add-on. There was no durable migration
history, no pre-migration SQLite backup, and no shared lock policy between
scanning and schema changes. Future functions require several schema versions
and must work on both SQLite and MySQL/MariaDB.

## Decision

Use a central `MigrationRunner` with:

- a `schema_migrations` history table;
- pinned checksums for every released step;
- schema 1 registered as an immutable baseline;
- read-only inspection before structural writes;
- refusal of newer schemas without modifying them;
- an atomic SQLite backup before existing-database changes;
- MySQL/MariaDB preflight plus an explicit external-backup requirement;
- a catalogue-wide migration lock that conflicts with scanning;
- one ordered migration path shared by all callers.

The current schema stays at version 1. This ADR establishes infrastructure only
and does not introduce saved views, collections, metadata facets, search, or
export tables.

## Consequences

Fresh databases gain migration history immediately. Existing schema-1 SQLite
databases receive one verified backup when history is bootstrapped. Released
migration checksums become immutable. MySQL/MariaDB migrations must be designed
for implicit DDL commits and safe reruns.
