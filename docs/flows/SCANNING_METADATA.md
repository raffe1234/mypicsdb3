# Scanning, filesystems, metadata and catalogue writes

This guide follows a manual or automatic catalogue scan. This is one of the
highest-risk areas because an incorrect change can misclassify a temporarily
unavailable source as deleted media.

## Entry paths

A scan can be requested through the plug-in UI or scheduled by the service:

```text
manual action in views.py ─┐
                           ├→ Scanner.scan_sources()
automatic service scan ────┘
```

Both paths create the same scanner with a catalogue, filesystem, settings,
cancellation callback, progress callbacks and checkpoint store.

Widget routes never start scans.

## Main scan flow

```text
Scanner.scan_sources(optional source ids)
→ load enabled sources
→ resolve/freeze effective scan policy for every selected source
→ for SQLite only, recover a scan lock left by a previous Kodi process
→ acquire shared scan lock
→ mark older unfinished scan-run rows interrupted while ownership is exclusive
→ prepare compatible local checkpoint
→ skip sources already completed in that checkpoint
→ Scanner.scan_source(source)
   → verify source root
   → restore folder stack or start at root
   → apply that source's recursion/exclusion/media-type policy
   → list directories through CancellationAwareFilesystem
   → upsert folder
   → stat supported media files
   → reuse unchanged rows or extract metadata
   → insert/update media and search document
   → commit completed folder
   → save atomic checkpoint
   → after complete traversal, mark unseen rows missing
   → update folder summaries
→ complete checkpoint
→ release scan lock
→ report statistics
```

## Files and responsibilities

| File | Responsibility |
| --- | --- |
| `scanner.py` | Traversal, locks, cancellation, changed-file decisions and writes |
| `filesystem.py` | Kodi VFS/local I/O abstraction and cancellation-aware wrapper |
| `metadata.py` | Bounded EXIF, XMP and optional IPTC extraction plus bounded local diagnostic summaries |
| `metadata_refresh.py` | Explicit serial re-read of already indexed still pictures/folders |
| `metadata_mapping.py` | Canonical fields, built-in/custom mapping rules, priority/merge semantics and metadata-index fingerprint |
| `models.py` | Source, file stat, metadata and scan-stat structures |
| `source_scan_policy.py` | Strict per-source policy normalization, inheritance values and checkpoint payload |
| `scan_checkpoint.py` | Compatible resumable folder state in the local profile |
| `db/catalog.py` | Source, folder, media, tag, search-document and scan-run writes |
| `db/locks.py` | Named lock constants and lock support |
| `views.py` | Manual scan action and progress presentation |
| `service_loop.py` | Automatic scheduling and playback-aware scan behaviour |
| `kodi.py` | Shared scan status, cancellation and background progress adapters |

## Source safety

A source has three distinct situations:

1. **Unavailable root**: do not traverse and do not mark existing rows missing.
2. **Partial traversal**: keep successful writes, report partial status and do
   not mark unseen rows missing.
3. **Complete, non-cancelled traversal**: unseen rows may be soft-marked
   missing after the traversal completes.

This distinction is required for SMB, NFS and NAS use. An empty result from a
failed listing is not evidence that a folder is genuinely empty.


## Per-source policy and inheritance

Schema 8 stores only explicit overrides in `source_scan_policies`. Absence of a
row means **use global defaults**. This is important for compatibility: upgrading
from 0.8.10 does not silently freeze old global values into the shared database.

When a scan starts, `Scanner` resolves one complete effective policy per selected
source and snapshots the database-global metadata mapping overrides. It keeps both
snapshots for the whole scan. A shared MariaDB policy is
therefore visible to every client, while a source without an override follows the
local global settings of whichever client actually scans it. Changing a policy
does not start a scan and never changes original files. On the next complete
scan, catalogue rows that are no longer in policy scope can be soft-marked
missing; normal retention/cleanup rules remain separate. Synology `@eaDir` trees
remain unconditionally excluded even if a custom policy has no exclusions.

## Scan lock

`Scanner` obtains a named catalogue lock before scanning. The lock has an owner
identifier and time-to-live. Long scans refresh it periodically, including
around filesystem activity. If refresh proves that ownership was lost, the scan
must stop rather than continue writing under a false assumption of exclusivity.

The lock matters especially for a shared MySQL/MariaDB catalogue used by more
than one Kodi device.

### Crash recovery

A hard Kodi/process crash cannot execute the scanner's normal `finally` cleanup.
Version 0.8.15 therefore distinguishes the supported backends deliberately:

- local SQLite scan owners include `hostname:pid:token`; before acquiring a new
  scan lock, a scanner may remove an existing SQLite scan lock only when the
  hostname matches the current machine, the recorded process id differs from
  the current Kodi process and that recorded process is confirmed absent. A
  same-process or uncertain lock is preserved;
- shared MySQL/MariaDB never uses that process shortcut. Another Kodi device may
  legitimately own the lock, so heartbeat refresh and TTL expiry remain the
  authority;
- after a scanner has successfully obtained exclusive ownership, it converts any
  older `scan_runs` rows still marked `running` to `interrupted` before creating
  the next source run. This cannot race another valid scanner because ownership
  is already exclusive;
- the automatic service retries a busy scan after 60 seconds rather than waiting
  the configured multi-hour scan interval.

Do not generalize SQLite crash recovery into "delete any inconvenient lock". The
backend distinction is intentional and protects shared catalogues.

## Cancellation

Cancellation is cooperative and safe:

- Kodi or the user requests a stop;
- the scanner checks at file/folder boundaries and through the wrapped
  filesystem;
- current bounded I/O can finish;
- the scan records cancellation and preserves a compatible checkpoint;
- missing marking is skipped for unfinished traversal.

Do not replace this with forceful thread termination or a cancellation check
that occurs only between whole sources.

## Checkpoints

Checkpoints are local to each Kodi profile, even when the catalogue is shared.
They record the folder stack and accumulated statistics after fully completed
folders.

A checkpoint is reused only if relevant inputs are unchanged, including:

- enabled source selection;
- database identity;
- each source's effective recursion, picture/video extensions, video inclusion, exclusions and hidden-file policy;
- the metadata-index fingerprint, which covers effective metadata mappings and
  metadata extraction settings that affect indexed values.

When changing scanner inputs, update checkpoint compatibility tests so that a
stale checkpoint cannot skip files that have become newly eligible.

## Metadata path

For a changed picture:

```text
media URI
→ Filesystem.stat()
→ metadata.extract_metadata()
→ bounded/materialized read when required
→ EXIF values
→ embedded XMP values
→ optional IPTC values for JPEG
→ built-in + database override mapping rules
→ canonical MetadataResult
→ scanner record
→ Catalog.insert_picture() or update_picture()
→ tags and normalized search document
```

For optional video rows, the scanner uses MIME inference and file modification
time rather than a full video metadata scraper.

## Unchanged files

The scanner compares stored size, modification information and
`metadata_index_hash` before deciding to reuse a picture row. The hash covers the
effective mapping plus metadata extraction settings. An unchanged item with a
matching hash is touched as seen without repeating expensive metadata work. If the
mapping or extraction inputs change, the next scan re-reads metadata even when
size/mtime are unchanged and then stores the new hash. Schema-9 upgrades leave old
rows without this hash deliberately, causing one safe metadata reindex. Changes to
this rule can have large performance and correctness effects on NAS libraries and
require regression tests.

## Explicit metadata refresh (0.8.23)

Normal incremental scanning deliberately avoids opening an unchanged picture when
size, mtime and `metadata_index_hash` still match. Version 0.8.23 adds a separate
user-requested path when the catalogue needs a metadata re-read without a full source
traversal:

```text
indexed picture id
→ MetadataRefresher
→ acquire metadata-refresh catalogue lock
→ Filesystem.stat(existing URI)
→ metadata.extract_metadata(current settings + mappings)
→ Catalog.refresh_picture_record()
→ normalized tags + search document
→ refresh affected folder summary
→ release lock
```

The exact-folder action first freezes the IDs of available still pictures directly
in that folder and processes them serially. It is cancellable between files, does not
include child folders, does not discover new media and never performs missing marking.
`last_seen_at` is preserved because a metadata refresh is not proof of a complete
source traversal.

`metadata-refresh`, `catalogue-scan` and `schema-migration` are mutually conflicting
writers. A scan also recovers a stale process-owned SQLite metadata-refresh lock left
by a crashed local Kodi process; shared MariaDB does not break remote ownership and
continues to rely on normal TTL/lock semantics.

**Metadata diagnostics** uses the same extractor for one picture but does not acquire
a writer lock and does not update the catalogue. It is intended to answer whether a
blank indexed field is stale or whether the current extractor also fails to see the
metadata Kodi's native picture info may display.

## Missing records and cleanup

Missing marking is soft. Rows are retained for the configured period. A
separate cleanup action deletes old missing rows. Do not combine source scanning
with immediate irreversible deletion.

## Useful tests

- `tests/test_scanner.py`;
- `tests/test_background_source_scan.py`;
- `tests/test_scan_checkpoint.py`;
- `tests/test_service_scan_progress.py`;
- service cancellation and shutdown tests;
- `tests/test_metadata.py`;
- `tests/test_metadata_refresh.py`;
- `tests/test_metadata_mapping.py`;
- `tests/test_catalog.py`;
- `tests/test_database_busy_handling.py`;
- `tests/test_mysql_integration.py` for shared-backend changes.

Search the suite for `partial`, `missing`, `checkpoint`, `cancel` and
`acquire_lock` before changing this flow.

## Large-library performance and concurrency

The scanner currently processes eligible files serially. First scans and explicit
metadata reindexes therefore reflect the cost of one filesystem stat plus bounded
metadata inspection per picture; SMB/NFS latency and other Kodi library scanners
using the same storage can dominate wall-clock time. Once a row's file size, mtime
and metadata-index fingerprint still match, later incremental scans reuse indexed
metadata instead of opening the picture again.

Do not optimize this by adding concurrent catalogue writes. A safe future experiment
would use a small bounded worker pool only for filesystem/stat/metadata-read work,
then feed completed records back to the existing single ordered catalogue/checkpoint
commit path. Such a change needs benchmarks and cancellation/lock/checkpoint tests on
local files, Kodi VFS/SMB, SQLite and shared MariaDB before it can become a default.

## Invariants

- Never mark unseen media missing after an unavailable or partial traversal.
- Keep cleanup separate from scanning.
- Preserve cancellation around slow filesystem and metadata operations.
- Preserve scan-lock refresh and ownership checks, including backend-specific stale-lock recovery.
- Commit checkpoints only after a folder is fully processed.
- Force a fresh traversal when settings change what can be discovered.
- Avoid copying complete remote files when a bounded read is sufficient.
- Keep explicit metadata refresh serial, source-read-only and mutually exclusive with scanner/migration writers.
- Add a real-Kodi or NAS validation note for behaviour that stubs cannot prove.

## EXIF parser resilience (0.8.24)

The Kodi dependency `script.module.exifread` remains the primary EXIF reader. If it
raises while decoding an unrelated text tag, MyPicsDB does not discard every core
field. A bounded fallback reads only the TIFF/EXIF structures already present in
the configured metadata prefix and can recover Camera Make/Model, capture dates,
orientation/dimensions and GPS coordinates. MakerNote, UserComment and arbitrary
free-form EXIF are intentionally excluded from the fallback.

This does **not** automatically rewrite rows that were indexed before 0.8.24. Use
**Metadata diagnostics** on one representative picture first; if Fresh extraction
now finds the expected values, use **Refresh metadata** for that picture or
**Refresh metadata in this folder** for a bounded batch.
