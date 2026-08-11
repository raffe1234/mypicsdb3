# Safe media export

Version 0.8.17 adds explicit COPY-only export for query-backed result pages and
manual collections. Export is deliberately a separate destination-side workflow:
it does not change collection membership, scanning state, source rows or source
media.

## Data flow

```text
global search / saved smart collection / Browse metadata / Needs attention
→ action/export-results with safe route reference
→ reconstruct + validate PictureQuery
→ Catalog.ordered_query_picture_ids()
→ freeze complete deterministic media-ID order

manual collection
→ Export collection
→ Catalog.ordered_collection_picture_ids()
→ freeze currently visible stored order

frozen IDs
→ ask for portable export-folder name
→ Kodi writable-destination picker
→ explicit item-count confirmation
→ SafeExporter
   → enumerate configured picture-source roots
   → allocate a unique dedicated folder outside every source tree
   → write preflight status=running manifest
   → fetch Catalog.media_for_export() in batches of at most 500 IDs
   → source exists? → choose non-overwriting portable destination name
   → Filesystem.copy() through Kodi VFS
   → progress / cancellation between files
   → finalize status=completed or cancelled manifest
```

## Files and responsibilities

| File | Responsibility |
| --- | --- |
| `views.py` | Safe result-reference reconstruction, destination/name dialogs, confirmation, progress and cancellation |
| `db/catalog.py` | Freeze ordered query/collection IDs and return bounded export metadata batches |
| `exporter.py` | Destination directory, collision policy, copy loop, credential-sanitized manifest and summary |
| `filesystem.py` | Backend-neutral `makedirs`, `copy` and `write_text`; Kodi implementation uses VFS |
| `tests/test_exporter.py` | Source safety, collisions, cancellation, manifest and credential-redaction tests |
| `tests/test_mysql_integration.py` | Opt-in MariaDB parity for ordered export selection/read helpers |

## Selection and database behaviour

The full selection is frozen before the destination copy starts. Query-backed
results compile through Query Model v1 and use its deterministic sort with an ID
tie-breaker. Manual collections use their stored `collection_items.position`
order while still applying the current visibility/rating policy. No raw SQL or
raw Query Model JSON is accepted by the export route.

After the ID list has been frozen, `media_for_export()` fetches only small
provenance/copy rows in batches of at most 500. This avoids holding full media
metadata for a very large export. Export performs no catalogue writes and needs
no schema migration; SQLite and MariaDB use the same catalogue boundary.

## Destination safety and collisions

The user chooses a writable parent location, but MyPicsDB 3 always creates its
own new subfolder. If that folder name already exists, a numbered folder is
allocated. A destination that would be inside any configured picture source is
rejected so exported copies cannot silently become new catalogue source media on
the next scan.

Existing destination files are never overwritten. Basenames are made portable
and collisions become `name (2).ext`, `name (3).ext`, and so on. No move,
rename-in-place, delete or source-side write operation exists in the export API.

## Manifest version 1

Every export directory contains `mypicsdb3-export-manifest.json`. A preflight
manifest is written before the first media copy. A normal finish rewrites it as
`completed`; user cancellation rewrites it as `cancelled`. A hard Kodi/process
crash may leave the preflight `running` manifest and already copied files, which
makes the partial export visible rather than pretending it was complete.

Representative structure:

```json
{
  "format": "mypicsdb3-export-manifest",
  "manifest_version": 1,
  "mypicsdb3_version": "0.8.17",
  "status": "completed",
  "selection": {"label": "Spain", "selected": 2},
  "summary": {
    "processed": 2,
    "copied": 1,
    "missing": 1,
    "failed": 0,
    "renamed_for_collision": 0
  },
  "destination": "smb://nas/exports/Spain/",
  "items": [
    {
      "id": 42,
      "status": "copied",
      "source_uri": "smb://nas/photos/a.jpg",
      "exported_file": "a.jpg",
      "media_type": "picture"
    }
  ]
}
```

Kodi VFS URIs can contain network credentials. The actual URI is used only for
the VFS operation; user/password information is stripped before source or
destination URI provenance is written into the manifest. VFS exception text is
not persisted or logged because it may echo a credential-bearing URI.

## Missing, failed and cancelled items

A catalogue ID that disappears before its batch is read is recorded as
`missing`. A source path that no longer exists is also `missing`. A copy failure
is recorded as `failed`, and later items continue. Cancellation is checked
between files and batches; already copied files are deliberately retained and
included in the final partial manifest. Version 0.8.17 has no resume operation.

## Invariants

- Source media are read-only: never move, rename, edit or delete them.
- Export always creates a new dedicated destination directory.
- Never export into a configured picture-source tree.
- Never overwrite an existing destination file.
- Never route user strings into SQL identifiers or SQL fragments.
- Never persist embedded VFS credentials in the manifest or log them from copy exceptions.
- Query/collection order is frozen before copying starts.
- Cancellation leaves an honest partial result and manifest rather than deleting successful copies.
- Archive/ZIP support, if ever added, must reuse these safety boundaries rather than bypass them.
