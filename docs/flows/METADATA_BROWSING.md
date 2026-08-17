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
