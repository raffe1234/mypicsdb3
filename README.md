# MyPicsDB 3

MyPicsDB 3 is an independent, community-maintained successor inspired by
MyPicsDB and MyPicsDB2. It provides a searchable picture catalogue, background
indexing and fast home-screen widgets for Kodi 21 Omega.

> Status: 0.2.3 release candidate. The catalogue, SQLite backend, scanner,
> browser routes, Estuary fork builder and package builder are covered by
> automated tests. Real Kodi installations are still required for platform and
> large-library testing before calling the project production-stable.

## Features

- Select one or more existing Kodi picture sources.
- Incremental manual or scheduled background scanning.
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
- choose the content of Row 1 through Row 9;
- set a row to None;
- arrange the rows in any order.

The first six rows are enabled by default in the order shown above through
**On this day**. Row 7 through Row 9 default to **None**, so the initial Pictures
home screen stays compact. Set any position to Favorites, Rated pictures,
Geotagged pictures or another view when you want to show more rows.

Each row position is independent, so avoid selecting the same view in more than
one position unless duplicate rows are intentional. A row set to **None** is not
shown. Rows with no indexed results also disappear until matching pictures have
been indexed.

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
- Use the context menu to enable, disable or scan only that source.
- Select **Refresh Kodi sources** after adding, removing or renaming a source in
  Kodi.

Only enabled sources are included in normal manual and automatic scans.

#### Replacing a test source with the real picture library

Disable the test source in MyPicsDB 3 before removing it from Kodi. Add or verify
the real Kodi picture source, select **Refresh Kodi sources**, and enable only
the real source before scanning it.

MyPicsDB 3 deliberately keeps indexed records when a source disappears, because
a temporarily unavailable NAS must not be treated as mass deletion. If the
SQLite catalogue contains only disposable test data, close Kodi, back up the
add-on profile folder, and remove `mypicsdb3.sqlite` together with any
`mypicsdb3.sqlite-wal` and `mypicsdb3.sqlite-shm` files before the first full
production scan. Do not remove a shared MySQL/MariaDB catalogue this way.

### 3. Run the first scan

Return to the MyPicsDB 3 main menu and select **Scan now**. The scan is
recursive. It visits enabled sources, indexes supported picture files and
stores the catalogue in the selected database.

The first scan can take time on a large local collection or NAS. It is safe to
cancel the progress dialog and continue later. Subsequent scans are incremental:
unchanged files are not read and indexed again.

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

Two limitations remain:

1. Upstream Estuary fixes are not inherited automatically. Each MyPicsDB 3 skin
   release is rebuilt from a pinned official Kodi Estuary source tag and then
   patched. The current build is based on `21.3-Omega`.
2. A future Kodi major version can introduce a new skin API. Kodi may disable an
   incompatible skin and fall back to standard Estuary until a compatible
   MyPicsDB 3 skin release is installed.

Standard Estuary is never removed and can always be selected again under
**Settings > Interface > Skin**.

See [docs/ESTUARY_INTEGRATION.md](docs/ESTUARY_INTEGRATION.md) for the build and
maintenance model.

## Database choice

SQLite is recommended for one Kodi device. The database is stored under the
add-on profile directory and must not be moved to SMB/NFS.

MySQL/MariaDB is useful when several Kodi devices see identical picture URIs.
See [docs/MYSQL_MARIADB.md](docs/MYSQL_MARIADB.md).

## Build and test

```bash
python3 -m pytest
python3 tools/verify.py
python3 tools/build.py
```

`tools/build.py` downloads the official Kodi source archive pinned in
`contrib/estuary/upstream.json`, extracts only `skin.estuary`, applies the
MyPicsDB 3 home-screen patch and packages the independent skin.

For an offline or local-source build:

```bash
python3 tools/build.py --estuary-source /path/to/skin.estuary
```

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
build/skin.estuary.mypicsdb3/
```

Generated upstream skin files are deliberately excluded from the source archive
and Git history. The official Estuary source is fetched again for reproducible
CI, Pages and release builds.

## Updates for other users

Install `repository.mypicsdb3-<version>.zip` once. When GitHub Pages is enabled
and the included Pages workflow has deployed, Kodi can discover picture add-on
and skin updates from:

```text
https://raffe1234.github.io/mypicsdb3/repository/
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

- **Default items per home-screen row**
- **Pictures per browser page**

In **Settings > Home screen**, each of the nine positions shows both its row
number and the currently selected content. The default selections are visible
without first opening each setting.

### Repository artwork paths

The repository builder preserves every asset path declared in an add-on's
`addon.xml`, including `resources/icon.png`, `resources/fanart.jpg` and skin
screenshots. This prevents 404 responses when Kodi loads generated skin artwork.
