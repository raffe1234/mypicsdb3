# Widget URL reference

All widget views are read-only and never start a scan. They use the local
**Minimum picture rating** setting, just like the interactive browser views.

| View | URL |
|---|---|
| Recently taken | `plugin://plugin.image.mypicsdb3/recent-taken?limit=15` |
| Recently discovered | `plugin://plugin.image.mypicsdb3/recent-added?limit=15` |
| Random memories | `plugin://plugin.image.mypicsdb3/random?limit=15` |
| Recent albums | `plugin://plugin.image.mypicsdb3/recent-folders?limit=15` |
| Random albums | `plugin://plugin.image.mypicsdb3/random-folders?limit=15` |
| Same date in earlier years | `plugin://plugin.image.mypicsdb3/on-this-day?limit=15` |
| Years | `plugin://plugin.image.mypicsdb3/years` |
| Cameras | `plugin://plugin.image.mypicsdb3/cameras` |
| Keywords | `plugin://plugin.image.mypicsdb3/keywords` |
| Favorites | `plugin://plugin.image.mypicsdb3/favorites?limit=15` |
| Rated | `plugin://plugin.image.mypicsdb3/rated?limit=15` |
| Geotagged | `plugin://plugin.image.mypicsdb3/geotagged?limit=15` |

The optional `limit` is restricted to 1–500. Interactive views use pagination.
Random views use indexed random keys rather than `ORDER BY RANDOM()` across the
whole table.
