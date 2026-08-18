# Metadata browsing and facet counts

Version 0.8.14 modernizes legacy MyPicsDB **Browse by Tags** without exposing
uncontrolled raw metadata names. Browse/facet enumeration remains read-only and uses
the indexed catalogue; it never opens source media and never starts a scan. Version
0.8.23 adds separate explicit per-picture/per-folder **Refresh metadata** context
actions and a one-picture **Metadata diagnostics** action; those are not part of the
facet query path.

## Request flow

```text
metadata-browser
  -> metadata_browser.CATEGORIES
  -> metadata-category?category=...
  -> metadata-values?field=...
  -> Catalog.query_facet_counts(validated picture-only Query Model, fixed facet key)
  -> metadata-result?field=...&value=...
  -> metadata_browser.metadata_value_query()
  -> validated Query Model v1
  -> Catalog.query_pictures()
```

## Curated hierarchy

- **Camera** — camera make and camera model;
- **Location** — country, state/region, city and sublocation;
- **Capture** — capture year;
- **Image** — file extension, MIME type, orientation-aware image shape and rating;
- **Keywords** — normalized indexed keyword values.

The browser deliberately omits arbitrary EXIF/XMP/IPTC tag names. Raw producer
metadata belongs to extraction/mapping; the browser exposes only values MyPicsDB 3
can represent safely in its canonical catalogue.

## Facet boundary

`Catalog.query_facet_counts()` accepts only internal allowlisted facet keys and a
bounded `limit`/non-negative `offset`. Callers cannot provide column names or SQL
expressions. Scalar facets use fixed expressions; normalized keywords use the
`picture_tags`/`tags` relation. Counts compile the supplied Query Model first, so
missing-row scope and the user's minimum-rating policy match the eventual result
selection.

Facet keys such as `camera_make`, `camera_model` and `taken_year` are not new Query
Model fields. Selecting a value converts it to existing version-1 rules: camera
make/model becomes a partial `camera eq` rule, capture year becomes `taken_date
between`, rating/file/location/aspect use their existing fields, and keywords use
`keyword eq`. This keeps saved-query compatibility and avoids a Query Model version
change.

## Pagination and safety

Metadata value lists request one extra bounded row to decide whether to show **Next
page**. Result pages use the normal picture browser pagination. Empty/NULL facet
values are omitted; missing-metadata workflows belong under **Needs attention**.

Invariants:

- no source file reads or writes;
- no scan trigger;
- no user-controlled SQL identifiers;
- counts/results respect the same minimum-rating display policy;
- SQLite and MariaDB aggregate SQL must be covered together;
- adding a new facet requires an explicit catalogue allowlist entry and a validated
  Query Model translation before it becomes user-visible.

## Indexed values versus fresh extraction

Browse metadata always enumerates canonical values already stored in the catalogue.
Kodi's native `i` picture-information dialog may independently read the source file,
so a Make/Model shown by Kodi can still be blank in a stale MyPicsDB index. Version
0.8.23 **Metadata diagnostics** performs a fresh MyPicsDB extractor read for one
selected picture and compares it with the indexed row. **Refresh metadata** is the
explicit write step that makes newly extracted canonical values available to facet
counts and Query Model results.

GPS coordinates and named locations are also separate metadata concepts. A camera may
store EXIF latitude/longitude without embedding city, state or country text; 0.8.23
does not reverse-geocode coordinates.

### Diagnostics display and parser fallback (0.8.24)

Metadata diagnostics is displayed in Kodi's scrollable text viewer so long
extractor reports are readable on normal TV layouts. The report includes whether
the bounded core EXIF fallback was used and how many core tags it recovered. A
reported ExifRead error can therefore coexist with successful Fresh extraction of
Camera Make/Model or GPS; the error describes the primary parser, not necessarily
the final normalized result.

0.8.25 adds low-level local diagnostics for cases where the fallback itself does
not fire: metadata-prefix byte count, embedded-EXIF detection, prefix read errors
and image-dimension probe errors. The recovery path also has a bounded fresh-VFS
JPEG marker walker, so a valid EXIF APP1 block can still be found when the normal
prefix path is unusable. These diagnostics do not write the catalogue; **Refresh
metadata** remains the explicit write action.
### Kodi VFS byte-stream fix (0.8.26)

If diagnostics in 0.8.25 show both `EXIF reader error: UnicodeDecodeError` and
`Metadata prefix read error: UnicodeDecodeError` with zero prefix bytes, the failure
is below the metadata mapping layer: binary JPEG data was passed through Kodi's text
`read()` API. 0.8.26 uses `readBytes()` in `KodiFileAdapter`, so Fresh extraction can
reach ExifRead/fallback data over SMB without UTF-8 decoding the file contents.
Existing indexed rows still require explicit refresh after a representative
diagnostic succeeds.

### XMP location/GPS compatibility and bounded JPEG headers (0.8.27)

Fresh extraction now reports a bounded list of XMP properties relevant to location and
GPS. Common EXIF-XMP `GPSLatitude` / `GPSLongitude` values can supply coordinates when
the EXIF GPS IFD did not, and common IPTC Extension `LocationShown*` /
`LocationCreated*` aliases can fill missing city/state/country/sublocation values. EXIF
coordinates and explicit/custom metadata mapping continue to win when they already
produced a canonical value. No reverse geocoding or network lookup is performed.

For JPEG sources, the metadata-prefix helper walks marker headers through Start Of
Scan and buffers only APP1 (EXIF/XMP) and SOF payloads, seeking over unrelated APP
segments and compressed pixels. The diagnostics label therefore reports **Metadata
header bytes buffered**, which may be far smaller than the source file while still
containing the metadata needed by this flow. Installing 0.8.27 does not force a
whole-library rewrite: inspect one representative picture, then use explicit refresh
for rows/folders that should store newly recognized values.

### Whole-library metadata reindex (0.8.29)

Browse metadata now begins with **Refresh all picture metadata**. It is an explicit
maintenance action, not a facet or Query Model query. It re-reads only existing
still-picture catalogue rows using the current extractor/mapping rules, updates their
canonical metadata/tags/search text and leaves source files unchanged. Progress is
cancellable and resumable from a profile-local checkpoint.

The metadata-refresh action itself intentionally does **not** contact a reverse-geocoding
provider. Existing embedded city/state/country values are indexed normally, and cached
provider results may be reused locally without network I/O. Starting in 0.8.32, new
GPS-to-name lookups for many pictures live in a separate explicit action under
**Browse metadata > Location**, with its own lock, confirmation, stop/resume state and
provider throttling.

### Explicit online location enrichment (0.8.28)

When **Store GPS coordinates** has produced a valid pair, the picture context menu can
show **Resolve location online**. The feature remains disabled until **Settings >
Metadata > Online reverse geocoding** is enabled. Invocation then asks for explicit
confirmation, acquires the `location-enrichment` writer lock and only afterwards sends
latitude/longitude to the configured Nominatim-compatible `/reverse` endpoint. A busy
scan/migration/metadata refresh blocks the action before network I/O.

The provider response uses Nominatim `geocodejson` stable address categories. Country,
state/region, city and sublocation fill only empty canonical columns; embedded metadata
already present in those columns wins. Provider+coordinate responses are cached in the
local `meta` table, and the attribution/source is retained with the URI-hash enrichment
record. Cache misses are throttled with a persistent provider timestamp so requests
are spaced by at least 1.1 seconds. Search text is rebuilt immediately after a
successful save. There is no folder, recursive, scheduled or scanner-triggered online
geocoding path. Later metadata refreshes or changed-file scans may reapply the already
saved local enrichment, but they never contact the provider.
### Explicit bulk GPS location enrichment (0.8.32)

**Browse metadata > Location > Analyze GPS coverage** is the safe planning step. It
performs no network requests, does not open source images and makes no catalogue writes.
The GPS count therefore means **coordinate pairs already stored in the catalogue**, not
GPS tags discovered by a fresh source-file scan. Because **Store GPS coordinates** is a
privacy-sensitive setting and is disabled by default, the report also compares every
still picture's `metadata_index_hash` with the fingerprint for the current metadata
settings. It explicitly shows how many rows are current and how many still need metadata
refresh before the stored-GPS count and reverse-geocoding estimate can be treated as
complete. Enabling GPS storage requires a normal scan or **Refresh all picture metadata**
to re-read older rows; changing the setting alone does not retroactively populate GPS.

Once the catalogue is current, the report shows how many GPS rows already have all four
named location fields, how many need enrichment, unique coordinate/bucket counts,
existing local cache reuse, expected ~10 m reuse during a run and the resulting estimated
online requests. For the default public Nominatim endpoint it also estimates time using
the same long-run throttle boundary as the worker.

**Browse metadata > Location > Resolve missing locations from GPS** examines only
available still-picture rows with a stored latitude/longitude pair and at least one
empty country/state/city/sublocation field. It freezes an ID horizon, updates rows in ID
order and saves a resumable checkpoint. Stop requests are soft: the current picture
finishes, progress is persisted, and the next invocation can resume or restart.

The worker first reuses per-picture enrichment and local caches. For explicit bulk use,
coordinates are rounded to four decimals (roughly 10 metres) so a burst of pictures from
the same place can share one provider response even when camera GPS jitter differs by a
few metres. Only coordinates are sent to the configured Nominatim-compatible endpoint;
filenames, URIs and image bytes stay local. Returned values fill only empty canonical
fields, preserving embedded metadata precedence.

The default public Nominatim endpoint stays single-threaded and cached. New cache misses
wait at least 1.1 seconds; after a resumable run has aged past 24 hours they slow to about
four requests per minute. Large libraries should therefore prefer an operator-controlled
compatible endpoint. Neither normal scanning nor whole-library metadata refresh invokes
this online path automatically.
