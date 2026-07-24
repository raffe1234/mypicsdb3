# Changelog

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
