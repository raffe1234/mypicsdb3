# Slideshows and the background service

This guide covers picture-only, video-only and mixed-media playback plus the
long-running Kodi service that supports it.

## Slideshow choices

The UI selects the safest playback path for the result set:

```text
picture-only album tree in one compatible folder structure
→ Kodi native recursive picture slideshow

video-only result
→ Kodi video playlist

mixed or cross-folder database result
→ bounded database-backed playlist
→ picture-player compatibility probe when needed
→ service monitor advances after video items

unsupported Kodi picture-playlist behaviour
→ conservative fallback or explanatory notification
```

## Main files

| File | Responsibility |
| --- | --- |
| `views.py` | Chooses slideshow type, obtains rows and starts/falls back safely |
| `slideshow.py` | Kodi JSON-RPC playlist operations and player compatibility probe |
| `service_loop.py` | Mixed-slideshow video monitor and general service scheduling |
| `kodi.py` | Shared start locks, session compatibility state and playback helpers |
| `db/catalog.py` | Folder-tree and query result rows used for playlists |

## UI start flow

```text
context menu or action route
→ PluginUI.action()
→ PluginUI._start_slideshow(params)
→ acquire slideshow-start token in Kodi shared state
→ determine source/result and media composition
→ native slideshow OR database playlist helper
→ release start token
```

The start token prevents overlapping plug-in calls from starting multiple
slideshows at the same time.

## Database-backed playlist flow

```text
catalogue rows
→ split/identify picture and video URIs
→ remove empty or duplicate items
→ stop relevant previous media players
→ probe picture playlist compatibility when unknown
→ clear Kodi playlist
→ add bounded batches
→ open the correct player
→ publish mixed-slideshow active state
```

Playlist additions are batched to avoid oversized JSON-RPC requests. The UI
also caps large mixed results.

## Why the picture-player probe exists

Kodi builds do not all treat picture playlist 2 identically. Some route a still
picture through `VideoPlayer`. MyPicsDB 3 probes one known expected picture and
checks active players repeatedly.

The probe is deliberately conservative:

- it matches the exact expected URI;
- an exact or picture-looking video-player match takes precedence;
- a picture match must be confirmed more than once;
- stale unrelated players are ignored;
- the result can be cached only for the current Kodi session.

Do not simplify the probe to "any active picture player" or one timing-dependent
poll.

## Mixed-slideshow monitor

The service's `MixedSlideshowVideoMonitor` watches shared mixed-session state and
active players. After a video item finishes, it advances the compatible picture
playlist when appropriate. It must ignore unrelated playback and clear stale
session state safely.

## Other service responsibilities

`ServiceLoop` also:

- retries initialization while another process owns the migration lock;
- synchronizes Kodi picture sources;
- schedules automatic scans;
- defers scans during playback when configured;
- publishes progress and responds to cancellation;
- notices a local date change and refreshes date-sensitive rows when Kodi is
  idle;
- notices home-widget limit changes and invalidates MyPicsDB 3 rows;
- schedules the separate random home-row generation without invalidating
  non-random providers;
- exits promptly when Kodi requests abort.

A service change should be reviewed for both steady-state loops and shutdown
paths.

## Shared Kodi state

`KodiContext` stores short-lived coordination values in Kodi window properties,
including scan status, cancellation, slideshow-start ownership and session
compatibility. These properties coordinate processes inside the same Kodi
instance; they are not a substitute for catalogue locks shared across devices.

## Useful tests

- `tests/test_slideshow.py`;
- `tests/test_mixed_slideshow_monitor.py`;
- `tests/test_kodi_slideshow_state.py`;
- `tests/test_service_shutdown.py`;
- `tests/test_service_startup_retry.py`;
- `tests/test_service_date_refresh.py`;
- `tests/test_service_scan_progress.py`;
- `tests/test_kodi_scan_state.py`.

## Invariants

- Never interfere with unrelated picture, video, TV or movie playback.
- Preserve the exact-item and repeated-confirmation compatibility checks.
- Keep playlist sizes and JSON-RPC batches bounded.
- Release slideshow-start ownership on every exit path.
- Service loops must remain responsive to Kodi abort requests.
- Playback-aware scans and date refreshes must defer rather than fight the UI.
- Use conservative notification/fallback behaviour when the Kodi player cannot
  be proven compatible.
