# Database migrations

MyPicsDB 3 uses a versioned migration runner for both SQLite and
MySQL/MariaDB. Add-on version 0.2.13 introduced the framework. Version 0.2.15
raised the catalogue to schema version 2. Version 0.2.19 raised it to schema 3
with normalized global-search documents. Version 0.2.22 raises it to schema 4
with an explicit picture/video media type.

## Startup sequence

`Catalog.initialize()` delegates to `MigrationRunner`.

1. Inspect the database before structural writes.
2. Refuse a database whose `schema_version` is newer than the add-on supports.
3. Validate the registered migration path and checksums.
4. Acquire the catalogue-wide `schema-migration` lock. It conflicts with the
   `catalogue-scan` lock in both directions.
5. For SQLite, checkpoint WAL and create an atomic, integrity-checked backup.
6. For MySQL/MariaDB, verify the server connection and log a reminder that an
   external backup is required.
7. Register schema 1 as the baseline if the database predates migration
   history.
8. Apply each migration in version order and record its checksum.
9. Update `meta.schema_version` only in the same transaction as the migration
   record where the backend permits transactional DDL.

The add-on never attempts a downgrade.

## Schema 2: date browsing

Schema 2 adds `idx_pictures_date_browse` on:

```text
(is_missing, taken_year, taken_month, taken_day, taken_at)
```

The index supports the Years browser's year → month → day hierarchy. The
migration checks whether the index already exists before creating it, which
makes the MySQL/MariaDB DDL step safe to retry after an interrupted run. No
picture rows or metadata columns are rewritten. The decision and its trade-offs
are recorded in `docs/adr/0002-schema-2-date-browsing-index.md`.

## Schema 3: normalized global-search documents

Schema 3 adds `picture_search_documents` with one row per picture. The document
contains bounded NFKC/casefold tokens derived from filename, caption, keywords,
URI/path parts, camera and stored location fields.

The migration creates the table and rebuilds all documents from authoritative
picture and keyword data in batches of 500. It clears partial derived rows
before rebuilding, making a retry safe after an interrupted MySQL/MariaDB DDL
attempt. Search documents are maintained on later scanner inserts and updates.

The migration does not alter original files or rewrite picture metadata. Its
design is recorded in
`docs/adr/0005-schema-3-global-search-documents.md`.

## Schema 4: mixed picture and video media type

Schema 4 adds `pictures.media_type` with the default value `picture` and creates
`idx_pictures_media_type` on:

```text
(is_missing, media_type, taken_at)
```

Existing rows remain pictures. New opt-in video rows use `media_type=video` and
share the existing catalogue, date hierarchy, folders, favorites and search
index. The migration checks for both the column and index before creating them,
so a partially completed MySQL/MariaDB DDL step can be retried safely.

## SQLite backups

Backups are written under:

```text
<addon profile>/backups/
```

Names use the pre-migration schema version and a UTC timestamp. A backup is
first written as a `.partial` file, checked with `PRAGMA quick_check`, and then
renamed atomically. The transient migration-lock row is removed from the
backup so a restored database does not appear busy.

To restore, stop Kodi, preserve the failed database for diagnosis, copy the
chosen backup to `mypicsdb3.sqlite`, and start Kodi again. Keep the database,
`-wal`, and `-shm` files together when preserving a failed state.

## Adding schema version N

A schema change must include all of the following in one Git commit:

1. Increment `SCHEMA_VERSION` in `mypicsdb3/__init__.py`.
2. Update the fresh-database SQL in `db/schema.py` to represent the complete
   latest schema.
3. Add a deterministic module under `db/migration_steps/`, for example
   `v0002_saved_views.py`.
4. Export a `MigrationStep` with a stable name, pinned SHA-256 checksum, and an
   idempotent apply function.
5. Add it explicitly to `DEFAULT_MIGRATIONS` in `db/migrations.py`.
6. Add upgrade tests from every supported prior schema and a fresh-database
   test.
7. Test interrupted migration, checksum mismatch, lock conflict, and rerun.
8. Update this document and `CHANGELOG.md`.

Never edit the checksum of a released migration. Create a new migration
instead.

## MySQL/MariaDB rules

DDL may commit implicitly. Each migration must therefore be safe to inspect,
retry, and diagnose after partial execution. Prefer small, idempotent steps and
feature-detection queries over assumptions. Production operators must create
and verify an external database backup before installing a release that bumps
`SCHEMA_VERSION`.

## Inspection tools

Inspect the current SQLite catalogue without changing it:

```bash
python3 tools/inspect_current_schema.py /path/to/mypicsdb3.sqlite --output current-schema.json
```

Inspect MySQL/MariaDB:

```bash
python3 tools/inspect_current_schema.py mypicsdb3 \
  --backend mysql --host 127.0.0.1 --username kodi --password '...'
```

Create a read-only inventory of a legacy SQLite database:

```bash
python3 tools/inspect_legacy_schema.py /path/to/legacy.db --output legacy-schema.json
```

The same legacy inspector accepts `--backend mysql` together with the server
arguments used by `inspect_current_schema.py`.

The legacy tool only inventories structure, indexes, foreign keys, row counts,
and possible signatures. It is not an importer and deliberately makes no
unverified table mapping.
