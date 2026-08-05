# Changelog

## 0.4.7 - 2026-08-05

- Fix still pictures opened from Recent albums, Random albums and other indexed
  album views being sent to Kodi's VideoPlayer and returning immediately to the
  thumbnail grid instead of opening in the native picture viewer.
- Keep `MyPicsDB3.WidgetLabel` available for Estuary captions while avoiding a
  VideoInfoTag on still-picture rows. Video items and album tiles retain their
  existing metadata and behaviour. No database migration or rescan is required.

## 0.4.6 - 2026-08-05

- Show **Scan duration** for the latest completed scan on the Scan status
  screen.
- Show **Elapsed time** when Scan status is opened or refreshed while a
  manual or automatic scan is running.
- Accept both SQLite timestamp strings and MariaDB/PyMySQL datetime values;
  invalid or incomplete timestamps are omitted safely. No database migration or
  rescan is required.

## 0.4.5 - 2026-08-05

- Fix Random memories, Random albums and On this day - random changing whenever
  Kodi re-queries an unchanged home provider during the configured interval.
- Derive the database random pivot from the normal and random provider
  generations, keeping each selection stable until a scheduled, scan, settings
  or manual generation change.
- Keep database schema 5, Estuary revisions 12/10 and repository add-on version
  0.2.26 unchanged. No catalogue rescan is required.

## 0.4.4 - 2026-08-05

- Add **Refresh random home-screen rows every (hours)** under **Settings > Home
  screen**, with a default of two hours and a supported range of 1–720 hours.
- Give Random memories, Random albums and On this day - random a separate
  Home-window generation value. Scheduled refreshes therefore rerun only the
  random providers instead of rebuilding unrelated MyPicsDB 3 rows.
- Keep existing early-refresh paths: catalogue-changing scans and relevant
  home-screen changes still invalidate all MyPicsDB 3 providers, while
  **Refresh random selections** also advances the random generation immediately.
- Add service scheduling and regression coverage for startup scheduling,
  interval changes and elapsed intervals. No database migration or rescan is
  required.
- Bump generated Estuary revisions to Kodi 21 revision 12 and Kodi 22 revision
  10. The repository add-on remains unchanged.

## 0.4.3 - 2026-07-31

- Add a clear developer onboarding path from the main README.
- Add architecture and data-flow documentation for the plug-in, background
  service, scanner, database, search, slideshows and Estuary integration.
- Add local development instructions and practical Git, GitHub Actions and
  QNAP/NAS workflows.
- Expand the contribution guide with testing, documentation and release
  guidance.

## 0.4.2 - 2026-07-30

- Restore the original `widget_limit` setting as the single source of truth for
  MyPicsDB home-screen row counts. Version 0.3.5 accidentally introduced a
  second visible setting whose default of 10 masked existing values such as 39.
- Move the original setting to the Home screen category, keep the temporary
  0.3.5 setting hidden for compatibility, and migrate either stored value once.
- Clamp the unified home-screen row count to 4-40 and log the one-time migration
  inputs and result so installations can be diagnosed without debug logging.

## 0.4.1 - 2026-07-30

- Fix the home-screen row count regression introduced in 0.3.5. Kodi 20 and
  newer now read integer settings through the typed `Settings.getInt()` API,
  with the legacy string API retained as a compatibility fallback.
- Make the configured `home_widget_limit` the sole source of truth for home
  providers. Cached provider URLs carrying an old `limit=10` value can no
  longer override a newly selected value such as 39.
- Remove the dynamic limit expression from Estuary provider URLs. The skin
  keeps a fixed safe capacity of 40 while the plug-in returns exactly the
  configured 4–40 items; the generation parameter still invalidates cached
  providers when the setting changes.
- Correct the numeric spinner controls to use integer formatting and publish
  the loaded home limit on the Home window for diagnostics. The service logs
  the value at startup and whenever it changes.
- Bump generated Estuary revisions to Kodi 21 revision 11 and Kodi 22 revision
  9. Database schema 5, Query Model version 1 and repository add-on version
  0.2.26 remain unchanged; no catalogue rescan is required.

## 0.4.0 - 2026-07-30

- Fix **Home-screen pictures per row** values above ten not taking effect. Every
  bundled provider URL now carries both the live integer setting and a
  Home-window generation value, while the plug-in honours the explicit 4–40
  value even if an already-running interpreter still has an older settings
  snapshot. Changing 10 to 39 therefore produces a 39-item request rather than
  being silently capped at ten.
- Add saved smart collections to **Configure home-screen rows**. A saved Query
  Model can be added as its own Pictures-home row, enabled or disabled, moved
  among built-in rows and removed again without deleting the saved collection.
- Add per-smart-row **Poster**, **Square** and **Wide** display modes through
  dedicated Estuary widget includes. Built-in rows retain their existing poster
  presentation and click behaviour.
- Store the mixed layout in a versioned hidden setting and materialize it into
  nine skin slots. Legacy built-in Row 1–Row 9 layouts migrate automatically,
  invalid or deleted saved-search IDs are discarded, and at most nine rows are
  enabled.
- Keep smart home rows synchronized when a saved collection is renamed or
  deleted. The home screen uses the current collection name and removes deleted
  rows instead of retaining a broken provider.
- Invalidate only MyPicsDB 3 home providers after a manual or automatic scan
  actually adds, updates or marks media missing. Standard and smart rows then
  rerun against the current catalogue without a full skin reload.
- Bump generated Estuary revisions to Kodi 21 revision 10 and Kodi 22 revision
  8. Database schema 5, Query Model version 1 and repository add-on version
  0.2.26 remain unchanged; no catalogue rescan is required.

## 0.3.5 - 2026-07-30

- Reduce home-screen artwork stalls by giving the Estuary rows a separate
  **Home-screen pictures per row** limit. It defaults to 10 and can be set from
  4 to 40 without changing normal browser page sizes.
- Mark every bundled home provider with `home=1`, fetch a small candidate pool
  and place JPEG, PNG, WebP, BMP, GIF and TIFF pictures before RAW/HEIF files
  and generated video frames while preserving the original order inside each
  class. This keeps slow NEF/HEIC/video artwork out of the first visible slots
  whenever faster stills are available.
- Supply one canonical `image://` texture-cache URI and make the custom Estuary
  widget read `ListItem.Art(thumb)` directly instead of probing Estuary's movie
  artwork variables. Existing catalogue rows benefit without a rescan.
- Replace the automatic local-date `ReloadSkin()` with a lightweight
  `Container.Refresh`, avoiding a full invalidation and reload of all home
  widgets at midnight. Explicit user-driven random refreshes still rebuild the
  skin so their selections definitely change.
- Use Kodi's picture InfoTag for resolution and capture time where available,
  retain compatibility metadata for fields Kodi does not yet expose, and keep
  the fallback compatible with Kodi 21 and Kodi 22.
- Avoid querying `Player.Filenameandpath` when Kodi reports that no media is
  active, preventing the spurious **Kodi is not playing any file** exception
  seen during slideshow/player transitions.
- Log directory listings and picture metadata reads that take at least five
  seconds, making slow SMB/NFS folders and individual files visible in the log
  without failing the scan.
- Update the QNAP instructions to the tested patch-and-GitHub-Actions workflow,
  and make the bundled widget URL convention explicit.
- Bump the generated Estuary revisions to Kodi 21 revision 9 and Kodi 22
  revision 7. Database schema 5, Query Model version 1 and repository add-on
  version 0.2.26 remain unchanged; no catalogue rescan is required.

## 0.3.4 - 2026-07-29

- Fix the Kodi GUI lock that could occur after **Stop scan** by removing
  `Container.Refresh` from both the stop action and the manual scan completion
  path. Scan cancellation now closes its progress dialog and clears shared scan
  state without asking the still-updating Pictures container to refresh itself.
- Keep manual as well as automatic scan progress completely hidden during Live
  TV, TV episodes, movies, music or other playback. Completion, cancellation
  and failure notifications are also suppressed while media is playing.
- Make **Pause scans during media playback** apply when playback starts in the
  middle of an automatic scan, not only when the scheduled scan is about to
  begin. A cancel request is still honoured immediately while the scan waits.
- Recreate the non-modal progress dialog after playback ends, while keeping the
  cross-interpreter **Scan status** data available throughout the hidden or
  paused period.
- Treat progress-dialog creation, update and close failures as non-fatal, catch
  unexpected manual scanner setup/runtime failures, and always close the dialog
  before clearing shared scan state.
- Guard notification and player-state calls during Kodi shutdown, and avoid a
  midnight `Container.Refresh` on unrelated PVR, video or other add-on windows
  when the standard Estuary skin is active.
- Require no catalogue rescan, database migration or Estuary package update;
  database schema 5, Query Model version 1, skin revisions and repository add-on
  version 0.2.26 remain unchanged.

## 0.3.3 - 2026-07-29

- Fix OK/Enter on MyPicsDB home-screen picture widgets by using Kodi's
  `ShowPicture` action instead of allowing dynamic content to route still
  pictures through `VideoPlayer` as one-frame MJPEG/TIFF media.
- Add explicit, escaped widget actions for pictures, videos and album folders,
  with a stable `MyPicsDB3.WidgetPath` property so SMB/NFS paths containing
  spaces, commas, quotes or non-ASCII characters are passed as one argument.
- Keep direct `PlayMedia` behaviour for indexed home videos and open album
  widgets in the Pictures window with normal return navigation.
- Keep automatic scans visually silent during Live TV, TV episodes, movies or
  other media playback. If scanning is allowed to continue, the non-modal
  progress dialog closes while playback is active and returns after playback
  stops; scan state remains available through **Scan status**.
- Bump the generated Estuary revisions, including Kodi 21.3 skin 21.3.8 and
  Kodi 22 beta 1 skin 22.0.0~beta1.6, so installed skin forks receive the new
  widget click actions.
- Require no catalogue rescan or database migration; database schema 5, Query
  Model version 1 and repository add-on version 0.2.26 remain unchanged.

## 0.3.2 - 2026-07-29

- Add a dedicated `WidgetListPosterMyPicsDB` include to the generated Estuary
  fork instead of relying on the movie-poster widget, which does not render
  picture filenames or album names below its artwork.
- Reserve a caption area below every MyPicsDB home-screen thumbnail, using the
  explicit `MyPicsDB3.WidgetLabel` property with `ListItem.Label` as a fallback.
- Show subdued caption text while unfocused and brighter scrolling text while
  focused, without changing Estuary's standard movie, TV or music widgets.
- Switch all MyPicsDB picture rows to the new include and bump the generated
  Estuary package revisions, including Kodi 21.3 skin 21.3.7 and Kodi 22 beta 1
  skin 22.0.0~beta1.5, so existing installations receive the XML change.
- Require no catalogue rescan or database migration; database schema 5, Query
  Model version 1 and repository add-on version 0.2.26 remain unchanged.

## 0.3.1 - 2026-07-29

- Publish each picture filename and album label through both `ListItem.Label` and
  `ListItem.Title`, restoring the subdued text used by Estuary poster widgets
  after poster artwork was added in 0.2.47.
- Keep a `MyPicsDB3.WidgetLabel` list-item property for skin integrations that
  prefer an explicit, stable widget label.
- Prefer common still-image formats such as JPEG, PNG, WebP and TIFF when
  choosing album artwork, before trying RAW/HEIF pictures or a video frame.
- Clear Estuary's remembered horizontal widget position before refreshing
  random selections so a new result set does not reopen with its first tile
  mostly outside the visible row.
- Require no catalogue rescan or schema migration; database schema 5, Query
  Model version 1 and repository add-on version 0.2.26 remain unchanged.

## 0.3.0 - 2026-07-29

- Add **Create smart collection** to the MyPicsDB 3 main menu. The Kodi dialog
  editor builds a validated Query Model without exposing SQL or placing query
  JSON in plug-in URLs.
- Support flat **all criteria** and **any criterion** groups with editable rules
  for text, capture-date range, minimum rating, favorite state, picture source,
  camera, keyword and media type.
- Add result previews showing the matching count and up to ten filenames before
  a collection is saved.
- Add selectable result ordering and a per-collection choice to apply or bypass
  the configured global minimum-rating display policy.
- Store smart collections in the existing schema-5 `saved_searches` table so
  they retain pagination, slideshow support, rename and delete actions, and
  automatically include newly indexed matching media.
- Extend Query Model version 1 with the allowlisted `media_type` field for exact
  picture/video selection. Existing version-1 saved searches remain valid.
- Keep database schema 5 and repository add-on version 0.2.26 unchanged.

## 0.2.49 - 2026-07-29

- Save a local, atomic scan checkpoint after each fully processed folder so an
  interrupted manual or automatic scan can continue from the first unfinished
  folder instead of traversing every enabled source from its root.
- Preserve the original source-scan timestamp and aggregate counters across a
  resumed run, allowing missing-record detection to remain correct after Kodi
  or the add-on service restarts.
- Skip sources that were completed before the interruption and resume the
  pending source with its saved depth-first folder frontier.
- Discard checkpoints older than 24 hours or incompatible with the current
  source list, database identity, extension lists, video option, exclusions or
  metadata settings. This makes settings changes such as adding NEF trigger a
  clean traversal instead of reusing an unsuitable checkpoint.
- Keep incomplete-traversal safety across restarts: if any folder could not be
  listed before the interruption, the resumed source remains `partial` and
  source-wide missing-record marking is still skipped.
- Store checkpoints only in the local Kodi add-on profile, even with a shared
  MySQL/MariaDB catalogue. No database migration is required; schema 5, Query
  Model version 1 and repository add-on version 0.2.26 remain unchanged.

## 0.2.48 - 2026-07-29

- Add **Refresh random selections** to the MyPicsDB 3 main menu. It refreshes
  the active plug-in container and reloads Estuary MyPicsDB 3 so Random
  memories, Random albums and On this day - random request new database rows
  without scanning or changing the catalogue.
- Document how to install Kodi's **Libraw image decoder** for NEF/RAW and
  **HEIF image decoder** for HEIC/HEIF, including when a rescan is and is not
  required.
- Distinguish a user-requested scan cancellation from a scan interrupted by
  Kodi shutdown, add-on update or another service restart in `kodi.log`.
- Document that an interrupted scan restarts source traversal on the next run
  while incremental metadata checks still skip unchanged indexed files.
- Keep database schema 5, Query Model version 1, repository add-on version
  0.2.26 and the 0.2.47 collection-artwork behaviour unchanged.

## 0.2.47 - 2026-07-29

- Carry the catalogue's exact representative `media_type` into album, year,
  month, day and undated collection artwork instead of relying only on the file
  extension. Video-only collections therefore use Kodi's generated-frame
  thumbnail even when the source uses an uncommon or user-added video suffix.
- Expose representative artwork through `thumb`, `icon`, `poster` and
  `landscape` so Estuary home-screen rows such as **Recent albums** do not fall
  back to the add-on camera icon merely because a widget asks for poster art.
- Continue to prefer a real still picture as an album cover when one exists,
  and use a generated video frame only as the fallback for video-only albums.
- Require no database migration or media rescan; existing schema-5 rows already
  contain the media-type information used by the new queries.
- Keep Kodi-owned lazy thumbnail generation, scan control, mixed slideshows and
  repository add-on version 0.2.26 unchanged.

## 0.2.46 - 2026-07-29

- Request video previews through Kodi's native `image://video@...` generated-frame
  loader instead of assigning the video file itself as picture artwork. This
  uses Kodi's existing thumbnail cache and requires no add-on FFmpeg process or
  duplicate thumbnail tree.
- Apply the same generated-frame artwork to video-only album and date-group
  representatives while preserving an explicit image thumbnail when one is
  supplied.
- Leave video `thumb_uri` empty for newly scanned catalogue rows. Existing rows
  remain compatible because the browser replaces a legacy self-referencing video
  thumbnail at display time.
- Keep the original media path, MIME type, direct playback, mixed-slideshow
  behaviour, database schema 5 and repository add-on version 0.2.26 unchanged.
- Document that the first preview can take a few seconds over SMB/NFS and that
  isolated still-picture preview failures remain Kodi texture-cache issues, not
  a reason to generate a second add-on-managed image cache.

## 0.2.45 - 2026-07-29

- Replace **Scan now** with a confirmation-protected **Stop scan** action while
  a manual or automatic scan is active. Cancellation is cooperative and stops
  at the next filesystem, metadata or catalogue checkpoint.
- Publish session-local scan state between Kodi's service and plug-in Python
  interpreters, including scan type, current source, current path and the number
  of discovered media items. Show that information in **Scan status**.
- Give automatic scans the same non-modal Kodi background progress indicator as
  manual scans, with progress updates throttled to avoid excessive GUI work on
  large libraries.
- Log an overlapping scheduled scan as skipped instead of failed when another
  catalogue scan already owns the scan lock.
- Handle malformed legacy `folder` plug-in URLs without an `id` parameter as an
  empty, completed directory request instead of raising `KeyError`.
- Keep NEF/Libraw support, database schema 5, Query Model version 1 and
  repository add-on version 0.2.26 unchanged.

## 0.2.44 - 2026-07-29

- Add Nikon NEF to the default picture-extension list and to still-picture
  slideshow classification. Existing installations using the unchanged legacy
  default are upgraded automatically; custom extension lists remain unchanged.
- Document that Kodi's Libraw image decoder is required to display NEF files.
  Metadata extraction continues through ExifRead, while IPTC extraction remains
  JPEG-only.
- Apply configured album views only while window 10002 (Pictures) is active, no
  modal dialog is open and the current container is not updating. Empty results
  no longer request a view mode.
- Add opt-in debug diagnostics for requested, applied, verified and cancelled
  album-view changes to make intermittent skin timing failures reproducible.
- Keep database schema 5, Query Model version 1 and repository add-on version
  0.2.26 unchanged.

## 0.2.43 - 2026-07-29

- Read IPTCInfo3 fields through indexed access instead of calling the unsupported
  dictionary-style `get()` method, preventing per-JPEG scan failures on Kodi 22.
- Attempt IPTC extraction only for files identified as JPEG. Prefer the JPEG
  signature when the metadata prefix is available, preventing PNG, HEIC and
  other image formats from reaching IPTCInfo3's blind scanner.
- Add regression coverage for IPTCInfo3 objects without `get()` and for skipping
  IPTC materialization on non-JPEG images.
- Keep database schema 5, Query Model version 1, slideshow behaviour and
  repository add-on version 0.2.26 unchanged.

## 0.2.42 - 2026-07-28

- Treat an inconclusive picture-player compatibility check as incompatible
  instead of silently accepting it. This prevents Kodi 21 on Windows from
  building and opening the full mixed playlist after the probe could not prove
  that the expected picture was handled by the picture player.
- Detect any still-picture URI currently opened by `VideoPlayer`, not only the
  original expected probe item. Kodi can advance through several one-frame
  MJPEG images between JSON-RPC polls, so exact-item matching alone can miss the
  failure while the screen visibly flickers.
- Use a new session-property key for compatibility results so a false
  `compatible` value cached by 0.2.41 cannot survive an in-place update.
- Keep picture-only database result sets on picture playlist 2 without applying
  the mixed-media compatibility probe; the conservative fallback is limited to
  lists that actually contain both pictures and videos.
- Keep native picture-only album playback, video playlist 1 for video-only
  results, the slideshow-start guard, database schema 5 and repository add-on
  version 0.2.26 unchanged.

## 0.2.41 - 2026-07-28

- Replace the one-picture compatibility probe with a minimal picture-and-video
  picture playlist. Kodi 21 on Windows can play an image-only picture playlist
  correctly but route every JPEG through `VideoPlayer` as soon as video is also
  present.
- Verify the expected picture again after the complete mixed playlist is opened
  before caching the route as compatible. Clear the list and use the existing
  native album fallback if the real playlist still opens that picture as MJPEG.
- Add a session-local slideshow-start guard so repeated actions cannot append to
  and open Kodi's global playlists concurrently while a slow SMB list is still
  being constructed.
- Keep native picture-only album playback, video playlist 1 for video-only
  results, database schema 5 and repository add-on version 0.2.26 unchanged.

## 0.2.40 - 2026-07-28

- Require the picture-player compatibility probe to report the exact expected
  picture on two consecutive polls; ignore stale picture players left by an
  earlier native slideshow.
- Inspect every active player before deciding and give an exact VideoPlayer
  match precedence, preventing the false-positive probe seen on Kodi 21 for
  Windows where JPEG files then flashed by as one-frame MJPEG videos.
- Probe one picture before constructing the full database playlist and cache
  the result for the current Kodi session. Reuse the native mixed-folder
  fallback immediately after an incompatibility is detected.
- Route video-only album and Videos-node playback through Kodi video playlist 1
  rather than picture playlist 2.
- Stop an existing picture or video player before starting a replacement
  slideshow, reducing overlap between repeated starts.
- Do not start an unsafe cross-folder picture playlist on an incompatible Kodi
  installation; show an explanatory notification instead.
- Keep database schema 5 and repository add-on version 0.2.26 unchanged.

## 0.2.39 - 2026-07-28

- Probe the active Kodi player after starting a mixed picture playlist and
  verify that a known picture is handled by the picture player.
- Detect Kodi installations that instead open the picture probe with
  `VideoPlayer`, where JPEG files are treated as one-frame MJPEG videos and
  advance almost immediately.
- Fall back to Kodi's native recursive slideshow for mixed album trees when
  that player mismatch is observed. Keep the explicit mixed playlist on Kodi
  installations where the picture-player probe succeeds.
- Fall back to a picture-only database playlist for mixed searches and other
  cross-folder result sets that cannot be represented by one native folder
  slideshow, with a visible notification that videos were omitted.
- Keep database schema 5 and repository add-on version 0.2.26 unchanged.

## 0.2.38 - 2026-07-28

- Write the selected slideshow route and privacy-safe media counts at Kodi INFO
  level for every slideshow start, so the active path remains visible even when
  opt-in debug logging is not being captured.
- Add a **Write diagnostic log entry** settings action that records the installed
  version and current Debug logging value in `kodi.log` without opening the
  database.
- Use `InfoTagVideo` setters for video list items on current Kodi versions while
  retaining a compatibility fallback for older test doubles.
- Stop writing the completed video's full URI after mixed-slideshow transitions.
- Keep the working 0.2.37 mixed-playlist behaviour, database schema 5 and
  repository add-on version 0.2.26 unchanged.

## 0.2.37 - 2026-07-27

- Keep Kodi's native recursive slideshow for picture-only album trees, but use
  the bounded MyPicsDB picture playlist when the selected album tree contains
  indexed videos.
- Reuse the scoped mixed-video monitor for mixed album playback so video-to-
  picture transitions are handled only for explicitly started mixed playlists.
- Make the add-on's **Debug logging** setting visible in `kodi.log` without
  requiring Kodi's global debug mode, and add route, media-count, playlist-batch
  and monitor-state diagnostics.
- Keep database schema 5 and repository add-on version 0.2.26 unchanged.

## 0.2.36 - 2026-07-27

- Wait until the requested picture container has remained active long enough for
  Kodi's path-specific view state to begin settling.
- Apply the configured album view synchronously, verify the active view control
  and retry only when Kodi performs a late restore to Shift or another saved view.
- Cancel retries when the user navigates away, preserving the parent menu view.
- Keep widgets, the main menu and database schema 5 unchanged.

## 0.2.35 - 2026-07-27

- Apply the configured album view only after Kodi reports that the requested
  picture container is active.
- Match both the plug-in category and content type before sending
  `Container.SetViewMode`, preventing search and saved-search results from
  changing the parent MyPicsDB 3 menu view.
- Stop using immediate duplicate view-mode commands; time out without touching
  another container when Kodi does not expose the expected result view.
- Keep widgets, the main menu and database schema 5 unchanged.

## 0.2.34 - 2026-07-27

- Add **Saved searches** to the add-on menu and allow the current global text
  search to be saved, reopened with normal pagination and slideshow support,
  renamed or deleted.
- Add database schema 5 with a portable `saved_searches` table for SQLite and
  MySQL/MariaDB. Store canonical Query Model JSON and its explicit version, not
  raw SQL or query JSON in saved-view plugin URLs.
- Revalidate the stored query version, JSON structure, fields and operators
  every time a saved search is opened.

## 0.2.33 - 2026-07-27

- Build large database-backed slideshows in bounded JSON-RPC batches instead of
  sending up to 5,000 media paths in one oversized `Playlist.Add` request.
- Drop empty and duplicate media URIs while preserving catalogue order and
  recalculate **Play slideshow from here** against the cleaned playlist.
- Keep the mixed-video monitor inactive while the playlist is being assembled,
  arm it only after playback starts successfully, and clear a partially built
  playlist when Kodi rejects an add or open request.
- Keep native recursive album slideshows unchanged and retain database schema 4.

## 0.2.32 - 2026-07-27

- Prefer the newest eligible picture as artwork for recent, random and folder
  album rows, even when a newer video exists in the same album.
- Keep the newest media timestamps for recent-album ordering instead of letting
  the picture-first artwork choice change album recency.
- Fall back to video artwork for albums that contain no pictures.
- Keep database schema 4 and avoid modifying original media.

## 0.2.31 - 2026-07-27

- Treat a directory-listing failure as an incomplete source traversal and skip
  missing-file and missing-folder marking for that source.
- Keep previously indexed media active when a listed file temporarily fails
  stat or metadata access.
- Record incomplete scans with the explicit `partial` status while continuing
  to index media from folders that were read successfully.
- Mark genuine deletions on the next complete scan without changing database
  schema 4.

## 0.2.30 - 2026-07-27

- Treat a migration lock held by another MyPicsDB 3 process as a temporary
  database-busy state instead of exposing a plug-in failure.
- Show a clear retry message for interactive browser requests while allowing
  widgets to return a successful, uncached empty directory without a popup.
- Let the background service wait briefly and retry database initialization,
  while still stopping promptly when Kodi is shutting down.
- Keep other migration and database failures visible instead of hiding them
  behind the temporary-busy handling.

## 0.2.29 - 2026-07-27

- Run the mixed-slideshow video monitor only while an explicitly started
  database-backed MyPicsDB 3 playlist contains video.
- Keep native recursive album slideshows free from MyPicsDB 3 JSON-RPC polling
  and automatic `Player.GoTo` calls.
- Clear stale mixed-slideshow session state after playback stops, while allowing
  a short startup grace period before Kodi reports an active player.

## 0.2.28 - 2026-07-27

- Use Kodi's native recursive folder slideshow when starting a slideshow from an
  album, allowing Kodi to handle picture/video transitions and consecutive
  videos directly.
- Keep the database-backed mixed playlist for result sets that can span
  unrelated folders, such as searches and other catalogue views.
- Avoid the rapid MJPEG playback and difficult-to-stop sequence seen when the
  custom mixed-slideshow video monitor was disabled during diagnosis.

## 0.2.27 - 2026-07-26

- Keep the repository add-on on its own version instead of bumping it for every
  MyPicsDB 3 plug-in release, preventing Kodi from replacing the repository
  while it is being used for an update check.
- Reuse the exact previously published repository archive when its version and
  contents are unchanged, and fail the Pages build if repository files change
  without a version bump.
- Do not attach an unchanged repository zip to plug-in-only GitHub releases.

## 0.2.26 - 2026-07-26

- Bump the Estuary MyPicsDB 3 skin package revisions so Kodi installs the
  home-screen XML added in 0.2.24.
- Ensure **On this day** and **On this day - random** can both appear when both
  rows are enabled. Existing installations update from skin 21.3.5 to 21.3.6
  on Kodi 21.3.

## 0.2.25 - 2026-07-26

- Treat Kodi's early `System.OnQuit` and `System.OnRestart` notifications as
  immediate cancellation signals for the service and manual scans.
- Reuse the shutdown-aware monitor during in-place add-on update retries so
  service initialization cannot continue after Kodi has begun exiting.
- Recheck shutdown state immediately before starting an automatic scan and
  after a cancelled scan, preventing delayed background work during exit.

## 0.2.24 - 2026-07-26

- Restored the chronological **On this day** home-screen row as a separate choice.
- Added **On this day - random** as an independent home-screen row so either or both can be enabled.
- Explicitly shuffles random On this day results before returning them.
- Keeps nine visible home rows while exposing ten configurable view types.

## 0.2.23 - 2026-07-26

- Keep the chronological **On this day** browser and add a random variant that
  samples matching dates across all earlier years; the Estuary home row now
  uses the random variant without changing saved row settings.
- Apply the configured default album view consistently to interactive picture,
  album, date, camera and keyword browsers while leaving widget layouts to the
  skin.
- Run both full and selected-source manual scans with Kodi's non-modal
  background progress indicator, including pause/resume during playback.
- Advance the picture playlist automatically after an indexed video finishes
  in a mixed slideshow, avoiding the repeated black-screen image-load loop.

## 0.2.22 - 2026-07-25

- Add optional indexing for common home-video formats alongside pictures.
- Add schema 4 with a backward-compatible `pictures.media_type` column and
  index for SQLite and MySQL/MariaDB; existing rows migrate as pictures.
- Add a dedicated Videos browser node and mark video list items playable in
  Kodi while keeping picture-only metadata views unchanged.
- Add database-backed mixed picture/video slideshows using Kodi picture
  playlist 2, including filtered result order and recursive album playback.
- Let minimum-picture-rating policies include videos without assigning fake
  ratings to video records.
- Document video setup, current metadata limitations and cleanup behaviour.
- Reconcile a lowered schema marker with already-recorded later migrations without
  inserting duplicate MySQL/MariaDB migration-history rows.

## 0.2.21 - 2026-07-25

- Always exclude Synology `@eaDir` metadata trees, including directory names
  that end with `@eaDir`, even when an older profile has no matching custom
  exclusion setting.
- Add a General-settings editor for choosing which catalogue browsing nodes are
  visible in the MyPicsDB 3 add-on menu.
- Keep Search, Picture sources, Scan now, Scan status and Settings available so
  catalogue management cannot be hidden accidentally.

## 0.2.20 - 2026-07-25

- Queue the date-sensitive home-screen refresh instead of reloading the skin
  immediately at midnight.
- Wait 60 seconds after the date changes and retry while Kodi is scanning a
  library, playing media, showing a modal dialog, running the screen saver or
  using DPMS.
- Defer the custom Estuary reload until the Home window is active, while other
  skins continue to use a normal container refresh.
- Keep the refresh request pending after transient GUI errors and log when it is
  deferred or completed.

## 0.2.19 - 2026-07-24

- Add skin-independent global search from the MyPicsDB 3 main menu.
- Normalize Unicode search text with NFKC and case folding, retain Swedish
  letters, and require every entered word to match the same picture.
- Search filename, caption, keywords, URI/path parts, camera and stored
  location fields through Query Model version 1 with bound SQL parameters.
- Raise the catalogue to schema 3 with normalized per-picture search documents,
  a retry-safe batch backfill and ongoing scanner maintenance.
- Preserve minimum-rating policy, temporary all-picture browsing and pagination
  across search results on SQLite and MySQL/MariaDB.

## 0.2.18 - 2026-07-24

- Add Query Model version 1 as the shared foundation for future search, smart
  filters, saved views and smart collections without changing database schema 2.
- Strictly validate nested all/any/not groups, bounded values, registered fields,
  operators, scopes and stable sort definitions.
- Compile only trusted SQL fragments with bound parameters for SQLite and
  MySQL/MariaDB, including catalogue page and count execution.
- Add deterministic canonical JSON, minimum-rating-policy control and backend
  parity coverage.

## 0.2.17 - 2026-07-24

- Add **Minimum picture rating** to the Kodi context menu throughout MyPicsDB 3.
- Remove the duplicate **Save current view as album default** entry inside albums.

## 0.2.16 - 2026-07-24

- Add a local minimum-rating display policy without changing database schema 2.
- Distinguish pictures without a stored rating from pictures with explicit rating 0.
- Apply the policy consistently to picture lists, widgets, album counts and artwork,
  date groups, cameras and keywords while leaving scans and stored metadata unchanged.
- Show the active policy in Kodi and allow a temporary all-pictures browsing session.
- Add SQLite coverage and an opt-in MySQL/MariaDB parity test.

## 0.2.15 - 2026-07-23

- Add schema version 2 with an idempotent year-first date-browsing index for
  SQLite and MySQL/MariaDB.
- Change the Years browser to drill down through year, month and day before
  showing pictures.
- Add a No date folder for pictures without an embedded capture date.
- Preserve route parameters on paginated date, camera and keyword views.
- Extend fresh-database, schema-1 upgrade, catalogue, Kodi UI and MariaDB tests.

## 0.2.14 - 2026-07-23

- Align the add-on, repository and core package release versions and update the
  published release notes for the migration foundation.
- Make source verification fail when the add-on, repository and Python package
  versions differ.
- Extend the MariaDB integration test to bootstrap migration history for an
  existing schema-1 catalogue, preserve its data and verify an idempotent rerun.

## 0.2.13 - 2026-07-23

- Add a versioned, checksummed migration runner while retaining schema version 1.
- Register existing schema-1 databases as a baseline only after creating an
  atomic, integrity-checked SQLite backup.
- Refuse newer database schemas before structural writes and coordinate schema
  work with catalogue scans through mutually exclusive locks.
- Add MySQL/MariaDB migration preflight plus read-only current and legacy schema
  inspection tools.
- Document migration design, backup and recovery, and the requirements for the
  first real schema-2 change.

## 0.2.12 - 2026-07-22

- Let the Estuary MyPicsDB 3 home rows load the configured number of items
  instead of always stopping at 15.
- Keep 15 as the default and cap the home-row setting at 50 to limit database,
  artwork and memory overhead.
- Parameterize Estuary's poster widget limit while preserving the standard
  Estuary limit of 15 for every non-MyPicsDB widget.

## 0.2.11 - 2026-07-21

- Stop full foreground scans when Kodi requests shutdown, rather than checking
  only the progress dialog's Cancel button.
- Avoid progress updates, notifications and container refreshes after Kodi has
  begun shutting down for both foreground and selected-source scans.
- Check for cancellation before and after Kodi VFS directory, stat, stream and
  metadata-materialisation operations so a scan stops as soon as a blocked SMB
  call returns.
- Replace the six-hour scan lock with a renewable 30-minute lock. Active scans
  refresh it every minute, while expired locks are never revived.

## 0.2.10 - 2026-07-21

- Replace the failing programmatic home-screen editor with a packaged XML dialog
  and close add-on settings before opening it.
- Fall back to standard Kodi selection dialogs if the visual editor cannot load,
  instead of showing a fatal add-on error.
- Add **Save current view as album default** to the Pictures side menu in the
  generated Estuary MyPicsDB 3 skin and to every item inside an album.
- Bump the patched Estuary skin revisions so Kodi receives the side-menu change.

## 0.2.9 - 2026-07-21

- Replace the nested home-screen configuration menus with a visual nine-row
  editor that shows an On/Off control and move-up/move-down buttons for every
  view.
- Register **Save current view as album default** as a Kodi context-menu item
  while browsing MyPicsDB 3 albums.
- Fall back to a view selector when Kodi cannot report the currently focused
  album view.

## 0.2.8 - 2026-07-21

- Replace the nine separate home-screen row selectors with one ordered editor
  where every view can be enabled, disabled, moved up or moved down.
- Preserve existing home-screen choices and continue writing the legacy row
  settings used by Estuary MyPicsDB 3.
- Add a configurable default view for albums under General settings.
- Add an album context-menu action that saves the currently active view as the
  new album default.

## 0.2.7 - 2026-07-20

- Add independent repository channels for Kodi 21 Omega and Kodi 22 Piers.
- Check the official Kodi releases daily and update pinned Estuary sources only
  after the patch, unit tests, package build and Kodi add-on checker succeed.
- Retain up to five patched Estuary archives per Kodi channel while advertising
  only the newest compatible version to Kodi.
- Preserve the old repository root long enough for installed 0.2.6 repository
  add-ons to update to the new multi-channel configuration.
- Keep the previously published repository history in the generated `repo-data`
  branch used by GitHub Pages.

## 0.2.6 - 2026-07-19

- Hide Kodi's virtual **Picture add-ons** entry from MyPicsDB 3 picture sources.
- Remove any previously stored copy of that virtual source automatically.

## 0.2.5 - 2026-07-19

- Refresh date-sensitive views automatically after the local date changes so
  **On this day** does not remain on the previous day.
- Ask before removing MyPicsDB 3 sources that no longer exist in Kodi, and keep
  declined removals available for the next manual source refresh.
- Add quick installation and setup instructions to the README.

## 0.2.4 - 2026-07-17

- Run **Scan selected source** with Kodi's non-modal background progress indicator.
- Pause selected-source scans during media playback and resume them automatically.
- Keep **Scan now** as the existing foreground, user-cancellable scan.

## 0.2.3

- Keep nine configurable home-screen positions but enable only the first six by default.
- Default Row 7 through Row 9 to None so new installations start with a compact Pictures screen.
- Document safe replacement of a disposable test source with the real picture library.
- Clarify that rows set to None and rows without matching results are not shown.

## 0.2.2

- Fixed missing labels for the General item-limit settings.
- Home screen Row 1 through Row 9 now show their selected or default content.
- Normalized the English gettext catalogue.
- Published skin artwork and screenshots at the paths declared in addon.xml.
- Added a short retry for the transient Kodi add-on registration race during updates.
- Updated Estuary MyPicsDB 3 to 21.3.3.

## 0.2.1 - 2026-07-17

- Show visible headings for all MyPicsDB 3 Pictures home-screen rows.
- Add nine configurable row positions and a Media sources visibility setting.
- Add Favorites, Rated pictures and Geotagged pictures as home-screen choices.
- Document row configuration and global Kodi repository-update diagnostics.
- Bump the generated Estuary MyPicsDB 3 skin to 21.3.2.

## 0.2.0 - 2026-07-17

- Add the separately installed `skin.estuary.mypicsdb3` skin for Kodi 21 Omega.
- Build the skin reproducibly from Kodi's official `21.3-Omega` Estuary source.
- Add Pictures home-screen rows for media sources, recent pictures, random memories, albums and On this day.
- Keep standard Estuary installed and untouched so Kodi updates cannot overwrite the custom skin.
- Publish the generated skin through the MyPicsDB 3 repository with its own independent version.
- Document automatic scan intervals and installation, update and fallback procedures.
- Update GitHub Actions to current Node.js 24-compatible action releases.

## 0.1.1 - 2026-07-17

- Fix source activation from Picture sources.
- Build every plugin link from the add-on root instead of the current nested route.
- Show Enable source and Disable source actions in the source context menu.
- Add regression tests for nested plugin URLs and source activation items.

## 0.1.0 - 2026-07-17

- Initial Kodi 21 Omega release candidate.
- SQLite catalogue with WAL mode and incremental scanning.
- Optional shared MySQL/MariaDB catalogue through PyMySQL.
- EXIF, basic XMP, IPTC, GPS, camera, rating and keyword indexing.
- Source management based on Kodi picture sources.
- Background and manual scanning with unavailable-source protection.
- Widget endpoints for recent, random, folder, date, camera and tag views.
- Favorites, rated pictures and geotagged picture views.
- Repository builder, GitHub Actions and Estuary integration documentation.
