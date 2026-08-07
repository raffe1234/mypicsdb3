# Estuary MyPicsDB 3

`skin.estuary.mypicsdb3` is an independently installed Kodi skin generated from
official Estuary release sources. Standard Estuary remains installed and is
never modified.

## Kodi channels

The repository currently defines two channels in
`contrib/estuary/upstream.json`:

| Channel | Kodi | Current source | Repository path |
| --- | --- | --- | --- |
| `omega` | Kodi 21 Omega | `21.3-Omega` | `repository/omega/` |
| `piers` | Kodi 22 Piers | `22.0b1-Piers` | `repository/piers/` |

`repository.mypicsdb3/addon.xml` declares a separate `<dir>` with
`minversion` and `maxversion` for each channel. Kodi therefore reads only the
repository index intended for its own major version.

The Piers lower boundary is `21.90.0`, matching the `xbmc.addon` API range
used by Kodi 22 preview builds. Omega ends at `21.89.999`, so only one channel
matches at a time.


## MyPicsDB 3 home-row contract

The generated skin patches the Pictures home group with up to nine materialized
rows. Built-in rows plus saved smart and manual collections use the standard
MyPicsDB poster include. Dynamic rows obtain their heading and database ID from
matching materialized slot settings; interactive browsing still uses Default
album view inside the plug-in.

Every MyPicsDB 3 provider path includes `MyPicsDB3.HomeWidgetGeneration`. This
fixes stale rows after changing the configured 4–40 item limit and lets scans
invalidate only MyPicsDB 3 providers. Random memories, Random albums and On this
day - random additionally include `MyPicsDB3.RandomWidgetGeneration`, allowing
the service to refresh only those rows on the configured hourly schedule. The
plug-in hashes both generation values into a stable database pivot, so Estuary
can re-query an unchanged provider without changing its visible selection. The
combined editor remains in the picture add-on; the skin only consumes the nine
slots.

The 0.4.4 patch uses Omega patch revision 12 and Piers patch revision 10.
The plugin-only 0.4.5 stability follow-up keeps those skin revisions unchanged.
Version 0.4.11 advances Omega to revision 15 and Piers to revision 13 because
the generated Home fragment removes the legacy square/wide smart-row branches.
Version 0.5.1 advances Omega to revision 16 and Piers to revision 14 for fixed
manual-collection Home providers.
Version 0.8.4 advances Omega to revision 17 and Piers to revision 15 for the
Picture Info collection action. Version 0.8.5 advances them again to revisions
18/16 to make that action reachable with keyboard and remote focus navigation.

## Picture Info collection action

The generated Estuary fork also patches `DialogPictureInfo.xml`. While Kodi's
native slideshow is showing a still picture, Picture Info displays **Add current
picture to collection** as control `9200`. The button closes Picture Info and
runs:

```text
plugin://plugin.image.mypicsdb3/action/add-current-picture-to-collection
```

The user flow is **I / Info** -> move **Down** past the last metadata row ->
**OK / Enter**. The `C` context-menu key and Kodi keymaps are not changed.

Focus navigation is deliberately fail-safe. At the bottom of Estuary's metadata
list, Down targets control `9200` only when `Control.IsVisible(9200)` is true.
The fallback back to list control `5` has the inverse condition, so the two
navigation actions cannot both fire for one key press. When the MyPicsDB action
is hidden, native Estuary behaviour is preserved.

The plug-in then resolves Kodi's current slideshow path and filename to one
exact, non-missing catalogue URI and requires `media_type=picture` before it
opens the existing collection picker. An unindexed, missing, ambiguous or video
item causes no collection write.

## Automatic upstream refresh

`.github/workflows/estuary-upstream.yml` runs once per day and can also be
started manually. It:

1. reads official Kodi releases through the GitHub Releases API;
2. updates the pinned release lists for Omega and Piers;
3. patches the newest Estuary source in each changed channel;
4. runs source verification, unit tests, the package build and Kodi's add-on
   checker;
5. commits `contrib/estuary/upstream.json` only when all checks pass;
6. starts the Pages deployment.

The workflow is fail-closed. If the Pictures group can no longer be found
exactly between Estuary control groups `4000` and `17000`, or the expected
Picture Info metadata-list navigation cannot be patched exactly once, no new pin
is committed and the previously published skin remains available. A GitHub issue
named **Automatic Estuary patch failed** is created or updated.

Only official release tags are followed. Development commits between Kodi
alpha, beta, release-candidate and final releases are not published
unattended.

## Retained patched versions

The Pages workflow stores the generated site in the `repo-data` branch. Before
each deployment it gives the previous `repository/` tree to `tools/build.py`.
The builder then:

- places the newest patched skin first;
- copies older archives and SHA-256 files from the previous deployment;
- retains at most `retain_versions` archives, currently five, per channel;
- writes `history.json` beside the skin archives;
- includes only the newest skin in `addons.xml`.

Omitting old versions from `addons.xml` prevents Kodi from choosing an obsolete
package automatically. The old zip files remain available for manual rollback
or diagnostics.

The root `repository/addons.xml` remains an Omega-compatible legacy index. It
lets an installed repository add-on from version 0.2.6 discover version 0.2.7.
After that update Kodi uses the versioned channel paths.

## Version scheme

Stable skin packages use the Kodi release plus an independent patch revision:

```text
21.3-Omega -> 21.3.5
```

Preview packages use Kodi's supported pre-release ordering:

```text
22.0a3-Piers -> 22.0.0~alpha3.1
22.0b1-Piers -> 22.0.0~beta1.1
22.0rc1-Piers -> 22.0.0~rc1.1
22.0-Piers   -> 22.0.1
```

Increase `patch_revision` in a channel when the MyPicsDB 3 patch itself changes
without a new Kodi release. Versions 0.4.9 and 0.4.10 use Omega revision 14 and
Piers revision 12. Version 0.4.11 uses revisions 15/13, version 0.8.4 uses
17/15 for Picture Info, and version 0.8.5 uses 18/16 for the corrected focus
navigation. Then run the updater
so all generated versions are recalculated.

## Build commands

Build the newest pinned skin for every channel:

```bash
python3 tools/build.py
```

Build one channel from a local matching Estuary source:

```bash
python3 tools/build.py \
  --channel omega \
  --estuary-source /path/to/xbmc/addons/skin.estuary
```

Build several pinned historical releases from source, mainly for an initial
archive or testing:

```bash
python3 tools/build.py --history-limit 5
```

Merge a previous published repository tree:

```bash
python3 tools/build.py \
  --previous-repository /path/to/old/dist/repository
```

Refresh the pins manually:

```bash
python3 tools/update_estuary_upstreams.py
```

The generated skin directories are placed under:

```text
build/estuary/<channel>/<skin-version>/skin.estuary.mypicsdb3/
```

The release assets contain the newest skin from each channel. GitHub Pages also
contains the retained history under the corresponding channel directory.

## Why the separate skin survives updates

Standard Estuary uses the add-on ID `skin.estuary`. The fork uses
`skin.estuary.mypicsdb3`. Kodi therefore gives them separate directories,
versions, settings and update records. Updating Kodi or standard Estuary cannot
overwrite the fork.

The generated skin pins `xbmc.gui` to the compatibility version configured
for its Kodi channel and adds a dependency on the current
`plugin.image.mypicsdb3` version. The explicit pin prevents a changing upstream
Estuary declaration from producing checker warnings or silently changing the
compatibility contract of an already configured channel.

## Returning to standard Estuary

Open:

```text
Settings > Interface > Skin > Estuary
```

Removing `skin.estuary.mypicsdb3` does not remove MyPicsDB 3 or its picture
database.

## Repository assets

The repository build copies generated skin assets using their exact
`addon.xml` paths. Do not flatten `resources/icon.png`,
`resources/fanart.jpg` or `resources/screenshots/*` into the add-on root.
