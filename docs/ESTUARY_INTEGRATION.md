# Estuary MyPicsDB 3

`skin.estuary.mypicsdb3` is an independently installed Kodi skin generated from
the official Estuary source for Kodi 21 Omega. It keeps standard Estuary intact
and changes only the Pictures home-screen group.

## Why a separate skin survives updates

Kodi identifies add-ons by ID. Standard Estuary uses:

```text
skin.estuary
```

The MyPicsDB 3 fork uses:

```text
skin.estuary.mypicsdb3
```

The two add-ons therefore have separate installation directories, versions,
settings and update records. Updating Kodi or standard Estuary cannot overwrite
the fork. Updates for the fork are delivered as normal Kodi add-on updates from
the MyPicsDB 3 repository.

A major Kodi release can change the `xbmc.gui` skin API. If the installed fork
is not compatible, Kodi can disable it and return to standard Estuary. Publish a
new fork built from the matching upstream Kodi branch before supporting a new
major Kodi version.

## Current upstream base

The pinned source is defined in `contrib/estuary/upstream.json`:

```text
Kodi tag: 21.3-Omega
Target add-on: skin.estuary.mypicsdb3
Skin version: 21.3.1
```

The build downloads the official Kodi source archive over HTTPS, extracts only
`addons/skin.estuary`, gives the copy a new add-on ID and applies
`contrib/estuary/Home-pictures-group.xml`.

The generated package depends on the current `plugin.image.mypicsdb3` version,
so installing the skin through the repository also installs the picture add-on.

## Home-screen rows

The Pictures group contains:

1. Media sources
2. Recently taken
3. Recently added
4. Random memories
5. Recent albums
6. Random albums
7. On this day

Every MyPicsDB 3 row is guarded by:

```xml
<visible>System.HasAddon(plugin.image.mypicsdb3)</visible>
```

The widget endpoints only query the indexed database. They never trigger a
source scan when the home screen opens.

## Build the skin

Online build using the pinned official archive:

```bash
python3 tools/estuary_skin.py
```

Build all Kodi packages and the repository index:

```bash
python3 tools/build.py
```

Use an already available official Estuary source directory:

```bash
python3 tools/build.py --estuary-source /path/to/skin.estuary
```

The generated skin directory is:

```text
build/skin.estuary.mypicsdb3/
```

The installable package is:

```text
dist/skin.estuary.mypicsdb3-<skin-version>.zip
```

## Updating to a newer Omega Estuary

1. Change `ref`, `archive_url` and `skin_version` in
   `contrib/estuary/upstream.json`.
2. Run `python3 tools/build.py --force-estuary-download`.
3. Confirm that the Pictures group was patched exactly once.
4. Run `python3 -m pytest` and the Kodi add-on checker.
5. Test navigation, playback, PVR, weather and Pictures in a real Kodi
   installation.
6. Publish a new project release.

If upstream changes the structure around groups `4000` or `17000`, the builder
fails instead of silently producing an unpatched skin. Update the replacement
fragment or matcher after reviewing the new upstream `Home.xml`.

## Returning to standard Estuary

Open:

```text
Settings > Interface > Skin > Estuary
```

Standard Estuary remains installed throughout. Removing
`skin.estuary.mypicsdb3` does not remove MyPicsDB 3 or its picture database.
