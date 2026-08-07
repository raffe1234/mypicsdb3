# Architecture

This document describes the current architecture of MyPicsDB 3. It focuses on
component responsibilities, dependency direction and invariants. For a guided
first visit, read [Start here](START_HERE.md). For step-by-step call paths, use
the [data-flow guides](flows/README.md).

## System context

MyPicsDB 3 runs inside Kodi and depends on Kodi for:

- picture-source configuration and VFS access;
- user dialogs, directory listings and notifications;
- media display, playlists and playback state;
- add-on settings and profile storage;
- skin integration and home-screen widgets.

The add-on owns:

- the indexed catalogue and its migrations;
- metadata normalization;
- query validation and SQL generation;
- scan safety, locking, cancellation and checkpoints;
- conversion of catalogue rows to Kodi views;
- the optional Estuary fork build and repository packaging.

## Process model

Kodi starts two independent Python entry points.

### Plug-in process

`addon.py` handles one Kodi request and exits.

```text
addon.py
→ entrypoints.plugin_main()
→ parse request
→ create KodiContext
→ create Runtime
→ initialize catalogue
→ PluginUI.dispatch()
→ finish directory or action
→ process exits
```

A widget request uses the same path as an interactive browser request. Widget
routes are read-only and must never start a filesystem scan.

### Service process

`service.py` starts a long-running loop.

```text
service.py
→ entrypoints.service_main()
→ create KodiContext and abort monitor
→ wait through an abortable Home-state publication grace period
→ publish Estuary Home-window state
→ ServiceLoop.run()
→ initialize catalogue when migrations are available
→ synchronize sources
→ repeat maintenance, scan and slideshow-monitor work
→ stop when Kodi requests abort
```

The service may overlap with short plug-in requests, so the database and scan
locks are part of the architecture rather than incidental implementation
details. During in-place add-on updates, the service also defers its initial
Estuary Home-window property writes for five abortable seconds. This avoids
writing GUI state while Kodi may still be unloading the previous skin or
unregistering the old add-on instance. Plug-in actions continue to publish
settings immediately when required.

## Layer and dependency map

```text
Entry points
  addon.py, service.py
        ↓
Kodi-facing orchestration
  entrypoints.py, views.py, service_loop.py, kodi.py
        ↓
Application and domain logic
  scanner.py, search.py, query_model.py, saved_searches.py,
  static_collections.py, slideshow.py, preferences.py, home_layout_editor.py
        ↓
Infrastructure adapters
  filesystem.py, metadata.py, db/engine.py, db/catalog.py,
  db/migrations.py, db/schema.py
```

Some modules necessarily cross these labels, but new code should preserve the
main direction. Domain and database logic should not reach directly into Kodi
UI modules merely to display a notification or read a setting.

## Runtime assembly

`Runtime` is intentionally small. It creates:

1. a `KodiContext`, unless one was injected;
2. a `DatabaseEngine` from the current settings;
3. a `Catalog` using that engine and the active rating policy;
4. the current schema through `Catalog.initialize()` and the migration runner;
5. a `KodiFilesystem` with a local temporary directory.

`PluginUI` receives the assembled runtime. Tests can inject fakes or construct
lower layers directly rather than starting Kodi.

The service builds equivalent parts itself because it must refresh settings and
retry database initialization while another process owns the migration lock.

## Main component responsibilities

### `kodi.py`: Kodi adapter and shared state

`KodiContext` centralizes access to add-on settings, localization,
notifications, JSON-RPC, source discovery, scan status, home-widget invalidation
and playback state. This prevents the rest of the project from scattering Kodi
API calls through otherwise testable logic.

### `views.py`: request and UI orchestration

`PluginUI` maps routes to catalogue reads or actions, creates Kodi `ListItem`
objects, applies pagination and view modes, and starts scans or slideshows. It
is deliberately Kodi-specific. Business rules that can be expressed without
Kodi should be moved into a smaller module rather than added indefinitely to
`views.py`.

### `db/engine.py`: backend abstraction

`DatabaseEngine` owns SQLite and MySQL/MariaDB connection details, placeholder
syntax, transactions and low-level execution. Higher layers should not branch
on the backend when the engine can hide the difference.

### `db/catalog.py`: catalogue API

`Catalog` is the main read/write interface for sources, folders, media,
searches, manual collections, collection music-playlist mappings, locks and scan
runs. It returns dictionaries or
domain objects that
higher layers convert to Kodi UI items. Query methods enforce rating policy and
use backend-neutral engine operations.

### `db/migrations.py` and `db/schema.py`: schema lifecycle

The complete current schema is defined for a fresh database. Existing databases
advance through deterministic migration steps with recorded checksums. SQLite
migrations use a verified backup. Migration ownership is protected by a lock so
that plug-in and service startup cannot modify the schema concurrently.

### `scanner.py`: safe incremental indexing

`Scanner` coordinates source traversal, exclusions, metadata extraction,
unchanged-file detection, catalogue writes, missing-row marking, scan locks and
checkpoints. It accepts callbacks for cancellation, progress and start state.
The filesystem is wrapped in `CancellationAwareFilesystem` so cancellation and
lock refresh checks also occur around slow I/O.

### `filesystem.py`: local and Kodi VFS adapters

The abstract `Filesystem` operations are small: existence, listing, stat,
binary reads and temporary materialization. `KodiFilesystem` supports Kodi VFS
and network URIs; `LocalFilesystem` is useful in tests and tools.

### `metadata.py`: bounded metadata extraction

Metadata extraction normalizes EXIF, embedded XMP and optional IPTC information
into `MetadataResult`. It works through the filesystem interface and respects
configured read limits. Video rows use lightweight filename and modification
information rather than a separate video scraper.

### `query_model.py`: validated query boundary

The Query Model defines supported fields, operators, sort choices and validation
limits. It is the only supported path from a user-created or stored query to a
catalogue query. Raw SQL is not accepted from Kodi routes or saved records.

### `static_collections.py`: manual-collection boundary

Manual collections are intentionally separate from saved smart searches. This
module validates names and stored collection metadata. `Catalog` owns ordered
media references and backend-neutral persistence; `views.py` owns Kodi dialogs,
context actions, explicit order changes, collection browsing and Home providers.
A collection never contains query JSON or source-file copies. Dynamic Home rows
store only validated saved-search or manual-collection IDs.

### `music_playlists.py` and `music_slideshow.py`: collection-music boundary

A saved smart or manual collection may reference one Kodi-readable music
playlist file. `music_playlists.py` validates target types and bounded URIs;
`Catalog` persists only the mapping. `music_slideshow.py` loads and starts Kodi
music playlist 0 and stops only an active audio player. `views.py` keeps the
feature explicit and picture-only. `kodi.py` and `service_loop.py` own the
session token, queue fingerprint and cleanup after the native picture slideshow
ends. Playlist files and music are never imported or modified.

### `service_loop.py`: long-running maintenance

The service synchronizes sources, schedules automatic scans, reacts to local
date changes, notices home-widget limit changes, advances the separate random
home-row generation on its configured hourly interval advances compatible mixed slideshows after video playback, and cleans up only
the recognized music queue belonging to a finished collection picture
slideshow. It must remain responsive to Kodi abort
requests and defer disruptive work while playback is active when configured.

### Estuary and build tools

`contrib/estuary/upstream.json` pins official Estuary sources per Kodi channel.
Maintained patches are applied by `tools/estuary_skin.py`; generated source is
not committed. `tools/build.py` creates plug-in, repository, skin and source
archives plus the published Kodi repository tree.

## Catalogue data model

At a high level the catalogue stores:

```text
sources
  └── folders
       └── pictures/media
            ├── tags/keywords
            └── normalized search document

scan runs and named locks
saved searches containing validated Query Model JSON
manual collections containing ordered references to pictures/media
optional smart/manual collection music-playlist mappings
schema and migration history
```

The historical table name `pictures` also stores optional video rows, identified
by `media_type`. Avoid assuming that every row can be opened as a still image.

## Database lifecycle

```text
DatabaseEngine.connect()
→ MigrationRunner.inspect()
→ reject unsupported newer schema
→ acquire migration ownership
→ create fresh schema OR validate migration path
→ back up SQLite when required
→ apply deterministic migrations
→ validate recorded checksums
→ release migration ownership
→ Catalog becomes available
```

Never change a released migration checksum. A corrected migration requires a
new schema step, not silent rewriting of history.

## Concurrency and locks

Two named concerns are especially important:

- **Migration ownership** prevents concurrent schema initialization by the
  service and a plug-in request.
- **Scan ownership** prevents two devices or processes from scanning the same
  catalogue simultaneously. The scanner refreshes the lock during long work
  and stops if ownership is lost.

A lock timeout is not permission to continue blindly. The code must prove that
it still owns the operation before committing destructive or state-changing
work.

## Safety invariants

### Missing-source safety

A failed root check or partial directory traversal must not mark unseen rows as
missing. Missing marking is allowed only after the root was available and a
complete, non-cancelled traversal finished.

### Soft deletion

Unseen media is first marked missing. Cleanup is a separate operation governed
by retention settings. This protects users from temporary SMB/NFS outages and
misconfigured source paths.

### Checkpoint compatibility

A scan checkpoint is reused only when the selected sources, database identity,
extensions, exclusions and metadata settings are compatible. A setting change
that could alter discovered media must force a fresh traversal.

### Query safety

The Query Model has a version and allowlists supported fields/operators. Stored
JSON is revalidated every time it is opened. SQL fragments are generated only
from validated structures.

### Kodi UI safety

Background or widget calls must not perform blocking scans or unexpectedly
change the active window. View-mode changes are guarded so they apply only to a
stable, relevant Pictures container.

### Slideshow safety

Kodi builds differ in how picture playlist 2 is handled. MyPicsDB 3 probes the
player and prefers conservative fallbacks rather than starting an invalid mixed
playlist or interfering with unrelated playback. Manual-collection stills avoid
that JSON-RPC playlist entirely: a hidden ordered plug-in directory is consumed
by Kodi's native ``SlideShow`` built-in.

## Testing architecture

The `tests/` suite installs Kodi module stubs in `tests/conftest.py`. Tests can
therefore exercise route, adapter and service behaviour without a Kodi process.
The suite includes:

- catalogue and migration tests;
- scanner, checkpoint and partial-source tests;
- query, search, saved-search and manual-collection tests;
- UI and Kodi-state tests;
- slideshow and service-loop tests;
- Estuary patch and package-asset tests;
- optional MariaDB integration tests.

Use the smallest relevant test during development, but run the complete suite
and `tools/verify.py` before pushing.

## Documentation ownership

Use the document type that matches the change:

- update `START_HERE.md` when the newcomer path changes;
- update this file when component responsibilities or invariants change;
- update a file under `docs/flows/` when a call path changes;
- update specialist documents for database, Query Model, search or skin
  contracts;
- add an ADR for a long-lived architectural choice with meaningful trade-offs;
- add or update a patch report for release-specific history;
- update README for user-visible behaviour, installation or public status.

## Change-impact checklist

Before opening a pull request, ask:

1. Which process runs this code: one-shot plug-in, long-running service, build
   tool, or more than one?
2. Does the change touch Kodi UI, filesystem I/O, metadata, database state or
   generated packages?
3. Can a network source be unavailable or a Kodi process stop midway?
4. Does a concurrent service or another device share the catalogue?
5. Does the change need a schema migration, Query Model version bump, setting
   migration or release-note update?
6. Which regression test proves the intended behaviour?
7. Which real-Kodi checks remain after automated tests pass?

## Screensaver boundary

`screensaver.mypicsdb3` is packaged as a separate Kodi screensaver add-on but
imports the installed MyPicsDB 3 core library. It may read the configured
SQLite/MySQL catalogue and compile stored Query Models, but it must not create a
`Runtime`, run migrations, start scans, publish Home state or modify original
media. Screensaver database access is bounded and read-only by design.
