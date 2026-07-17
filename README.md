# MyPicsDB 3

MyPicsDB 3 is an independent, community-maintained successor inspired by
MyPicsDB and MyPicsDB2. It provides a searchable picture catalogue and fast
skin widgets for Kodi 21 Omega and later.

> Status: 0.1.0 release candidate. The core catalogue, SQLite backend, scanner,
> browser routes and package builder are covered by automated tests. A real Kodi
> installation is still required for final platform testing before calling the
> release production-stable.

## Features

- Select one or more existing Kodi picture sources.
- Incremental manual or background scanning.
- SQLite by default, using WAL mode and a local add-on profile database.
- Optional shared MySQL/MariaDB catalogue through PyMySQL.
- EXIF capture date, camera, orientation, dimensions, rating and GPS.
- Basic embedded XMP keywords, rating, location and capture date.
- IPTC keywords, caption and location through IPTCInfo3 when available.
- GPS storage is disabled by default.
- Missing-source safety: an unavailable SMB/NFS source is never interpreted as
  deletion of every picture.
- Lazy Kodi thumbnail caching; no duplicate thumbnail tree is generated.
- Favorites, ratings, keywords, cameras, years and geotagged views.
- Stable widget endpoints for Estuary mods and configurable skins.
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

## Install a local test build

1. Run `python3 tools/build.py`.
2. Copy `dist/plugin.image.mypicsdb3-0.1.0.zip` to the Kodi device.
3. In Kodi, enable installation from unknown sources for this test.
4. Select **Add-ons > Install from zip file**.
5. Open **Pictures > Picture add-ons > MyPicsDB 3**.
6. Open **Picture sources**, enable one or more sources, then run **Scan now**.

Kodi resolves ExifRead and PyMySQL from its add-on repositories. IPTCInfo3 is an
optional dependency; EXIF and XMP indexing continue if it is unavailable.

## Using MyPicsDB 3 in Kodi

### 1. Add picture sources to Kodi

MyPicsDB 3 reads the picture sources that already exist in Kodi. If the source
you want is not visible in Kodi yet, add it first from the Pictures section by
using **Add pictures...**. Local folders, SMB shares, NFS shares and other
locations supported by Kodi can be used.

Make sure Kodi can open the source and display its pictures before indexing it.
For a first test, use a small folder rather than an entire photo archive.

### 2. Enable sources in MyPicsDB 3

Open:

```text
Pictures
  > Picture add-ons
  > MyPicsDB 3
  > Picture sources
```

MyPicsDB 3 imports Kodi's current picture-source list. Every newly discovered
source is disabled by default.

- Select a disabled source to enable it.
- The source label changes from **Disabled** to **Enabled**.
- Use the context menu to toggle a source or scan only that source.
- Select **Refresh Kodi sources** after adding, removing or renaming a source in
  Kodi.

Only enabled sources are included in normal manual and automatic scans.

### 3. Run the first scan

Return to the MyPicsDB 3 main menu and select **Scan now**. The scan is
recursive. It visits the enabled sources, indexes supported picture files and
stores the catalogue in the selected database.

The first scan can take time on a large local collection or NAS. It is safe to
cancel the progress dialog and continue later. Subsequent scans are
incremental: unchanged files are not read and indexed again.

Open **Scan status** after a scan to see:

- the active database backend;
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

### 5. Enable automatic scans when the first test works

Open **Settings > Scanning** and enable **Enable automatic scanning**. The
background service waits for the configured startup delay and then scans at the
configured interval. By default, automatic scanning is disabled and scans are
paused while Kodi is playing media.

For one Kodi device, keep the default SQLite backend. Configure MySQL/MariaDB
only when multiple Kodi devices need to share the same catalogue and all
clients can access the same picture URIs.

### Standard Estuary home screen

Installing MyPicsDB 3 does not by itself add rows to standard Estuary's Pictures
home screen. Kodi add-ons must not modify another installed add-on, and an
Estuary update could overwrite such changes.

Until a separate Estuary fork is installed, use MyPicsDB 3 from:

```text
Pictures > Picture add-ons > MyPicsDB 3
```

The project contains stable `plugin://` widget endpoints and an Omega Estuary
patch helper for creating the separately named **Estuary MyPicsDB 3** skin. See
[docs/ESTUARY_INTEGRATION.md](docs/ESTUARY_INTEGRATION.md). Configurable skins
can use the endpoints listed under [Widget endpoints](#widget-endpoints)
directly.

## Database choice

SQLite is recommended for one Kodi device. The database is stored under the
add-on profile directory and must not be moved to SMB/NFS.

MySQL/MariaDB is useful when several Kodi devices see identical picture URIs.
See [docs/MYSQL_MARIADB.md](docs/MYSQL_MARIADB.md).

## Estuary

Kodi add-ons are not allowed to edit another add-on's files. MyPicsDB 3 therefore
cannot silently alter standard Estuary. The repository includes an Omega
Estuary replacement block and a patch helper for a separately named skin fork.
See [docs/ESTUARY_INTEGRATION.md](docs/ESTUARY_INTEGRATION.md).

For QNAP publication commands, see [docs/QNAP_GITHUB.md](docs/QNAP_GITHUB.md).

## Build and test

```bash
python3 -m pytest
python3 tools/verify.py
python3 tools/build.py
```

Build output:

```text
dist/plugin.image.mypicsdb3-0.1.0.zip
dist/repository.mypicsdb3-0.1.0.zip
dist/mypicsdb3-0.1.0-source.zip
dist/mypicsdb3-0.1.0.tar.gz
dist/SHA256SUMS.txt
dist/repository/
```

## Updates for other users

Install `repository.mypicsdb3-0.1.0.zip` once. When GitHub Pages is enabled for
the repository and the included Pages workflow has deployed, Kodi can discover
new versions from:

```text
https://raffe1234.github.io/mypicsdb3/repository/
```

Change the URLs in `repository.mypicsdb3/addon.xml` and add-on metadata if the
GitHub account or repository name differs.

## License and history

GNU GPL version 2. See `LICENSE.txt` and `NOTICE.md`.

MyPicsDB 3 is not an official release by the original MyPicsDB/MyPicsDB2
authors. Contributions and issue reports are welcome.

## Versioning and releases

Update all package version fields with:

```bash
python3 tools/set_version.py 0.2.0
```

Update `CHANGELOG.md`, commit the change, and tag the same version with a `v`
prefix. The release workflow verifies, tests and attaches the built archives to
the GitHub release.
