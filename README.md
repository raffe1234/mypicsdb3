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
