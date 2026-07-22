# MyPicsDB 3

MyPicsDB 3 is an independent, community-maintained successor inspired by
MyPicsDB and MyPicsDB2. It provides a searchable picture catalogue, background
indexing and fast home-screen widgets for Kodi 21 Omega and Kodi 22 Piers.

> Status: 0.2.12 release candidate. The catalogue, SQLite backend, scanner,
> browser routes, Estuary fork builder and package builder are covered by
> automated tests. Real Kodi installations are still required for platform and
> large-library testing before calling the project production-stable.

## Features

- Select one or more existing Kodi picture sources.
- Incremental foreground, selected-source background and scheduled scanning.
- SQLite by default, using WAL mode and a local add-on profile database.
- Optional shared MySQL/MariaDB catalogue through PyMySQL.
- EXIF capture date, camera, orientation, dimensions, rating and optional GPS.
- Basic embedded XMP keywords, rating, location and capture date.
- IPTC keywords, caption and location through IPTCInfo3 when available.
- Missing-source safety: an unavailable SMB/NFS source is never interpreted as
  deletion of every picture.
- Lazy Kodi thumbnail caching; no duplicate thumbnail tree is generated.
- Favorites, ratings, keywords, cameras, years and geotagged views.
- Stable widget endpoints for configurable skins.
- Optional **Estuary MyPicsDB 3** skin with picture rows on the home screen.
- GitHub Actions, Kodi repository generation and GitHub Pages deployment.

## Widget endpoints

```text
plugin://plugin.image.mypicsdb3/recent-taken?limit=15
plugin://plugin.image.mypicsdb3/recent-added?limit=15
plugin://plugin.image.mypicsdb3/random?limit=15
plugin://plugin.image.mypicsdb3/recent-folders?limit=15
plugin://plugin.image.mypicsdb3/random-folders?limit=15
plugin://plugin.image.mypicsdb3/on-this-day?limit=15
plugin://plugin.image.mypicsdb3/years
plugin://plugin.image.mypicsdb3/cameras
plugin://plugin.image.mypicsdb3/keywords
plugin://plugin.image.mypicsdb3/favorites?limit=15
plugin://plugin.image.mypicsdb3/rated?limit=15
plugin://plugin.image.mypicsdb3/geotagged?limit=15
```

Widget calls only read indexed database rows. They never scan picture sources.

## Quick install and setup

The steps below are enough to get started. See [Installing MyPicsDB 3](#installing-mypicsdb-3)
and [Using MyPicsDB 3 in Kodi](#using-mypicsdb-3-in-kodi) for explanations,
alternatives and troubleshooting.

### Quick install with the MyPicsDB 3 Repository

Use this method if you want Kodi to discover future MyPicsDB 3 and Estuary
MyPicsDB 3 updates.

1. Download `repository.mypicsdb3-<version>.zip` from the
   [latest release](https://github.com/raffe1234/mypicsdb3/releases/latest).
   In Kodi, enable **Unknown sources**, open **Add-ons > Install from zip file**
   and select the downloaded repository zip.
2. Open **Add-ons > Install from repository > MyPicsDB 3 Repository > Picture
   add-ons > MyPicsDB 3** and select **Install**.
3. Optional: to show MyPicsDB 3 rows directly on the Pictures home screen, open
   **MyPicsDB 3 Repository > Look and feel > Skin > Estuary MyPicsDB 3** and
   select **Install**.

### Quick install without the MyPicsDB 3 Repository

Kodi cannot discover MyPicsDB 3 updates through this method. Check the GitHub
releases yourself and install newer packages manually.

1. Download `plugin.image.mypicsdb3-<version>.zip` from the
   [latest release](https://github.com/raffe1234/mypicsdb3/releases/latest).
   In Kodi, enable **Unknown sources**, open **Add-ons > Install from zip file**
   and select the downloaded add-on zip.
2. Optional: if you use Estuary and want MyPicsDB 3 rows on the Pictures home
   screen, download and install `skin.estuary.mypicsdb3-<version>.zip` in the
   same way, after installing MyPicsDB 3.

### Quick setup

1. Add each photo location under **Pictures > Add pictures...** and verify that
   Kodi can open it.
2. Open **Pictures > Picture add-ons > MyPicsDB 3 > Picture sources**. Select
   **Refresh Kodi sources**, then enable the sources that MyPicsDB 3 should
   index.
3. Return to the MyPicsDB 3 main menu and select **Scan now**.
4. Open **Pictures > Picture add-ons > MyPicsDB 3 > Settings** to adjust:
   - **General** — widget size, browser page size, the default album view and
     notifications;
   - **Home screen** — Media sources and the content and order of the Estuary
     MyPicsDB 3 rows;
   - **Scanning** — automatic scans, scan timing, playback pauses, file types,
     exclusions and batch size;
   - **Metadata** — XMP, IPTC, GPS storage and metadata read limits;
   - **Database** — local SQLite or a shared MySQL/MariaDB catalogue;
   - **Maintenance** — missing-record retention and debug logging.

## Installing MyPicsDB 3

### Recommended: install through the MyPicsDB 3 repository

Installing the repository is recommended because Kodi can then discover future
updates for the picture add-on and the optional Estuary fork.

1. Open the [latest MyPicsDB 3 release](https://github.com/raffe1234/mypicsdb3/releases/latest).
2. Under **Assets**, download `repository.mypicsdb3-<version>.zip` and copy it
   to a location that the Kodi device can access.
3. In Kodi, open **Settings > System > Add-ons** and enable **Unknown sources**.
4. Open **Add-ons > Install from zip file** and select the repository zip.
5. Wait for the **MyPicsDB 3 Repository Add-on installed** notification.
6. Open **Add-ons > Install from repository > MyPicsDB 3 Repository > Picture
   add-ons > MyPicsDB 3**.
7. Select **Install** and allow Kodi to install the required dependencies.
8. Open **Pictures > Picture add-ons > MyPicsDB 3**.

Kodi checks the installed repository for later releases according to the update
policy under **Settings > System > Add-ons > Updates**. To force an immediate
check, open the Add-on browser's left-side menu and select **Check for updates**.

### Optional: install Estuary MyPicsDB 3

After MyPicsDB 3 is installed:

1. Open **Add-ons > Install from repository > MyPicsDB 3 Repository**.
2. Open **Look and feel > Skin**.
3. Select **Estuary MyPicsDB 3** and choose **Install**.
4. Accept Kodi's prompt to switch to the new skin, or select it later under
   **Settings > Interface > Skin**.
5. Keep the skin when Kodi displays its confirmation dialog.

The skin can show **Media sources** plus nine configurable MyPicsDB 3 rows:

- Recently taken
- Recently added
- Random memories
- Recent albums
- Random albums
- On this day
- Favorites
- Rated pictures
- Geotagged pictures

Open **Pictures > Picture add-ons > MyPicsDB 3 > Settings > Home screen** to:

- show or hide Media sources;
- open **Configure home-screen rows**;
- enable or disable each available view;
- move a view up or down to change the order.

The visual editor lists every view once in the same order used on the Pictures
home screen. Every row has its own **On/Off**, **Move up** and **Move down**
controls. The first six views are enabled by default through **On this day**.
Favorites, Rated pictures and Geotagged pictures are disabled by default, so the
initial home screen stays compact. Existing Row 1 through Row 9 choices are
migrated automatically the first time the editor is opened.

Rows with no indexed results disappear until matching pictures have been
indexed.

### Default album view

Choose the view used when an album opens under **Settings > General > Default
album view**. The default remains **Wide list**. You can also open an album,
switch to another view and use **Save current view as album default** from the
left-side **View options** menu in Estuary MyPicsDB 3. The same action is also
available from the context menu of each picture or subalbum.

### Alternative: install a package directly

A direct installation is useful for testing a particular release, but it does
not install the update repository.

1. Open the [latest MyPicsDB 3 release](https://github.com/raffe1234/mypicsdb3/releases/latest).
2. Under **Assets**, download either:
   - `plugin.image.mypicsdb3-<version>.zip`; or
   - `skin.estuary.mypicsdb3-<version>.zip`.
3. Enable **Unknown sources** under **Settings > System > Add-ons**.
4. Open **Add-ons > Install from zip file** and select the downloaded package.

Installing the skin package directly also installs or updates its required
MyPicsDB 3 dependency when Kodi can resolve that dependency from an enabled
repository.

Kodi resolves ExifRead and PyMySQL from its add-on repositories. IPTCInfo3 is an
optional dependency; EXIF and XMP indexing continue if it is unavailable.

## Using MyPicsDB 3 in Kodi

### 1. Add picture sources to Kodi

MyPicsDB 3 reads picture sources that already exist in Kodi. If a source is not
visible in Kodi yet, add it from **Pictures > Add pictures...**. Local folders,
SMB shares, NFS shares and other locations supported by Kodi can be used.

Make sure Kodi can open the source and display its pictures before indexing it.
For the first test, use a small folder rather than an entire photo archive.

### 2. Enable sources in MyPicsDB 3

Open:

```text
Pictures
  > Picture add-ons
  > MyPicsDB 3
  > Picture sources
```

Every newly discovered source is disabled by default.

- Select a disabled source to enable it.
- The source label changes from **Disabled** to **Enabled**.
- Use the context menu to enable, disable or start a background scan of only that source.
- Select **Refresh Kodi sources** after adding, removing or renaming a source in
  Kodi. If a saved MyPicsDB 3 source no longer exists in Kodi, MyPicsDB 3 asks
  whether to remove it and its indexed pictures. Select **No** to keep it; the
  question is shown again the next time you refresh Kodi sources.

Only enabled sources are included in normal manual and automatic scans.

#### Replacing a test source with the real picture library

Disable the test source in MyPicsDB 3 before removing it from Kodi. Add or verify
the real Kodi picture source, select **Refresh Kodi sources**, remove the old
test source from MyPicsDB 3 when prompted, and enable only the real source before
scanning it.

MyPicsDB 3 deliberately keeps indexed records when a source disappears, because
a temporarily unavailable NAS must not be treated as mass deletion. If the
SQLite catalogue contains only disposable test data, close Kodi, back up the
add-on profile folder, and remove `mypicsdb3.sqlite` together with any
`mypicsdb3.sqlite-wal` and `mypicsdb3.sqlite-shm` files before the first full
production scan. Do not remove a shared MySQL/MariaDB catalogue this way.

### 3. Run the first scan

Return to the MyPicsDB 3 main menu and select **Scan now**. The scan is
recursive. It visits enabled sources, indexes supported picture files and
stores the catalogue in the selected database. **Scan now** keeps its foreground
progress dialog and can be cancelled from that dialog.

The first scan can take time on a large local collection or NAS. It is safe to
cancel the progress dialog and continue later. Subsequent scans are incremental:
unchanged files are not read and indexed again.

If Scan status reports directory-listing or other traversal errors, investigate
them before using **Clean missing records**. A source whose root is completely
unavailable is protected from mass deletion, but a partially unreadable folder
tree must be treated as an incomplete scan.

Open **Scan status** after a scan to see:

- active database backend;
- indexed and missing-picture counts;
- indexed-album count;
- last scan time and status;
- found, updated and unchanged-picture counts;
- scan errors.

**Test database connection** and **Clean missing records** are also available
from the Scan status screen.

### 4. Browse the catalogue

After the first successful scan, the add-on main menu provides:

- **Recently taken** — pictures sorted by embedded capture date when available;
- **Recently added** — pictures most recently discovered by MyPicsDB 3;
- **Random memories** — a random selection from the catalogue;
- **Recent albums** and **Random albums** — folders represented by indexed
  pictures;
- **On this day** — pictures captured on today's month and day in earlier years;
- **Years**, **Cameras** and **Keywords** — metadata-based navigation;
- **Favorites** — pictures marked through the Kodi context menu;
- **Rated pictures** — pictures with an embedded metadata rating;
- **Geotagged pictures** — pictures with stored GPS coordinates.

Open the context menu on a picture and select **Toggle favorite** to add or
remove it from Favorites. **Open containing album** opens the indexed folder.
Album context menus can also start a recursive Kodi slideshow.

The Keywords and Rated pictures views depend on metadata embedded in the source
files. Geotagged pictures requires **Store GPS coordinates** to be enabled
before the relevant pictures are scanned again.

The configurable extension list includes formats such as HEIC, HEIF and AVIF.
Indexing an extension does not guarantee that every Kodi platform or installed
image decoder can display that format.

The background service detects a local date change while Kodi is running and
refreshes date-sensitive views. On the Estuary MyPicsDB 3 home screen, the skin
is reloaded once after midnight so **On this day** changes without manual action.

### 5. Configure automatic scanning

Open **MyPicsDB 3 > Settings > Scanning** and enable **Enable automatic
scanning**. Set **Automatic scan interval (hours)** to any whole number from 1
to 720. Common choices are:

- `2` hours for frequently changing local folders;
- `6` hours for a regularly updated NAS library;
- `12` hours for a lower-impact schedule;
- `24` hours for a daily scan.

The background service waits for the configured startup delay and then runs an
incremental scan. By default, automatic scanning is disabled and scans are
paused while Kodi is playing media. **Scan now** remains available at any time.

**Scan selected source** uses Kodi's non-modal background progress indicator,
so the interface remains available. When **Pause scans during media playback**
is enabled, the selected-source scan pauses at the next file or folder checkpoint
after playback starts and resumes automatically after playback stops. This
applies to movies, TV episodes, music and other media playback. The background
indicator does not provide a cancel button; exiting Kodi cancels the scan safely.

For one Kodi device, keep the default SQLite backend. Configure MySQL/MariaDB
only when multiple Kodi devices need to share the same catalogue and all clients
can access the same picture URIs.

## Does the separate Estuary skin survive updates?

Yes. Standard Estuary and Estuary MyPicsDB 3 have different add-on IDs and live
in different directories:

```text
skin.estuary
skin.estuary.mypicsdb3
```

A Kodi update or standard Estuary update therefore does not overwrite the
MyPicsDB 3 skin. The selected MyPicsDB 3 skin remains installed and receives its
own updates through the MyPicsDB 3 repository.

The repository maintains separate Estuary channels for Kodi 21 Omega and Kodi
22 Piers. Kodi selects the matching channel from the repository add-on's
`minversion` and `maxversion` ranges. A scheduled GitHub Actions workflow checks
the official Kodi releases once per day, patches and validates a new Estuary
source, and publishes it only if every test succeeds.

A future Kodi major version can still introduce a new skin API. Until a matching
channel is configured and validated, Kodi can disable the custom skin and fall
back to standard Estuary.

Standard Estuary is never removed and can always be selected again under
**Settings > Interface > Skin**.

See [docs/ESTUARY_INTEGRATION.md](docs/ESTUARY_INTEGRATION.md) for the build and
maintenance model. For integration with user-configurable, Estuary-derived and
non-Estuary skins, see [docs/SKIN_INTEGRATION.md](docs/SKIN_INTEGRATION.md).
Only the separately packaged Estuary MyPicsDB 3 skin is currently built and
tested by this project.

## Database choice

SQLite is recommended for one Kodi device. The database is stored under the
add-on profile directory and must not be moved to SMB/NFS.

The current release records a schema version but does not yet implement database
migrations between schema versions. Back up the add-on profile before testing a
development build that changes the catalogue schema.

MySQL/MariaDB is useful when several Kodi devices see identical picture URIs.
See [docs/MYSQL_MARIADB.md](docs/MYSQL_MARIADB.md).

## Build and test

```bash
python3 -m pytest
python3 tools/verify.py
python3 tools/build.py
```

`tools/build.py` downloads the latest pinned official Estuary source for each
configured Kodi channel, extracts only `skin.estuary`, applies the MyPicsDB 3
home-screen patch and builds separate Omega and Piers repository indexes.

For an offline or local-source build, select exactly one channel:

```bash
python3 tools/build.py --channel omega --estuary-source /path/to/skin.estuary
```

To refresh the release pins manually from the official Kodi GitHub releases:

```bash
python3 tools/update_estuary_upstreams.py
```

GitHub Pages passes the previous published `repository/` tree back to the
builder. The builder adds the new patched skin, retains at most five archives
per channel and lists only the newest compatible skin in `addons.xml`.

Build output:

```text
dist/plugin.image.mypicsdb3-<version>.zip
dist/repository.mypicsdb3-<version>.zip
dist/skin.estuary.mypicsdb3-<skin-version>.zip
dist/mypicsdb3-<version>-source.zip
dist/mypicsdb3-<version>.tar.gz
dist/SHA256SUMS.txt
dist/repository/
```

The generated skin source is placed temporarily under:

```text
build/estuary/<channel>/<skin-version>/skin.estuary.mypicsdb3/
```

Generated upstream skin files are deliberately excluded from the source archive
and Git history. The official Estuary source is fetched again for reproducible
CI, Pages and release builds.

## Updates for other users

Install `repository.mypicsdb3-<version>.zip` once. When GitHub Pages is enabled
and the included Pages workflow has deployed, Kodi can discover picture add-on
and skin updates from:

```text
https://raffe1234.github.io/mypicsdb3/repository/omega/
https://raffe1234.github.io/mypicsdb3/repository/piers/
```

Change the URLs in `repository.mypicsdb3/addon.xml` and add-on metadata if the
GitHub account or repository name differs.

### If Check for updates remains at 0%

The global **Check for updates** command refreshes every enabled Kodi repository,
not only MyPicsDB 3. If updating MyPicsDB 3 directly from **My add-ons** works but
the global command remains at 0%, another enabled repository or a stalled network
request may be blocking the global refresh.

1. Restart Kodi and reproduce the problem once.
2. Inspect `kodi.log` for repository, checksum, HTTP, TLS or timeout errors.
3. Confirm that the MyPicsDB 3 repository can open `addons.xml` and
   `addons.xml.md5` from the published repository URL.
4. Temporarily disable other third-party repositories one at a time and retry the
   global update check.
5. Re-enable every repository after the test.

Do not repeatedly force-close Kodi while it is writing settings or databases. If
the interface cannot exit, collect the relevant log section before ending the
process.

## License and history

MyPicsDB 3 code is licensed under GNU GPL version 2. See `LICENSE.txt` and
`NOTICE.md`.

The generated Estuary MyPicsDB 3 package retains the upstream Estuary license,
assets and attribution. It is built from Kodi's official Estuary source and is
not an official Kodi release.

MyPicsDB 3 is not an official release by the original MyPicsDB/MyPicsDB2
authors. Contributions and issue reports are welcome.

## Versioning and releases

Update the MyPicsDB 3 plug-in and repository versions with:

```bash
python3 tools/set_version.py 0.3.0
```

The skin version and pinned upstream Kodi tag are maintained separately in
`contrib/estuary/upstream.json`. Update `CHANGELOG.md`, commit the changes, and
tag the project version with a `v` prefix. The release workflow verifies, tests,
builds all three Kodi packages and attaches the archives to the GitHub release.

## Settings display

In **Settings > General**, the numeric values are shown with descriptive labels:

- **Default items per home-screen row** — 15 by default, configurable from 1 to 50
- **Pictures per browser page**
- **Default album view**

In **Settings > Home screen**, **Configure home-screen rows** opens a visual
nine-row editor. Each row has an **On/Off** control plus buttons for moving the
view up or down.

### Repository artwork paths

The repository builder preserves every asset path declared in an add-on's
`addon.xml`, including `resources/icon.png`, `resources/fanart.jpg` and skin
screenshots. This prevents 404 responses when Kodi loads generated skin artwork.
