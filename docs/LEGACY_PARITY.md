# MyPicsDB / MyPicsDB2 legacy parity and modernization plan

This document records the legacy-function review that guides MyPicsDB 3. The
goal is **parity in useful behavior**, not a mechanical port of old code or old
bugs.

Primary historical references used for the review:

- https://github.com/Xycl/plugin.image.mypicsdb
- https://github.com/Xycl/repository.xycl.addons
- https://forum.kodi.tv/showthread.php?tid=133905
- https://forum.kodi.tv/showthread.php?tid=387901

The GitHub repositories are the strongest evidence for implemented legacy
behavior because they expose the old code, README and service package. Forum
threads are useful for user-visible behavior and known playback problems. A
feature should not be described as legacy parity unless it is supported by one
of these sources or by retained project evidence.

## Already replaced or exceeded by MyPicsDB 3

- multiple Kodi picture sources and central catalogue;
- SQLite plus shared MySQL/MariaDB behind one catalogue API;
- manual and scheduled background scanning;
- unavailable/partial-source safety, scan locks, cancellation and resumable
  folder checkpoints;
- year/month/day and no-date browsing;
- keywords, cameras, ratings, favorites, geotagged media and global search;
- saved filters through a validated, versioned Query Model;
- manual collections with deterministic order;
- collection music-playlist assignment;
- optional video rows without a movie scraper;
- screensaver as a bounded read-only add-on;
- modern Home providers and maintained Estuary integration.

Separate old concepts such as named date "Periods" do not need their own table:
a saved smart collection with a date range provides the same user value with a
more general model.

## Verified remaining gaps and modern plan

### 1. Per-source scan behavior — implemented in 0.8.11

Legacy roots could carry source/root-specific recursion and excluded paths.
MyPicsDB 3 schema 8 modernizes this as an inherited/explicit source policy with
checkpoint compatibility and shared-database semantics. Future source-specific
metadata depth, schedule or playback-pause settings are intentionally not part
of 0.8.11.

### 2. Metadata tag translation / combination — implemented in 0.8.12

Legacy MyPicsDB could translate, combine or suppress raw metadata tags. MyPicsDB 3
schema 9 modernizes this with database-global, validated overrides on top of
built-in EXIF/XMP/IPTC normalization. Canonical targets are allowlisted; scalar
values use deterministic priority, keywords combine mapped values, and a custom
ignore rule can suppress a built-in mapping. XMP mappings identify the property
local name so producer-specific namespace prefixes do not become persistent
configuration. No user mapping text becomes an SQL identifier.

A per-picture metadata-index fingerprint covers both the effective mapping and
metadata extraction settings. This provides the explicit reindex path the legacy
feature lacked: changing a mapping makes the next scan re-read otherwise unchanged
pictures, while original files remain untouched. Shared MariaDB clients use the
same stored override set.

### 3. Negative/presence smart-filter operators and "Needs attention" — implemented in 0.8.13

The old Filter Wizard supported positive/negative tag behavior and no-date
workflows. MyPicsDB 3 version 0.8.13 exposes the existing Query Model v1
presence operators as **Exists** / **Missing**, uses controlled negated groups
for **Is not**, adds exact/upper-bound/range rating choices and makes MIME type a
first-class editor facet. The **Needs attention** browser reuses the same Query
Model compiler for pictures without capture date, camera metadata, canonical
location or keywords. It does not add raw SQL, scan files or modify source
metadata.

### 4. Generic metadata/tag browsing — implemented in 0.8.14

Legacy `Browse by Tags` exposed arbitrary stored tag types and their values.
MyPicsDB 3 version 0.8.14 implements the modernized **Browse metadata** path over
curated canonical categories: Camera, Location, Capture, Image and Keywords.
The catalogue owns a fixed facet allowlist, value counts are bounded and paginated,
and selecting a value builds an ordinary validated Query Model v1 query. Camera
make/model, capture year, image shape, rating and normalized keyword facets join
the location/file facets introduced earlier. No file-supplied tag name becomes SQL.

An optional advanced "Other metadata" store/browser could still be designed later,
but it would require an explicit raw-metadata persistence model and is not required
for the stable legacy use case. Do not dump uncontrolled raw EXIF names into the
primary UI.

### 5. Freeze current results into a manual collection — completed in 0.8.16

Legacy workflows could bulk-add filter/tag results to collections. MyPicsDB 3
0.8.16 modernizes this as **Save current results as collection** for global
search, saved smart collections, Browse metadata results and Needs attention.
The complete validated result is frozen transactionally as ordered catalogue IDs
inside a new manual collection. No query JSON or source-file copies are stored,
and later query matches do not alter the snapshot.

### 6. Export/archive selected results — copy parity completed in 0.8.17

Legacy code exposed export/ZIP paths. MyPicsDB 3 version 0.8.17 implements the
low-risk, useful part as explicit **COPY-only** export for query-backed results
and manual collections. The complete ordered selection is frozen first, copied
through the filesystem/VFS boundary into a unique dedicated destination folder,
and accompanied by a versioned JSON manifest. Existing destination files are
never overwritten; basename collisions receive numbered suffixes, missing and
failed source items are reported, cancellation preserves the already copied
partial result, and destinations inside configured picture-source trees are
rejected. Credentials embedded in VFS URIs are stripped from manifest provenance.

The legacy ZIP/archive path is intentionally **not** copied yet. If archive
creation is useful later, it should reuse the same frozen selection, collision,
source-safety and manifest boundaries. Move/delete semantics remain out of scope.

### 7. GPS/map view — local foundation implemented in 0.8.22

Legacy MyPicsDB had a GoogleMap dialog/context action for GPS-tagged pictures.
MyPicsDB 3 version 0.8.22 adds provider-neutral **Location details** plus local
**Browse this city/country** actions over already-indexed catalogue metadata. GPS
coordinates are shown only when the privacy-sensitive storage setting is enabled;
no provider URL, API key or network request is involved.

Version 0.8.28 closes the named-location part of that gap with an explicit,
disabled-by-default **Resolve location online** action. It resolves one stored GPS pair
at a time through a configurable Nominatim-compatible service, caches the result,
retains attribution and fills only missing canonical location fields. No image/path
metadata is sent and no scan/background/bulk geocoding exists.

An explicit **Open map** action remains a later gap. It must stay opt-in at the point
of use, provider-neutral and must not silently send a user's photo coordinates to a
network provider or embed private API keys.

Version 0.8.23 adds explicit metadata refresh/diagnostics around this foundation.
A selected picture can be freshly inspected to determine whether MyPicsDB's current
EXIF/XMP/IPTC extractor sees camera/GPS/location data that is absent from the stored
index, then refreshed without a catalogue rebuild. Folder refresh is exact-folder and
serial. This does not add reverse geocoding: coordinates still do not become named
locations unless such text metadata exists in the source.

### 8. Legacy database / Picasa import

Old code included Picasa import paths; existing MyPicsDB/MyPicsDB2 users may also
benefit from collection/filter migration. Modern plan: one Maintenance > Import
framework with a dry run, matched/missing counts and explicit confirmation.
Legacy source formats must be re-verified before an importer is promised.

### 9. Mixed pictures + videos + music

Legacy collections could mix pictures/videos with music, but forum evidence also
records playback hangs around stopping/resuming music across video playback.
Modern plan: only after lower-risk parity work, build an explicit media-session
state machine that owns the music it starts, pauses/stops only that owned queue,
waits for video completion and resumes safely. Do not recreate the old implicit
Kodi playlist choreography.

### 10. Generic skin API

Legacy MyPicsDB published Latest/Random/statistics window properties. MyPicsDB 3
uses modern provider routes and Estuary Home integration. If other skins request
a stable integration contract, expose a documented provider API v1 rather than
reviving CommonCache-era behavior.

## Recommended roadmap after 0.8.28

1. 0.8.15 — completed: stale scan/crash recovery and short automatic busy retry.
2. 0.8.16 — completed: collection snapshots from validated query-backed results.
3. 0.8.17 — completed: safe COPY-only export + credential-sanitized manifest.
4. 0.8.19 — completed: scanner observability without parallel I/O or write concurrency.
5. 0.8.22 — completed: offline/provider-neutral location details and local city/country browsing; explicit map opening remains deferred.
6. 0.8.23 — completed: explicit serial metadata refresh for one picture/exact folder plus privacy-local indexed-vs-fresh extractor diagnostics; no source-file mutation or catalogue rebuild.
7. 0.8.24 — completed: resilient bounded core TIFF/EXIF fallback when ExifRead aborts on a malformed/incorrectly encoded text tag, plus scrollable metadata diagnostics; no automatic whole-library reindex.
8. 0.8.25 — completed: harden EXIF recovery when the normal metadata prefix path fails and preserve automatic-scan cadence across Kodi/add-on service restarts while still resuming an interrupted checkpoint promptly.
9. 0.8.26 — completed: correct Kodi VFS metadata reads to use the binary `readBytes()` API so normal JPEG/EXIF bytes are not UTF-8 decoded before ExifRead/fallback processing.
10. 0.8.27 — completed: broaden offline XMP location/GPS compatibility, expose matched XMP location properties in local diagnostics, reduce JPEG metadata-prefix I/O and make scan-blocked refresh explicit.
11. 0.8.28 — completed: explicit privacy-gated single-picture Nominatim-compatible reverse geocoding with local caching, attribution, provider switching and no bulk/background path.
12. Later — light video metadata, optional explicit Open map action, optional generic provider API, rebuild catalogue while preserving sources; optional archive creation may reuse the 0.8.17 export engine if there is a real user need.
13. Later/high-risk — legacy import, duplicate reporting, sidecar-only refresh, mixed picture/video/music state machine.

This order is a recommendation, not a release contract. User priorities can
change it, but new work should preserve the scanner, Query Model, migration,
source-file and playback safety boundaries already established in MyPicsDB 3.
