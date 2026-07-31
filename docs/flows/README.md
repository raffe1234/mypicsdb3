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
                   ┌────────────────┴────────────────┐
                   │                                 │
          one-shot plug-in calls             background service
                   │                                 │
            addon.py / views.py              service.py / service_loop.py
                   │                                 │
        ┌──────────┼───────────┐          ┌──────────┼───────────┐
        │          │           │          │          │           │
     browse      search    slideshow   auto scan  date refresh  monitor
        │          │           │          │
        └──────────┴─────┬─────┴──────────┘
                         │
                    Catalog API
                         │
        ┌────────────────┼─────────────────┐
        │                │                 │
    SQLite/MySQL     Scanner writes    saved queries
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

Main files: `scanner.py`, `filesystem.py`, `metadata.py`, `scan_checkpoint.py`,
`db/catalog.py`, `db/locks.py`, `service_loop.py`.

### [Search, Query Model and saved smart collections](SEARCH_COLLECTIONS.md)

Read this for global text search, normalized search documents, validated query
JSON, saved searches, smart-filter editing and smart home rows.

Main files: `search.py`, `search_index.py`, `query_model.py`,
`saved_searches.py`, `smart_filter_editor.py`, `db/catalog.py`, `views.py`.

### [Slideshows and the background service](SLIDESHOW_SERVICE.md)

Read this for native picture slideshows, video playlists, mixed database
playlists, player compatibility probes, service monitoring and Kodi shared
state.

Main files: `views.py`, `slideshow.py`, `service_loop.py`, `kodi.py`,
`db/catalog.py`.

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
