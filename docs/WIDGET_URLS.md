# Widget URL reference

All widget views are read-only and never start a scan. They use the local
**Minimum picture rating** setting, just like the interactive browser views.

| View | URL |
|---|---|
| Recently taken | `plugin://plugin.image.mypicsdb3/recent-taken?widget=1&limit=15` |
| Recently discovered | `plugin://plugin.image.mypicsdb3/recent-added?widget=1&limit=15` |
| Random memories | `plugin://plugin.image.mypicsdb3/random?widget=1&limit=15` |
| Recent albums | `plugin://plugin.image.mypicsdb3/recent-folders?widget=1&limit=15` |
| Random albums | `plugin://plugin.image.mypicsdb3/random-folders?widget=1&limit=15` |
| Same date in earlier years, newest first | `plugin://plugin.image.mypicsdb3/on-this-day?widget=1&limit=15` |
| Same date in earlier years, random | `plugin://plugin.image.mypicsdb3/on-this-day-random?widget=1&limit=15` |
| Years | `plugin://plugin.image.mypicsdb3/years?widget=1` |
| Cameras | `plugin://plugin.image.mypicsdb3/cameras?widget=1` |
| Keywords | `plugin://plugin.image.mypicsdb3/keywords?widget=1` |
| Favorites | `plugin://plugin.image.mypicsdb3/favorites?widget=1&limit=15` |
| Rated | `plugin://plugin.image.mypicsdb3/rated?widget=1&limit=15` |
| Geotagged | `plugin://plugin.image.mypicsdb3/geotagged?widget=1&limit=15` |

The `widget=1` marker lets MyPicsDB 3 distinguish background widget loading
from interactive browsing. The bundled Estuary home rows add `home=1` and a
Home-window generation value, for example:

```text
plugin://plugin.image.mypicsdb3/on-this-day?widget=1&home=1&generation=<generation>
```

`home=1` applies home-art prioritization and makes the provider read the typed
`home_widget_limit` setting directly. Cached URL values such as `limit=10` are
ignored for bundled home rows. The generation changes when that setting changes
or a scan changes catalogue rows, making Kodi request fresh provider results
without a complete skin reload. Third-party widgets should omit `home=1` when
they want the general widget limit and original media order.

The bundled slot URL always has a second cache-key field. For non-random slots its skin variable resolves to `0`; for the three random row types it resolves to the live random generation:

```text
plugin://plugin.image.mypicsdb3/home-slot?slot=1&widget=1&home=1&generation=<generation>&random_generation=<slot-random-generation>
```

For bundled random home rows, the plug-in hashes both generation values into a
stable database pivot. Repeated requests for an unchanged provider URL therefore
return the same selection instead of invoking a fresh random sample.

`MyPicsDB3.RandomWidgetGeneration` advances at the interval configured under
**Settings > Home screen**, two hours by default. It is also advanced by
**Refresh random selections**. Because the per-slot variable changes only for Random memories, Random albums and
On this day - random, scheduled refreshes do not change the provider URL for
non-random slots. Catalogue-changing scans still advance the common
generation and therefore refresh every MyPicsDB 3 row, including the random
ones.

The optional `limit` is restricted to 1–500 for ordinary widgets; bundled home
providers use the configured 4–40 home limit instead.
Interactive views use pagination.
Random views use indexed random keys rather than `ORDER BY RANDOM()` across the
whole table. **On this day - random** also shuffles the selected rows before they
are returned, so the visible order is not chronological. The Estuary MyPicsDB 3
home screen offers **On this day** and **On this day - random** as separate rows.

## Saved smart collection providers

A third-party skin can use a saved collection directly as a read-only widget
source:

```text
plugin://plugin.image.mypicsdb3/saved-search?id=42&widget=1
```

The URL contains the database ID, not raw Query Model JSON. MyPicsDB 3 loads and
validates the stored query on every request.

The bundled Estuary integration uses fixed slot providers instead:

```text
plugin://plugin.image.mypicsdb3/home-slot?slot=1&widget=1&home=1&generation=<generation>&random_generation=<slot-random-generation>
```

The plug-in validates the slot and resolves its materialized saved-search ID.
This avoids embedding a two-argument add-on setting label inside `$INFO[...]`,
where its commas can be interpreted as label prefix/suffix separators. Up to
nine configured slots are available. Smart slots use the standard MyPicsDB
poster row; opening the saved collection uses the configured Default album view.

## Manual collection providers

A manual collection can be used directly as a read-only widget source through
its normal collection route:

```text
plugin://plugin.image.mypicsdb3/collection?id=9&widget=1
```

The bundled Estuary integration uses a fixed materialized slot instead:

```text
plugin://plugin.image.mypicsdb3/home-slot?slot=1&widget=1&home=1&generation=<generation>&random_generation=<slot-random-generation>
```

The plug-in resolves `home_collection_id_1`, applies the configured Home-row
limit and returns available media in the collection's explicit order. Rename,
membership, ordering and deletion actions invalidate or remove the slot safely.
Opening the collection interactively uses **Default album view**.
