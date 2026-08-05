# MyPicsDB 3

MyPicsDB 3 is an independent, community-maintained successor inspired by
MyPicsDB and MyPicsDB2. It provides a searchable picture and optional
home-video catalogue, background indexing, mixed slideshows and fast home-screen
widgets for Kodi 21 Omega and Kodi 22 Piers.

> Status: 0.4.2 development release. The catalogue, SQLite backend, scanner,
> browser routes, Estuary fork builder and package builder are covered by
> automated tests. The schema-1-to-5 migrations, search-document backfill,
> mixed-media playlist integration, backup and restore, and large-library search
> performance still require documented validation on real Kodi installations before calling the project
> production-stable.

## Want to help develop MyPicsDB 3?

New contributors do not need to read the whole repository before making a
useful change. Start with [Start here: developing MyPicsDB 3](docs/START_HERE.md),
which explains the two entry points, the main modules, the most important safety
rules and where to begin for different types of work.

A suitable reading order is:

1. read this README for the user-facing purpose and behaviour;
2. read [START_HERE.md](docs/START_HERE.md) for the system overview;
3. choose the relevant guide in the [data-flow index](docs/flows/README.md);
4. set up and test the project with
   [LOCAL_DEVELOPMENT.md](docs/LOCAL_DEVELOPMENT.md);
5. follow [CONTRIBUTING.md](CONTRIBUTING.md) for branches, commits, GitHub
   Actions and pull requests.

For the component boundaries and long-lived safety rules, see
[ARCHITECTURE.md](docs/ARCHITECTURE.md).

## Features

- Select one or more existing Kodi picture sources.
- Incremental manual and scheduled background scanning, with local folder
  checkpoints that resume a compatible interrupted scan from the first
  unfinished folder.
- Session-visible scan progress for manual and automatic scans, with a
  confirmation-protected **Stop scan** action that cancels at the next safe
  file or folder checkpoint. Scan progress is hidden while Live TV, TV
  episodes, movies or other media are playing and returns after playback.
- Faster home rows with a separate 4–40 item limit that updates live, direct
  Kodi texture-cache artwork and render-friendly stills ahead of RAW/HEIF and
  video thumbnails.
- SQLite by default, using WAL mode and a local add-on profile database.
- Optional shared MySQL/MariaDB catalogue through PyMySQL.
- EXIF capture date, camera, orientation, dimensions, rating and optional GPS.
- Basic embedded XMP keywords, rating, location and capture date.
- IPTC keywords, caption and location from JPEG files through IPTCInfo3 when
  available.
- Missing-source safety: an unavailable SMB/NFS source or incomplete directory
  traversal is never interpreted as deletion of unseen media.
- Lazy Kodi thumbnail caching, including native generated-frame previews for
  indexed videos; no duplicate thumbnail tree is generated.
- Global Unicode-normalized AND search across filename, caption, keywords,
  path parts, camera and stored location fields.
- Favorites, ratings, keywords, cameras, year/month/day and geotagged views.
- Picture-first album artwork, preferring broadly supported still formats,
  with RAW/HEIF and video fallback for collections that need them.
- Guarded album-view activation that waits for the active, stable Pictures
  container, skips empty results and never changes a background window or widget
  layout.
- Optional indexing of common home-video formats alongside pictures, including
  a dedicated **Videos** node and mixed picture/video date and folder views.
- Native recursive slideshows for picture-only album trees and database-backed
  mixed playlists for album trees containing video or results spanning multiple
  folders, with bounded playlist batches.
- Optional global minimum-rating display policy for normal browser and widget
  views, with a temporary all-pictures override.
- Save, reopen, rename and delete named global searches, with normal
  pagination and slideshow support.
- Kodi smart-filter editor with all/any matching, metadata criteria, result
  preview and saved smart collections. Saved smart collections can be placed as
  ordered Pictures-home rows in poster, square or wide format.
- Versioned, validated Query Model used by global and saved searches; stored
  queries are revalidated when opened and never expose raw SQL.
- Stable widget endpoints for configurable skins.
- Optional **Estuary MyPicsDB 3** skin with picture rows on the home screen.
- GitHub Actions, Kodi repository generation and GitHub Pages deployment.

## Widget endpoints

```text
plugin://plugin.image.mypicsdb3/recent-taken?widget=1&limit=15
plugin://plugin.image.mypicsdb3/recent-added?limit=15
plugin://plugin.image.mypicsdb3/random?limit=15
plugin://plugin.image.mypicsdb3/recent-folders?limit=15
plugin://plugin.image.mypicsdb3/random-folders?limit=15
plugin://plugin.image.mypicsdb3/on-this-day?limit=15
plugin://plugin.image.mypicsdb3/on-this-day-random?limit=15
plugin://plugin.image.mypicsdb3/videos?limit=15
plugin://plugin.image.mypicsdb3/years
plugin://plugin.image.mypicsdb3/cameras
plugin://plugin.image.mypicsdb3/keywords
plugin://plugin.image.mypicsdb3/favorites?limit=15
plugin://plugin.image.mypicsdb3/rated?limit=15
plugin://plugin.image.mypicsdb3/geotagged?limit=15
```

Widget calls only read indexed database rows. They never scan picture sources.
They use the local **Minimum picture rating** display policy.

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
     notifications, plus which browsing nodes are visible in the add-on menu;
   - **Home screen** — Media sources and the content and order of the Estuary
     MyPicsDB 3 rows;
   - **Scanning** — automatic scans, scan timing, playback pauses, picture and
     optional video file types, exclusions and batch size;
   - **Metadata** — XMP, IPTC, GPS storage and metadata read limits;
   - **Database** — local SQLite or a shared MySQL/MariaDB catalogue;
   - **Maintenance** — missing-record retention and debug logging.

### Optional RAW and HEIF image decoders

MyPicsDB 3 can index supported file extensions, but Kodi must also have an
image decoder installed to display the files and create thumbnails. Open:

```text
Add-ons
  > Install from repository
  > Kodi Add-on repository
  > Image decoders
```

- Install **Libraw image decoder** for Nikon NEF and other RAW formats supported
  by Libraw.
- Install **HEIF image decoder** for HEIC and HEIF pictures.

Restart Kodi after installing a decoder. A new catalogue scan is needed only
when the file extension was not enabled during the earlier scan. Media that is
already indexed does not need to be rescanned merely because a decoder was
installed.

## Optional video support

Video indexing is disabled by default. Enable **Settings > Scanning > Include
videos**, review the video-extension list and run **Scan now**. Videos are stored
in the existing catalogue with `media_type=video`. In 0.2.22, their date comes
from the file modification time and their MIME type is inferred from the
filename; no separate video scraper or `ffprobe` dependency is used.

Videos appear in folder, recent, date, favorites and search results and in the
dedicated **Videos** node. Camera, keyword, geolocation and embedded-rating
views remain picture-only. Minimum-picture-rating policies still include videos
without assigning a fake rating to them.

Kodi plays an individual video directly. MyPicsDB 3 asks Kodi's native
`image://video@...` loader for a representative frame when no explicit image
thumbnail exists. Generation is lazy and device-local, so the first view can
take a few seconds for large SMB/NFS videos; no frames are extracted during the
catalogue scan. Album and date widgets publish the selected representative
artwork as thumb, icon, poster and landscape. Common still formats such as JPEG,
PNG, WebP and TIFF are preferred for album covers; RAW/HEIF pictures remain
available when no common still exists, and a video-only collection falls back
to Kodi's generated video frame. Widget items also publish filenames and album names as titles. Estuary
MyPicsDB 3 uses a dedicated picture-poster widget that reserves a caption area
under each thumbnail, shows a subdued label normally and a brighter scrolling
label while focused. Standard Estuary movie and TV widgets remain unchanged.
Widget pictures and still pictures selected inside indexed albums open through
Kodi's native picture viewer. Still-picture rows deliberately avoid a
VideoInfoTag so Kodi does not route JPEG/PNG files through VideoPlayer; videos
keep normal playback and album tiles open in the Pictures window. No rescan is
required for these display choices. Use **Play slideshow from here** on
a media item or **Play mixed
slideshow** on an album. Video-only results use Kodi's video playlist.
Picture-only album trees use Kodi's native recursive slideshow. Mixed album
playback includes descendants and is capped at 5,000 media files. A lightweight
service monitor advances a compatible picture playlist after an indexed video
finishes.

Kodi builds do not all route picture playlist 2 through the picture player.
MyPicsDB 3 therefore probes one known picture before constructing a potentially
large database playlist. The probe must report the exact expected file twice;
an unrelated or stale picture player is ignored, and an exact `VideoPlayer`
match takes precedence. If Kodi treats the JPEG as one-frame MJPEG video, the
result is cached for the current Kodi session and album playback uses Kodi's
native recursive folder slideshow. Cross-folder picture slideshows cannot be
represented safely on such installations, so MyPicsDB shows an explanatory
notification instead of flashing through the files.

Disabling video support does not immediately delete stored rows. Run a new scan
to mark video rows missing, then use **Scan status > Clean missing records**
after the configured retention period.

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

The skin can show **Media sources** plus nine configurable MyPicsDB 3 rows. Ten view types are available, so either On this day variant or both can be enabled:

- Recently taken
- Recently added
- Random memories
- Recent albums
- Random albums
- On this day
- On this day - random
- Favorites
- Rated pictures
- Geotagged pictures

Open **Pictures > Picture add-ons > MyPicsDB 3 > Settings > Home screen** to:

- show or hide Media sources;
- choose **Home-screen pictures per row** from 4 to 40;
- choose how often the three random rows receive a new selection, in hours
  (two hours by default); repeated Kodi requests during the interval keep the
  current selection stable;
- open **Configure home-screen rows**;
- enable or disable built-in rows;
- add a saved smart collection as its own row;
- move built-in and smart rows up or down in one shared order;
- choose **Poster**, **Square** or **Wide** for each smart row.

The editor lists all built-in views and any smart collections already added to
the home screen. The first six built-in views are enabled by default through
**On this day**. On this day - random, Favorites, Rated pictures and Geotagged
pictures are disabled by default, so the initial home screen stays compact. At
most nine rows can be visible at the same time. Existing Row 1 through Row 9
choices are migrated automatically the first time the editor is opened.

Changing the per-row value changes the provider URL and invalidates only the
MyPicsDB 3 rows; a choice such as 39 is therefore no longer capped by an old
ten-item widget result. Smart rows run the saved Query Model again whenever the
widget reloads, so newly scanned matching media appears automatically. Renaming
or deleting a saved collection updates or removes its home row. Rows with no
indexed results disappear until matching media has been indexed.

Random memories, Random albums and On this day - random use a separate refresh
generation. The background service advances it at the configured hourly
interval, so non-random rows keep their current provider results. A scan that
changes the catalogue, a relevant home-screen setting change or **Refresh random
selections** can produce a new random selection before the interval expires.

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
optional dependency and is used only for files identified as JPEG; EXIF and XMP
indexing continue if it is unavailable.

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
recursive. It visits enabled sources, indexes supported media files and stores
the catalogue in the selected database. It uses Kodi's non-modal background
progress indicator, so you can continue using the interface. Exiting Kodi
cancels the scan safely. While a scan is active, **Scan now** is replaced by
**Stop scan**. Confirming that action requests a soft stop; the current file
operation is allowed to finish before the scan records its cancelled state.
The stop action does not refresh the active Kodi container while the scan
plug-in call is still finishing, avoiding a Kodi GUI update race.

The first scan can take time on a large local collection or NAS. Subsequent
scans are incremental: unchanged files are not read and indexed again. MyPicsDB 3
also saves an atomic local checkpoint after each fully processed folder. If Kodi
exits, the add-on is updated or **Stop scan** is used, the next scan with the same
enabled sources and scan settings continues from the first unfinished folder.
Sources completed before the interruption are skipped.

Checkpoints are stored in the local Kodi add-on profile and expire after 24
hours. They are discarded when the source selection, database identity, picture
or video extensions, exclusions or metadata settings change. For example, adding
`nef` after stopping a scan deliberately starts a fresh traversal so earlier
folders are checked for NEF files. With a shared MySQL/MariaDB catalogue, each
Kodi device still keeps its own local traversal checkpoint.

If a folder cannot be listed, Scan status reports `partial`. MyPicsDB 3 still
indexes folders that were read successfully, but it skips missing-record
marking for that source. Genuine deletions are marked during the
next complete scan. Investigate repeated traversal errors before using **Clean
missing records**.

Open **Scan status** after a scan to see:

- active database backend;
- indexed and missing-picture counts;
- indexed-album count;
- last scan time, duration and status;
- elapsed time when Scan status is opened or refreshed during a running scan;
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
- **On this day** — all matching pictures from earlier years, newest year first;
- **On this day - random** — a freshly shuffled sample across all matching earlier years;
- **Years** — browse by year, then month and day, with a separate **No date** folder;
- **Cameras** and **Keywords** — metadata-based navigation;
- **Favorites** — pictures marked through the Kodi context menu;
- **Rated pictures** — pictures with an embedded metadata rating;
- **Geotagged pictures** — pictures with stored GPS coordinates;
- **Videos** — all indexed home videos, when optional video indexing is enabled;
- **Saved searches** — named global searches and smart collections that can be
  reopened with normal pagination and slideshow support;
- **Create smart collection** — combine metadata criteria in a Kodi dialog,
  preview the current result count and save the validated filter.

Select **Refresh random selections** to request new results for Random memories,
Random albums and On this day - random. With Estuary MyPicsDB 3, the action clears
the remembered horizontal row position before reloading the skin, so the fresh
selection starts at its first tile. It does not scan the filesystem or change
the catalogue.

Open **Settings > General > Configure add-on menu** to show or hide the
configurable catalogue browsing nodes. Search, Saved searches, Create smart
collection, Picture sources, Refresh random selections, Scan now, Scan status
and Settings always remain visible.

Open the context menu on a picture and select **Toggle favorite** to add or
remove it from Favorites. **Open containing album** opens the indexed folder.
Album context menus can also start a recursive Kodi slideshow.

The Keywords and Rated pictures views depend on metadata embedded in the source
files. Geotagged pictures requires **Store GPS coordinates** to be enabled
before the relevant pictures are scanned again.

The default picture-extension list includes Nikon NEF RAW files as well as HEIC,
HEIF and AVIF. Existing installations that still use the unchanged pre-0.2.44
default are upgraded automatically to include `nef`; custom extension lists are
left unchanged. Kodi needs **Libraw image decoder** to display supported RAW
files such as NEF and **HEIF image decoder** to display HEIC/HEIF. AVIF support
depends on the Kodi build and installed decoders. Indexing an extension does not
guarantee that every Kodi platform can display it.

Synology `@eaDir` metadata directories are always ignored, even if the custom
exclusion setting is empty. A rescan marks thumbnails that were indexed by an
older version as missing; the normal missing-record cleanup can then remove
their retained database rows.

The background service detects a local date change while Kodi is running and
refreshes date-sensitive views without reloading the complete skin. Both
**On this day** rows therefore change without forcing every home image to be
decoded again.

### 5. Search the whole catalogue

Select **Search** at the top of the MyPicsDB 3 main menu and enter one or more
words. Search covers indexed filename, caption, keywords, path parts, camera
make/model, city, state, country and sublocation. Punctuation separates words.
Unicode text is normalized and case-folded, so Swedish letters such as å, ä and
ö are retained.

Multiple words use AND semantics: every word must occur somewhere in the same
picture's search document, but the words may come from different fields. For
example, `fujifilm london summer` can match a camera make, a city and a
keyword on one picture. Search does not currently implement phrase search,
fuzzy matching or prefix completion.

Select **Save this search** at the top of a result list and enter a unique name.
Open **Saved searches** from the main menu to run it again against the current
catalogue. Saved searches retain normal pagination and **Play slideshow from
here** support. Use a saved search's context menu to rename or delete it. The
add-on stores the validated query rather than a frozen copy of the results, so
newly indexed matching media can appear the next time the search is opened.

Select **Create smart collection** to build a reusable filter without writing a
text query. Choose whether all criteria or any criterion must match, then add
rules for text, date range, rating, favorite state, source, camera, keyword or
pictures/videos. You can remove or edit criteria, choose the result order,
preview the matching count and up to ten filenames, and decide whether the
collection should use the configured global minimum-rating policy. Saving the
collection opens it immediately and makes it available under **Saved searches**.
Open **Settings > Home screen > Configure home-screen rows** to add that saved
collection as a Pictures-home row and choose its order and display mode.

The configured minimum-rating policy also applies to search results and saved
searches. Use **Show all pictures temporarily** from the main menu before
searching or opening a saved search to bypass the policy for that browsing
session.

### 6. Configure the minimum-rating display policy

Open the context menu anywhere inside MyPicsDB 3 and select **Minimum
picture rating**, or open **MyPicsDB 3 > Settings > General > Minimum picture
rating**, to choose which pictures normal browser and widget views should show:

- **All pictures** includes pictures with no stored rating, explicit rating 0,
  and ratings 1 through 5.
- **Rated and unrated (exclude rating 0)** includes pictures with no stored
  rating and ratings 1 through 5, but hides explicit rating 0.
- **Rating 1 or higher** through **Rating 5** show only pictures at or above
  the selected threshold.

The policy applies to picture lists, album counts and representative artwork,
date groups, cameras, keywords and home-screen widgets. It does not change
scanning, metadata extraction or stored database values. The active policy is
shown in the browser category. Open **Show all pictures temporarily** from the
add-on main menu to bypass the configured policy for that browsing session.

### 7. Query Model, global search and saved searches

Version 0.2.19 extended Query Model version 1 with the allowlisted `text` /
`contains_tokens` rule used by Kodi global search. Version 0.2.34 added named
saved searches backed by canonical Query Model JSON in schema 5. Version 0.3.0
adds the first Kodi smart-filter editor and the allowlisted `media_type` field.
The model validates nested all/any/not rules for rating, favorite, source,
album, date range, camera, keyword, text and picture/video type, and compiles
only trusted SQL with bound parameters for SQLite and MySQL/MariaDB.

Search text is never copied into SQL. It is converted to normalized tokens and
matched against schema-3 search documents maintained by scans and the schema-2
to schema-3 migration. Saved-search plugin URLs contain only a database row ID;
the stored query version and JSON are parsed and validated every time the search
is opened. The 0.3.0 editor intentionally creates one flat all/any group;
nested and negated groups remain supported by the underlying model but are not yet exposed
in the Kodi dialog. See [Query Model version 1](docs/QUERY_MODEL.md),
[Global search](docs/GLOBAL_SEARCH.md) and
[Database migrations](docs/DATABASE_MIGRATIONS.md).

### 8. Configure automatic scanning

Open **MyPicsDB 3 > Settings > Scanning** and enable **Enable automatic
scanning**. Set **Automatic scan interval (hours)** to any whole number from 1
to 720. Common choices are:

- `2` hours for frequently changing local folders;
- `6` hours for a regularly updated NAS library;
- `12` hours for a lower-impact schedule;
- `24` hours for a daily scan.

The background service waits for the configured startup delay and then runs an
incremental scan. By default, automatic scanning is disabled and scans are
deferred while Kodi is playing media. Automatic scans use the same non-modal
background progress indicator as manual scans. The main menu and **Scan status**
show the current source, file and number of discovered media items. If **Pause
scans during media playback** is disabled, scanning may continue silently while
Live TV, a TV episode, a movie or other media is playing. The background
progress dialog closes during playback and returns automatically after playback
stops. **Scan status** still exposes the current source and count.

Both **Scan now** and **Scan selected source** use Kodi's non-modal background
progress indicator, so the interface remains available. When **Pause scans
during media playback** is enabled, both manual and automatic scans pause at the
next file or folder checkpoint after playback starts and resume automatically
after playback stops. This applies to movies, TV episodes, music and other media
playback. The progress dialog is closed before playback and no pause, resume,
completion or cancellation notification is shown over the playing media. The
background indicator itself does not provide a cancel button, but the MyPicsDB 3
main menu and **Scan status** expose **Stop scan** with a confirmation prompt.
Exiting Kodi also interrupts the scan safely. The log distinguishes a user
request from an interruption caused by Kodi shutdown or an add-on service restart.
The next compatible scan resumes from the saved folder checkpoint; an expired or
incompatible checkpoint is logged and discarded before a clean traversal starts.

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
22 Piers. Each generated skin pins the validated `xbmc.gui` compatibility
version for its channel instead of inheriting a potentially changing upstream
value. Kodi selects the matching channel from the repository add-on's
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

The current development release uses schema version 5 for both SQLite and
MySQL/MariaDB. Schema 2 adds the year-first date-browsing index. Schema 3 adds
one normalized search document per picture and backfills existing catalogues.
Schema 4 adds the picture/video media type. Schema 5 adds validated named saved
searches. Existing SQLite databases receive an atomic, integrity-checked backup
before a schema migration; MySQL/MariaDB operators must keep an external
backup. See [docs/DATABASE_MIGRATIONS.md](docs/DATABASE_MIGRATIONS.md) before
testing a development build that changes the catalogue schema.

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

Update the MyPicsDB 3 plug-in version with:

```bash
python3 tools/set_version.py 0.4.2
```

The repository add-on keeps its existing version during normal plug-in
releases. Bump it only when `repository.mypicsdb3` itself changes:

```bash
python3 tools/set_version.py 0.4.2 --repository-version 0.2.27
```

The skin version and pinned upstream Kodi tag are maintained separately in
`contrib/estuary/upstream.json`. Update `CHANGELOG.md`, commit the changes, and
tag the project version with a `v` prefix. The release workflow verifies, tests,
builds all three Kodi packages and attaches the archives to the GitHub release.

## Settings display

In **Settings > General**, the numeric values are shown with descriptive labels:

- **Default items per widget** — 15 by default, configurable from 1 to 50
- **Pictures per browser page**
- **Default album view**

**Configure add-on menu** opens a multi-select dialog for the catalogue browsing
nodes shown between Picture sources and the scan actions.

In **Settings > Home screen**, **Home-screen pictures per row** is separate from
the general widget size and accepts 4–40. **Refresh random home-screen rows every
(hours)** defaults to 2 and accepts 1–720. **Configure home-screen rows** opens
the combined built-in/smart editor. It supports visibility, ordering, adding or
removing saved smart collections and Poster/Square/Wide mode for smart rows.

### Repository artwork paths

The repository builder preserves every asset path declared in an add-on's
`addon.xml`, including `resources/icon.png`, `resources/fanart.jpg` and skin
screenshots. This prevents 404 responses when Kodi loads generated skin artwork.
