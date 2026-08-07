# MyPicsDB 3 Screensaver flow

The screensaver is a separate Kodi add-on, `screensaver.mypicsdb3`, shipped from
the same repository as `plugin.image.mypicsdb3`. The separation lets Kodi manage
it as a normal **Look and feel > Screensaver** add-on while the database and
query rules remain owned by MyPicsDB 3.

## Source selection

`RunScript(screensaver.mypicsdb3,choose-source)` opens a picker containing the
current manual collections and saved smart collections. The selected type, id
and display name are stored in the screensaver add-on's own settings. There is no
default collection and no implicit all-library fallback.

## Read-only provider

The screensaver imports the MyPicsDB 3 core library from the installed picture
add-on and reads that add-on's database configuration. It constructs
`ScreensaverReadOnlyProvider` directly instead of `Runtime`, so it does not call
`Catalog.initialize()`, migrations, Home-state publication or scanning code.

SQLite uses `DatabaseEngine.connect_readonly()`. MySQL/MariaDB uses the configured
account but the screensaver code issues only SELECT statements.

For manual collections, still pictures are selected from `collection_items`. For
saved smart collections, the stored Query Model is parsed and compiled through
the normal trusted query compiler. Both paths filter missing rows and videos.
The local minimum-rating policy remains active.

## Random and bounded selection

Every screensaver session is capped at 1,000 pictures. Random mode uses the
existing per-picture `random_key`: one random pivot reads forward to the limit
and, when necessary, wraps once to the start of the key space. This avoids
`ORDER BY RANDOM()`/`RAND()` across a large catalogue.

## Display lifecycle

The Python screensaver creates a full-screen `WindowDialog` with one aspect-ratio
preserving image control. `xbmc.Monitor.onScreensaverDeactivated()` and the Kodi
abort flag both stop the loop quickly. A direct user action on the dialog also
closes it. Optional filename text is drawn by a separate label control.

If the database is unavailable, the selected collection was deleted, or no still
pictures remain, a short text fallback is shown. The screensaver never scans or
modifies original media.
