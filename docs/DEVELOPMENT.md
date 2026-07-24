# Development notes

## Design boundaries

- `filesystem.py` isolates Kodi VFS operations.
- `metadata.py` isolates EXIF, XMP and IPTC extraction.
- `db/engine.py` handles SQL parameter syntax and connections.
- `db/catalog.py` contains catalogue writes and read models.
- `scanner.py` never runs from a widget route.
- `views.py` is the Kodi-specific browser and action layer.
- `tools/estuary_skin.py` creates the separate skin from a pinned official
  Estuary source tree; generated upstream files are not committed.

## Scanner safety

A source is marked missing only after its root was confirmed available and a
complete, non-cancelled traversal finished. Records are soft-marked missing.
Cleanup removes old missing rows after the configured retention period.

## Schema changes

Database startup is owned by `db/migrations.py`; do not add ad-hoc DDL to
`Catalog.initialize()`. Increment `SCHEMA_VERSION`, update the complete
fresh-database schema, add one deterministic and checksummed migration step,
and test upgrades from every supported schema. Never change a checksum after
release. See `docs/DATABASE_MIGRATIONS.md`. Version 0.2.13 introduced the
migration foundation while retaining schema version 1. Version 0.2.15 raises
the current catalogue to schema version 2.

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

To test only the plug-in and repository without downloading Estuary:

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
skins, while `tools/verify.py` validates the repository add-on, channel ranges
and URLs directly.

`kodi-addon-checker` 0.0.36 can also crash if an external Kodi repository
cannot be loaded and its internal `Repository` object is left without an
`addons` attribute. `tools/run_kodi_addon_checker.py` handles only that known
upstream failure by treating the unavailable repository as empty. All local
validation errors and other checker failures still fail the workflow.
