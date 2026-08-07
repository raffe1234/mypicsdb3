# Manual collections

This guide follows a named manual collection from schema migration through Kodi
browsing and slideshow playback. Manual collections are user-selected media-ID
lists. They are deliberately separate from saved smart collections, whose
contents are recalculated from validated Query Model JSON.

## Data flow

```text
picture or home-video context menu
→ Add to collection
→ choose an existing collection or create a new one
→ Catalog.add_picture_to_collection()
→ append collection_items.position

Estuary full-screen still → I / Info → Add current picture to collection
→ KodiContext.current_slideshow_picture_uri()
→ Catalog.picture_for_uri() exact available `media_type=picture` match
→ same collection picker and Catalog.add_picture_to_collection() path
→ no write if the current item cannot be resolved safely

Collections main-menu entry
→ Catalog.list_collections()
→ open collection route
→ Catalog.pictures_in_collection()
→ skip missing/policy-hidden media
→ render in stored order with Default album view

item context menu → Move up/down/top/bottom
→ Catalog.move_picture_in_collection()
→ rewrite compact 1-based positions in one transaction
→ invalidate Home widgets and refresh the collection

Home-screen editor → Add collection → Add manual collection
→ persist collection ID in home_layout_v2 and the selected slot
→ Estuary home-collection?slot=N provider
→ resolve current collection and render its bounded ordered media

Play collection slideshow / Play slideshow from here
→ release any direct plug-in playback handle
→ collection slideshow scope
→ fetch up to the normal bounded playlist limit in stored order
→ picture-only: internal ordered plug-in directory → Kodi native SlideShow
→ video-only: Kodi video playlist
→ mixed: choose native picture slideshow or video playlist

optional collection context action → Assign music playlist
→ schema-7 mapping by manual collection ID
→ explicit Play picture slideshow with music
→ same ordered picture-only directory + service-owned music cleanup
```

## Files and responsibilities

| File | Responsibility |
| --- | --- |
| `static_collections.py` | Collection-name and stored-record validation |
| `db/migration_steps/v0006_static_collections.py` | Schema-5-to-6 migration |
| `db/schema.py` | Fresh SQLite and MySQL/MariaDB schema |
| `db/catalog.py` | Collection CRUD, duplicate prevention, ordered membership, reordering and reads |
| `preferences.py`, `home_layout_editor.py` | Manual collection Home-row persistence and editing |
| `views.py` | Main-menu route, dialogs, context actions, full-screen Picture Info action, Home provider, browsing and slideshow scope |
| `kodi.py` | Kodi state helpers, including the current native slideshow picture URI |
| `contrib/estuary/`, `tools/estuary_skin.py` | Generated Estuary Home rows and focusable Picture Info action |
| `resources/language/resource.language.en_gb/strings.po` | User-facing collection text |
| `music_playlists.py`, `music_slideshow.py` | Optional playlist assignment and music playback helpers |
| `db/migration_steps/v0007_collection_music.py` | Optional schema-7 music mapping |

## Schema and ordering

`collections` stores the name and timestamps. `collection_items` stores one
media reference per collection, an explicit positive `position` and its add
time. The `(collection_id, picture_id)` primary key prevents duplicates. The
`(collection_id, position)` unique constraint keeps the explicit order
deterministic.

New items append at `MAX(position) + 1`. Move and remove operations rewrite the
remaining IDs to compact 1-based positions. The rewrite preserves each
membership timestamp, replaces the collection rows inside the current transaction
and inserts the final positive positions, so the unique
`(collection_id, position)` constraint is never violated and MySQL `INT
UNSIGNED` remains supported. Pictures and videos remain in one shared order.

## Missing media and rating policy

A collection keeps catalogue references, not copies of source files. Browsing
joins current `pictures`, `folders` and `sources` rows and requires
`p.is_missing=0`. Temporarily unavailable items therefore disappear from the
view without causing an exception. If missing-record cleanup later deletes a
picture row, the foreign key removes its collection membership automatically.

The normal minimum-rating display policy also applies. `list_collections()`
reports the count and artwork of currently visible media, while retaining the
total membership count internally. The temporary all-pictures browsing override
is forwarded in collection routes and slideshow actions.

## CRUD behaviour

- Creating and renaming require a non-empty unique name of at most 191
  characters.
- Adding an already-present item is a no-op and returns `False`.
- Only indexed, currently non-missing media can be added.
- The full-screen Picture Info route additionally requires one exact URI match
  whose catalogue row is explicitly a still picture; otherwise it fails closed.
- Removing an item deletes only its membership row and compacts positions.
- Context actions move an item one step or directly to either edge.
- Deleting a collection cascades membership rows but never deletes a `pictures`
  row or source file.
- Pictures and videos may coexist in the same collection.

## Slideshow behaviour

Collection videos reuse Kodi's video playlist. Collection pictures do not use
JSON-RPC picture playlist 2: Kodi 21 on Windows can accept that playlist but
reopen its JPEG through VideoPlayer in a tight loop. Instead, MyPicsDB exposes a
hidden plug-in directory containing only the selected still pictures and starts
Kodi's native ``SlideShow`` built-in on that directory. Zero-padded internal
labels retain stored collection order when Kodi sorts directory results, while
normal picture metadata retains the visible filename. ``beginslide`` preserves
**Play slideshow from here**. Empty URIs, duplicate paths and videos are filtered
from the native picture directory.

Slideshow command rows deliberately avoid a VideoInfoTag. When Kodi nevertheless
opens a directly selected command as a media request, the action marks that
request unresolved before opening the actual playlist. ``RunPlugin`` context
commands use a negative handle and are not resolved.

An optional schema-7 playlist assignment adds **Play picture slideshow with
music**. This action filters out videos and starts the same native ordered
picture directory while Kodi music playlist 0 plays. Version 0.6.0 deliberately
keeps videos on their normal separate playlist; it does not pause, fade or
resume music around video items. The background service stops music after the
picture slideshow only while the Kodi music queue still matches the queue that
MyPicsDB started. See [Collection music playlists](COLLECTION_MUSIC.md).

## Tests

- `tests/test_static_collections.py` validates names and stored records;
- `tests/test_catalog.py` covers CRUD, duplicates, order, missing media, rating
  policy, mixed media and deletion safety;
- `tests/test_migrations.py` covers schema-5-to-6, schema-6-to-7 and fresh schema 7;
- `tests/test_kodi_ui_smoke.py` covers routes, Home providers, context actions,
  full-screen collection guardrails and row synchronization;
- `tests/test_kodi_date_refresh.py` covers current-slideshow URI resolution;
- `tests/test_estuary_skin.py` covers Picture Info insertion and keyboard/remote
  focus navigation in the generated Estuary fork;
- `tests/test_preferences.py` and `tests/test_home_layout_editor.py` cover manual Home rows;
- `tests/test_mysql_integration.py` contains an opt-in backend round trip.

## Invariants

- Manual and smart collections remain different concepts and tables.
- Source files are never copied, moved, edited or deleted by collection actions.
- Full-screen collection adds reuse the same membership writer as list-context
  adds and never modify Kodi's native slideshow or keymap.
- One media row occurs at most once in a collection.
- Stored order is stable, compact and editable across browsing pages, Home rows
  and each selected playback type.
- A deleted manual collection cannot leave an active Home provider behind.
- Missing or policy-hidden media never crashes collection browsing.
- SQLite and MySQL/MariaDB expose equivalent collection behaviour.
- Schema migrations 6 and 7 do not require a catalogue rescan.
- Optional music remains picture-only and never changes collection ordering.
