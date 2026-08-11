# Data-flow guide

This is the first page for understanding how the main parts of MyPicsDB 3 fit
together. Each linked guide follows one complete family of requests and lists
the production files, tests and invariants that matter for that family.

Read [Start here](../START_HERE.md) first when this is your first visit to the
repository.

## Overview

```text
                              ┌──────────────────────┐
                              │        Kodi          │
                              └──────────┬───────────┘
                                         │
             ┌───────────────────────────┼──────────────────────────┐
             │                           │                          │
    one-shot plug-in calls        background service          screensaver
             │                           │                          │
      addon.py / views.py        service.py / service_loop.py   default.py
             │                           │                          │
  ┌──────────┼───────────┐      ┌────────┼──────────┐       read-only provider
  │          │           │      │        │          │              │
browse     search    slideshow  scan  refresh    monitor    bounded picture query
  │          │           │      │                                │
  └──────────┴─────┬─────┴──────┘                                │
                   │                                              │
              Catalog API                                 SQLite/MySQL SELECT
                   │
       ┌───────────┼──────────────┐
       │           │              │
   SQLite/MySQL Scanner writes saved queries/collections
                   │
            filesystem + metadata
```

## Choose a guide

### [Plug-in requests, browsing and widgets](PLUGIN_BROWSING.md)

Read this for routes, menus, pagination, list items, rating display policy,
folders, pictures and home-screen widget providers.

Main files: `addon.py`, `entrypoints.py`, `router.py`, `runtime.py`, `views.py`,
`db/catalog.py`, `kodi.py`.

### [Scanning, filesystems, metadata and catalogue writes](SCANNING_METADATA.md)

Read this for manual or scheduled scans, source safety, scan locks, cancellation,
folder checkpoints, EXIF/XMP/IPTC extraction and missing-record handling.

Main files: `scanner.py`, `filesystem.py`, `metadata.py`, `metadata_mapping.py`, `scan_checkpoint.py`,
`db/catalog.py`, `db/locks.py`, `service_loop.py`.

### [Search, Query Model and saved smart collections](SEARCH_COLLECTIONS.md)

Read this for global text search, normalized search documents, validated query
JSON, saved searches, smart-filter editing and smart home rows.

Main files: `search.py`, `search_index.py`, `query_model.py`,
`saved_searches.py`, `smart_filter_editor.py`, `attention.py`, `db/catalog.py`,
`views.py`.

### [Manual collections](STATIC_COLLECTIONS.md)

Read this for named user-selected collections, ordered media references,
collection context actions, default album view and collection slideshows.

Main files: `static_collections.py`, `db/catalog.py`, `db/schema.py`,
`db/migration_steps/v0006_static_collections.py`, `views.py`.

### [Slideshows and the background service](SLIDESHOW_SERVICE.md)

Read this for native picture slideshows, video playlists, mixed database
playlists, player compatibility probes, service monitoring and Kodi shared
state.

Main files: `views.py`, `slideshow.py`, `service_loop.py`, `kodi.py`,
`db/catalog.py`.

### [Collection music playlists](COLLECTION_MUSIC.md)

Read this for smart/manual collection playlist assignments, Kodi music-source
picking, picture-only music slideshows, queue fingerprints and ownership-safe
service cleanup.

Main files: `music_playlists.py`, `music_slideshow.py`, `views.py`, `kodi.py`,
`service_loop.py`, `db/catalog.py`.

### [MyPicsDB 3 screensaver](SCREENSAVER.md)

Read this for manual/smart collection source selection, bounded read-only
catalogue queries, full-screen picture layout and Kodi screensaver lifecycle.

Main files: `screensaver.mypicsdb3/default.py`, `screensaver.py`, `query_model.py`,
`db/engine.py`, `tests/test_screensaver.py`.

### [Estuary integration, builds, GitHub Actions and releases](SKIN_BUILD_RELEASE.md)

Read this for the maintained Estuary fork, widget contracts, upstream pins,
package building, CI, Pages deployment and release tags.

Main files: `contrib/estuary/`, `tools/estuary_skin.py`, `tools/build.py`,
`repository.mypicsdb3/`, `.github/workflows/`.

## Cross-cutting references

Some changes need more than one flow guide:

- database schema work: [Database migrations](../DATABASE_MIGRATIONS.md);
- dynamic query work: [Query Model](../QUERY_MODEL.md);
- text search internals: [Global search](../GLOBAL_SEARCH.md);
- MySQL deployment: [MySQL and MariaDB](../MYSQL_MARIADB.md);
- third-party skins: [Skin integration](../SKIN_INTEGRATION.md);
- stable provider URLs: [Widget URL reference](../WIDGET_URLS.md);
- long-lived decisions: [`docs/adr/`](../adr/).

## How to use a flow guide

1. Read the diagram and file table.
2. Follow the named methods in the editor.
3. Open the listed tests and run one focused file.
4. Note the invariants before editing.
5. Update the guide when your change alters the described path.
