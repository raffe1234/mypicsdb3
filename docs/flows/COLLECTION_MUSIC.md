# Collection music playlists

This guide follows one optional music-playlist assignment from a saved smart or
manual collection through picture-slideshow startup and service-owned cleanup.
The playlist is a Kodi-accessible file reference, not imported music data.

## Data flow

```text
collection context menu
→ Assign music playlist
→ Kodi music-source file picker
→ Catalog.set_music_playlist(type, id, URI)
→ collection_music_playlists

open smart/manual collection
→ assigned URI adds Play picture slideshow with music
→ fetch bounded collection results
→ filter pictures and missing/empty URIs
→ stop existing media players
→ xbmc.PlayList(PLAYLIST_MUSIC).load(URI)
→ xbmc.Player().play(music playlist)
→ fingerprint current Kodi music queue
→ publish token + fingerprint on Home window
→ start native ordered picture slideshow directory

background service
→ MusicSlideshowMonitor reads token
→ wait for native picture player to appear
→ detect picture player ending
→ compare current queue fingerprint with owned fingerprint
→ matching queue: stop audio and clear token
→ changed queue: leave replacement audio playing and clear token
```

## Files and responsibilities

| File | Responsibility |
| --- | --- |
| `music_playlists.py` | Target-type, URI and display-label validation |
| `db/migration_steps/v0007_collection_music.py` | Schema-6-to-7 migration |
| `db/schema.py` | Fresh SQLite and MySQL/MariaDB mapping table |
| `db/catalog.py` | Assignment CRUD and target deletion cleanup |
| `views.py` | Collection context actions, picker, picture filtering and startup |
| `music_slideshow.py` | Kodi music-playlist load/play and audio-only stop helper |
| `kodi.py` | Queue fingerprint and owner-token Home property |
| `service_loop.py` | Slideshow lifecycle monitor and ownership-safe cleanup |

## Schema 7

`collection_music_playlists` stores:

```text
collection_type  smart | manual
collection_id    saved-search ID or manual-collection ID
playlist_uri     Kodi-readable playlist path/URI
updated_at       UTC catalogue timestamp
```

The composite primary key permits at most one assignment per target. Smart and
manual IDs use separate namespaces. The table intentionally has no polymorphic
foreign key; `Catalog.delete_saved_search()` and `Catalog.delete_collection()`
delete the matching mapping in the same transaction before deleting the target.

The migration creates an empty mapping table. It does not scan sources, inspect
music files, rewrite media metadata or populate assignments. Existing schema-6
catalogues therefore upgrade without a rescan.

## Picker and supported playlist files

The context action opens Kodi's single-file browser and starts in Kodi's normal
profile playlist directory, `special://profile/playlists/music/`. On Windows it
usually maps below `%APPDATA%\Kodi\userdata\playlists\music\`. The user can
navigate upward to another configured music source if the playlist is stored
elsewhere. The picker filters common ordinary playlist files:

- `.m3u`
- `.m3u8`
- `.pls`
- `.b4s`
- `.wpl`

MyPicsDB stores the selected URI exactly after trimming surrounding whitespace.
It never copies, parses or edits the playlist file. Kodi remains responsible for
resolving the entries and reporting whether the playlist is loadable and
non-empty.

## Picture-only playback policy

Assigned collection music is started only by the explicit **Play picture
slideshow with music** action. The result set is filtered to still pictures and
then exposed through the existing ordered native-slideshow directory:

- manual collections preserve `collection_items.position`;
- smart collections preserve the validated Query Model sort;
- missing media, videos, empty paths and duplicate paths are skipped;
- the first remaining picture becomes `beginslide`;
- normal video and mixed-collection commands are unchanged.

Version 0.6.0 does not pause, fade or resume music around videos. Keeping videos
on their existing video-playlist path avoids competing audio players and makes
ownership and cleanup deterministic.

## Ownership-safe cleanup

Starting a music slideshow records a random session token plus a SHA-256
fingerprint of Kodi music playlist 0. The fingerprint contains the ordered file
list and total queue length, not the current playback position, so normal song
progress does not change ownership.

The service allows a startup grace period for Kodi to open the native picture
player. After a seen picture player disappears for the end grace period:

- if the active audio queue still has the stored fingerprint, only that audio
  player is stopped;
- if the queue differs, it is treated as replacement playback and left alone;
- if audio has already ended, only the session token is cleared.

The monitor passes its active-player snapshot to the stop helper. It does not
perform a second detection poll between ownership verification and `Player.Stop`.

## Failure behaviour

- A missing assignment shows an error and starts nothing.
- A collection with no available pictures starts nothing.
- A missing, unreadable or empty playlist shows an error and starts no
  slideshow.
- If Kodi cannot expose a verifiable music queue after loading, MyPicsDB stops
  the attempted audio and aborts the slideshow.
- If native slideshow startup fails after music starts, matching owned audio is
  stopped and the session token is cleared.
- A service-monitor exception is logged once and retried on later ticks.

## Tests

- `tests/test_music_playlists.py` covers validation and labels;
- `tests/test_collection_music_catalog.py` covers assignment CRUD and deletion;
- `tests/test_music_slideshow.py` covers playlist load/play failures;
- `tests/test_music_slideshow_monitor.py` covers owned and replacement queues;
- `tests/test_kodi_slideshow_state.py` covers token and queue fingerprints;
- `tests/test_kodi_ui_smoke.py` covers picker actions, smart/manual routes and
  native slideshow startup;
- `tests/test_migrations.py` covers schema-6-to-7 upgrade;
- `tests/test_mysql_integration.py` contains the opt-in backend checks.

## Invariants

- Music assignment never changes smart/manual collection identity or contents.
- Source pictures, videos, music files and playlist files are never edited.
- Music playback is opt-in and picture-only.
- Only a queue still recognized as owned by the slideshow may be stopped.
- A replacement queue must survive slideshow cleanup.
- Smart and manual assignments behave equivalently on SQLite and MySQL/MariaDB.
- Schema migration requires no catalogue rescan.
