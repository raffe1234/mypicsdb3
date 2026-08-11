# Database migrations

MyPicsDB 3 uses a versioned migration runner for both SQLite and
MySQL/MariaDB. Add-on version 0.2.13 introduced the framework. Version 0.2.15
raised the catalogue to schema version 2. Version 0.2.19 raised it to schema 3
with normalized global-search documents. Version 0.2.22 raised it to schema 4
with an explicit picture/video media type. Version 0.2.34 raised it to schema 5
with validated saved searches. Version 0.5.0 raises it to schema 6 with named
manual media collections and explicit item order. Version 0.6.0 raises it to
schema 7 with optional smart/manual collection music-playlist mappings. Version
0.8.11 raises it to schema 8 with optional per-source scan policies. Version
0.8.12 raises it to schema 9 with metadata mapping overrides and a per-picture
metadata-index fingerprint.

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

## Schema 5: saved searches

Schema 5 adds `saved_searches` with a user-facing name, the explicit Query
Model version, canonical Query Model JSON and creation/update timestamps. The
table is portable across SQLite and MySQL/MariaDB.

The add-on stores no raw SQL. Each saved query is parsed and validated again
when it is opened; malformed JSON, unknown fields, unsupported operators and
unknown query versions are rejected. Saved-search plugin URLs contain only the
database row ID, pagination and local display-policy parameters.

## Schema 6: manual media collections

Schema 6 adds two portable tables:

```text
collections
- id
- name
- created_at
- updated_at

collection_items
- collection_id
- picture_id
- position
- added_at
```

A collection stores only references to existing `pictures` rows. The composite
primary key prevents one media item from being added twice to the same
collection, while the unique collection/position key preserves a deterministic
manual order. Foreign keys cascade collection-item rows when a collection or a
cleaned-up media row is deleted; source files are never changed.

The migration creates empty tables and an item lookup index. It does not scan
sources, rewrite media metadata or populate collections automatically. Existing
schema-5 catalogues therefore upgrade without a rescan. SQLite and
MySQL/MariaDB use equivalent constraints, with backend-appropriate types and
DDL.

## Schema 7: collection music playlists

Schema 7 adds one portable mapping table:

```text
collection_music_playlists
- collection_type (`smart` or `manual`)
- collection_id
- playlist_uri
- updated_at
```

The composite primary key permits one optional playlist reference for each
saved smart or manual collection. Because the target can live in either
`saved_searches` or `collections`, the mapping deliberately has no polymorphic
foreign key. Catalogue deletion methods remove the mapping in the same
transaction as the target.

The migration creates an empty table only. It does not read playlist files,
scan music, rewrite collection contents or touch indexed media. Existing
schema-6 catalogues therefore upgrade without a rescan. SQLite enforces the two
allowed target-type values with a check constraint; application validation
provides the equivalent boundary for MySQL/MariaDB.


## Schema 8: per-source scan policies

Schema 8 adds one portable child table keyed by `sources.id`:

```text
source_scan_policies
- source_id
- recursive
- include_videos
- picture_extensions
- video_extensions
- exclude_fragments
- exclude_hidden
- updated_at
```

There is deliberately no row for the normal inherited case. A source without a
policy row uses the current global scan settings of the Kodi client that performs
the scan, preserving pre-0.8.11 behavior. Saving a custom source policy writes a
complete policy for the fields controlled by the source editor; choosing global
defaults deletes that row. Extension and exclusion lists are serialized as strict
JSON text arrays, but neither backend relies on database-native JSON operators.

The foreign key cascades the policy row when its source is deleted. The migration
creates an empty table only: it does not scan sources, rewrite media rows, mark
anything missing or touch original files. Policy changes are applied only by a
later scan. The scanner snapshots effective policies at scan start and includes
them in checkpoint compatibility, so a changed policy cannot resume from a folder
checkpoint produced under different discovery rules.

## Schema 9: metadata normalization and mapping overrides

Schema 9 adds a database-global override table and one nullable picture column:

```text
metadata_mapping_rules
- id
- source_type (`exif`, `xmp` or `iptc`)
- source_tag
- normalized_tag
- target_field (nullable = suppress/ignore)
- rule_priority
- created_at
- updated_at

pictures.metadata_index_hash
```

The override table stores only user customizations. Built-in rules remain in
`metadata_mapping.py` and intentionally reproduce the metadata precedence used by
0.8.11. The application validates source types and canonical target fields; raw
user text is never used as a table name, column name or SQL fragment. A unique
`(source_type, normalized_tag)` key makes one custom decision authoritative for
each raw tag. XMP tag identities use the XML property local name rather than a
producer-selected namespace prefix.

Scalar canonical fields use the lowest-priority mapped tag that yields a usable
value. `keywords` is multi-valued and combines all mapped values in priority
order. A custom rule with no target suppresses a built-in tag mapping; redirecting
a built-in tag replaces its default target/priority. Multiple raw tags may map to
the same canonical field. GPS, dimensions and orientation keep their existing
dedicated extraction paths in schema 9.

Mappings live in the catalogue rather than local Kodi settings. This is required
for shared MySQL/MariaDB deployments: every client reading/writing one catalogue
must normalize metadata under the same rule set. Changing a mapping does not
automatically launch a scan and never changes the original media file.

`pictures.metadata_index_hash` fingerprints the effective mapping together with
metadata extraction settings that affect indexed values (`read_xmp`, `read_iptc`,
GPS storage and bounded/deep read limits). Existing rows receive `NULL` during
migration. Consequently, the first later scan re-reads picture metadata once even
when size and mtime are unchanged, stores the new fingerprint and rebuilds derived
search data. Subsequent unchanged scans skip that work again. The same fingerprint
is part of scan-checkpoint compatibility, so a checkpoint created under different
metadata-index inputs cannot skip the required reindex.

The migration creates the new table and column only. It does not scan sources,
rewrite canonical metadata during startup, mark rows missing or touch source
files. SQLite receives the normal pre-migration verified backup; MySQL/MariaDB
operators remain responsible for external backups.

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
