# Development notes

New to the project? Read [Start here](START_HERE.md),
[Architecture](ARCHITECTURE.md), the [data-flow index](flows/README.md) and
[Local development](LOCAL_DEVELOPMENT.md) before using these specialist notes.

## Design boundaries

- `filesystem.py` isolates Kodi VFS operations.
- `metadata.py` isolates bounded EXIF, XMP and IPTC extraction, including the JPEG marker-header I/O path and XMP GPS/location compatibility; `metadata_mapping.py` owns canonical metadata mapping and reindex fingerprints; `metadata_refresh.py` owns explicit serial re-reads of already indexed still pictures.
- `db/engine.py` handles SQL parameter syntax and connections.
- `db/catalog.py` contains catalogue writes and read models.
- `scanner.py` never runs from a widget route.
- `views.py` is the Kodi-specific browser and action layer.
- `smart_filter_editor.py`, `attention.py` and `metadata_browser.py` must build
  validated Query Model data for result selection; none may introduce raw SQL or
  a second filtering language. Metadata value enumeration belongs to the fixed,
  bounded facet allowlist in `Catalog.query_facet_counts()`.
- Query-result snapshots must be reconstructed from safe route references and
  compiled through the same Query Model boundary. Manual collections store only
  frozen media IDs/order; do not put query JSON or SQL into `collection_items`.
- Media exports must freeze ordered catalogue IDs before copying and use
  `exporter.py` plus the filesystem adapter. Export is destination-side COPY only:
  never move/delete/edit source media, never overwrite destination files, reject
  destinations inside configured picture sources, and never persist VFS
  credentials in manifests or logs.
- `screensaver.py` is a bounded read-only catalogue provider;
  `screensaver.mypicsdb3/default.py` owns Kodi's screensaver window and settings
  actions without creating `Runtime`.
- `tools/estuary_skin.py` creates the separate skin from a pinned official
  Estuary source tree; generated upstream files are not committed.

## Scanner safety

A source is marked missing only after its root was confirmed available and a
complete, non-cancelled traversal finished. Records are soft-marked missing.
Cleanup removes old missing rows after the configured retention period.

The scanner is intentionally serial today. A first scan or metadata reindex can
therefore be slow on very large network libraries, but serial traversal preserves
Kodi VFS behaviour, one ordered database/checkpoint stream and predictable cancellation.
Do not add arbitrary concurrent database writes. A future performance experiment may
use a small bounded worker pool for file stat/metadata reads only, with results committed
serially and benchmarked on local, SMB, SQLite and MariaDB configurations.

Crash recovery must preserve the same ownership boundary. SQLite may recover only
a same-host scan lock whose recorded process id differs from the current Kodi
process and is confirmed absent. MariaDB/MySQL must wait for the shared lock
heartbeat/TTL. Older
`scan_runs` rows may be marked `interrupted` only after the new scanner owns the
global scan lock.

## Schema changes

Database startup is owned by `db/migrations.py`; do not add ad-hoc DDL to
`Catalog.initialize()`. Increment `SCHEMA_VERSION`, update the complete
fresh-database schema, add one deterministic and checksummed migration step,
and test upgrades from every supported schema. Never change a checksum after
release. See `docs/DATABASE_MIGRATIONS.md`. Version 0.2.13 introduced the
migration foundation while retaining schema version 1. Version 0.2.15 raised the
catalogue to schema version 2. Version 0.2.19 raised it to schema version 3
with normalized global-search documents. Later migrations added mixed-media
rows in schema 4 and saved searches in schema 5. See
`docs/DATABASE_MIGRATIONS.md` for the current sequence.

## Building the Estuary skin

The default full build downloads the newest official Kodi archive pinned for
each channel in `contrib/estuary/upstream.json`, extracts only
`addons/skin.estuary`, changes the add-on id to `skin.estuary.mypicsdb3`, adds
the MyPicsDB 3 dependency and patches the Pictures group in `xml/Home.xml`.

```bash
python3 tools/build.py
```

For offline development, point the builder at a local copy of the official
`skin.estuary` directory:

```bash
python3 tools/build.py --channel omega --estuary-source /path/to/xbmc/addons/skin.estuary
```

To test the plug-in, screensaver and repository without downloading Estuary:

```bash
python3 tools/build.py --skip-skin
```

Do not commit `build/`, `.cache/` or generated skin source. The scheduled
updater normally refreshes release pins. For a manual refresh run
`python3 tools/update_estuary_upstreams.py`, review the new `Home.xml`, run the
full test suite and confirm the independent skin versions.

## MariaDB integration test

```bash
docker compose -f dev/docker-compose.yml up -d
export MYPICSDB3_MYSQL_HOST=127.0.0.1
export MYPICSDB3_MYSQL_PORT=3307
export MYPICSDB3_MYSQL_DATABASE=mypicsdb3
export MYPICSDB3_MYSQL_USERNAME=mypicsdb3
export MYPICSDB3_MYSQL_PASSWORD=mypicsdb3
python3 -m pytest tests/test_mysql_integration.py
```

## Release checklist

```bash
python3 tools/set_version.py 0.2.0
# Add --repository-version 0.2.0 only when repository.mypicsdb3 changed.
python3 -m pytest
python3 tools/verify.py
python3 tools/build.py
git add -A
git commit -m "Release MyPicsDB 3 0.2.0"
git push
git tag -a v0.2.0 -m "MyPicsDB 3 0.2.0"
git push origin v0.2.0
```

The GitHub workflows repeat the tests, generate the pinned skin, run Kodi's
add-on checker and publish the packages. Create the release tag only after the
`main` workflows are green.

### Repository manifest check

Kodi supports `minversion` and `maxversion` on repository `<dir>` elements, but
`kodi-addon-checker` 0.0.36 rejects those attributes in its bundled XML schema.
The workflows therefore run Kodi's checker for the picture add-on and generated
skins, while `tools/verify.py` validates the screensaver package plus the
repository add-on, channel ranges and URLs directly.

`kodi-addon-checker` 0.0.36 can also crash if an external Kodi repository
cannot be loaded and its internal `Repository` object is left without an
`addons` attribute. `tools/run_kodi_addon_checker.py` handles only that known
upstream failure by treating the unavailable repository as empty. All local
validation errors and other checker failures still fail the workflow.

### Reverse-geocoding development guardrails (0.8.28)

Keep network geocoding in `geocoding.py` and inject/mock the opener in tests; unit and
release tests must never contact a public geocoder. Public Nominatim use must remain
user-triggered one picture at a time, cached, attributed and switchable by endpoint.
The persistent per-endpoint throttle must keep cache misses below one request per
second; unit tests inject clock/sleep functions rather than waiting in real time. Do
not add a folder/bulk worker or scanner-triggered network hook without selecting a
service designed for that workload. The `location-enrichment` lock must continue to
conflict with scan, migration and metadata-refresh writers. Scanner code may only
reapply already-saved local enrichment and must never call the provider.


### Whole-library metadata refresh guardrails (0.8.29)

- Keep the job serial; do not add worker pools or concurrent SMB metadata reads.
- Iterate existing catalogue IDs in bounded batches; do not preload the whole library.
- Preserve the frozen maximum-ID horizon across resume.
- Advance the local checkpoint only after writes in the completed batch have had folder summaries refreshed.
- Never call an online reverse-geocoding provider from full/folder metadata refresh. Local provider cache reuse is allowed.
- Keep source files read-only and preserve scan-only semantics such as `last_seen_at`.
