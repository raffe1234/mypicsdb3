# Plug-in requests, browsing and widgets

This guide follows a one-shot Kodi plug-in request from URL to rendered
directory items. It covers normal browser pages and read-only widget providers.

## Main path

```text
plugin://plugin.image.mypicsdb3/<route>?<params>
→ plugin.image.mypicsdb3/addon.py
→ entrypoints.plugin_main(argv)
→ router.parse_request(base_url, query)
→ KodiContext
→ Runtime
   → DatabaseEngine
   → Catalog.initialize()
   → KodiFilesystem
→ PluginUI.dispatch(Request)
→ catalogue getter or action
→ Kodi ListItems
→ PluginUI.finish()
→ xbmcplugin.endOfDirectory()
```

## Files and responsibilities

| File | Responsibility |
| --- | --- |
| `addon.py` | Adds the package path and calls `plugin_main()` |
| `entrypoints.py` | Parses Kodi arguments, handles migration-busy startup and creates the UI |
| `router.py` | Converts URL path and query string into `Request(route, params)` |
| `runtime.py` | Assembles Kodi context, database, catalogue and filesystem |
| `views.py` | Dispatches routes and creates Kodi directory/action items |
| `db/catalog.py` | Performs read models, pagination and state changes |
| `kodi.py` | Wraps settings, localization, notifications and shared Kodi state |
| `view_mode.py`, `album_view.py` | Guard and remember Kodi picture view choices |

## Example: Recently taken

```text
route: recent-taken
→ PluginUI.dispatch()
→ PluginUI.pictures(route, Catalog.recent_taken, params, category)
→ Catalog.recent_taken(limit, offset)
→ Catalog._pictures(... ORDER BY taken date ...)
→ rows returned to PluginUI
→ PluginUI._media_item(row)
→ next-page item when required
→ PluginUI.finish(content="images")
```

The same route can be opened interactively or used as a widget provider. Widget
parameters control limits and caching behaviour, but the route still reads only
indexed catalogue rows.

## Route groups

`PluginUI.dispatch()` is the central route table. Current groups include:

- root and configuration actions;
- global search and saved searches;
- source and folder browsing;
- recent, random and on-this-day views;
- videos, years, months and days;
- cameras, keywords, favorites, ratings and geotagged media;
- status and action routes.

When adding a route, keep URL construction inside `PluginUI.url()` or existing
helpers so parameters are encoded consistently.

## List-item construction

`PluginUI` separates:

- folder items that open another directory route;
- action items that run a command;
- picture/video media items;
- album representative items;
- next-page items.

Kodi metadata and artwork differ for pictures, videos and albums. Do not assume
that a row from the historical `pictures` table is always a still image.

## Rating display policy

The configured minimum rating is a display policy, not a destructive filter on
the stored catalogue. `PluginUI.dispatch()` sets the effective policy on the
catalogue for the current request. Some routes can temporarily request all
pictures while preserving the configured default for later calls.

Changes here should normally inspect:

- `rating_policy.py`;
- `tests/test_rating_policy.py`;
- route and UI tests that use `rating` or `show_all` parameters.

## Widgets

Stable widget URLs are documented in `docs/WIDGET_URLS.md`. Important rules:

1. Widget routes read the catalogue only.
2. A widget route must never start or wait for a source scan.
3. Home widgets can use a separate item limit from normal browser pages.
4. Random rows should refresh only when explicitly invalidated, not on every
   unrelated navigation event.
5. Widget labels and artwork must remain compatible with the skin contract.

## Adding or changing a route

A normal route change touches this sequence:

1. Add or change the route branch in `PluginUI.dispatch()`.
2. Reuse a catalogue method or add a focused one in `db/catalog.py`.
3. Use existing item and finish helpers.
4. Add URL constants to `docs/WIDGET_URLS.md` when the route is public to skins.
5. Add a localized label when visible to users.
6. Add or update tests.

Useful tests include:

- `tests/test_utils_router.py`;
- `tests/test_kodi_ui_smoke.py`;
- `tests/test_catalog.py`;
- `tests/test_view_mode.py`;
- `tests/test_context_menu.py`;
- widget and Estuary tests for provider changes.

## Invariants

- Unknown or malformed routes should fail safely and finish Kodi directory
  requests where required.
- Temporary migration-lock contention must not become a raw Kodi plug-in error.
- Widget calls are read-only with respect to media sources.
- Pagination must preserve the route's filter parameters.
- Kodi view changes must target the active stable Pictures container only.
- New Kodi API calls should remain in the Kodi-facing layer or an adapter.
