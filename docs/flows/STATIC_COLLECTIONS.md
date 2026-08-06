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

Collections main-menu entry
→ Catalog.list_collections()
→ open collection route
→ Catalog.pictures_in_collection()
→ skip missing/policy-hidden media
→ render in stored order with Default album view

Play collection slideshow / Play slideshow from here
→ collection slideshow scope
→ fetch up to the normal bounded playlist limit in stored order
→ existing picture-only, video-only or mixed playback path
```

## Files and responsibilities

| File | Responsibility |
| --- | --- |
| `static_collections.py` | Collection-name and stored-record validation |
| `db/migration_steps/v0006_static_collections.py` | Schema-5-to-6 migration |
| `db/schema.py` | Fresh SQLite and MySQL/MariaDB schema |
| `db/catalog.py` | Collection CRUD, duplicate prevention, ordered membership and reads |
| `views.py` | Main-menu route, dialogs, context actions, browsing and slideshow scope |
| `resources/language/resource.language.en_gb/strings.po` | User-facing collection text |

## Schema and ordering

`collections` stores the name and timestamps. `collection_items` stores one
media reference per collection, an explicit positive `position` and its add
time. The `(collection_id, picture_id)` primary key prevents duplicates. The
`(collection_id, position)` unique constraint makes order deterministic and
prepares the model for a later reordering UI.

The first implementation appends at `MAX(position) + 1`. Removing an item may
leave a gap; gaps are harmless because reads sort by `position, picture_id`.
Compaction and manual up/down movement are intentionally deferred.

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
- Removing an item deletes only its membership row.
- Deleting a collection cascades membership rows but never deletes a `pictures`
  row or source file.
- Pictures and videos may coexist in the same collection.

## Slideshow behaviour

Collections reuse the existing database slideshow implementation. Saved order
is preserved for picture-only, video-only and mixed collections. The common
playlist bound still applies, empty URIs and duplicates are filtered defensively,
and mixed playback remains coordinated with the background service.

## Tests

- `tests/test_static_collections.py` validates names and stored records;
- `tests/test_catalog.py` covers CRUD, duplicates, order, missing media, rating
  policy, mixed media and deletion safety;
- `tests/test_migrations.py` covers schema-5-to-6 upgrade and fresh schema 6;
- `tests/test_kodi_ui_smoke.py` covers routes and context actions;
- `tests/test_mysql_integration.py` contains an opt-in backend round trip.

## Invariants

- Manual and smart collections remain different concepts and tables.
- Source files are never copied, moved, edited or deleted by collection actions.
- One media row occurs at most once in a collection.
- Stored order is stable across browsing pages and slideshow creation.
- Missing or policy-hidden media never crashes collection browsing.
- SQLite and MySQL/MariaDB expose equivalent collection behaviour.
- Schema migration does not require a catalogue rescan.
