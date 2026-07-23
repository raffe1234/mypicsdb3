# Database migrations

MyPicsDB 3 uses a versioned migration runner for both SQLite and
MySQL/MariaDB. Add-on version 0.2.13 introduces the framework while the
catalogue remains on schema version 1.

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
