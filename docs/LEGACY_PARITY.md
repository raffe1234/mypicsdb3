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

### 4. Generic metadata/tag browsing

Legacy `Browse by Tags` exposed arbitrary stored tag types and their values.
Modern plan: an **Advanced Metadata Browser** over curated canonical categories
(Camera, Location, Capture, Image, Keywords) with bounded facet counts through
the Query Model/catalogue boundary. An optional "Other metadata" area can come
later; do not dump uncontrolled raw EXIF names into the primary UI.

Recommended target: 0.8.14.

### 5. Freeze current results into a manual collection

Legacy workflows could bulk-add filter/tag results to collections. Modern plan:
**Save current results as manual collection** / snapshot, transactionally copying
catalogue IDs only. Never copy or move original files.

Recommended target: 0.8.15.

### 6. Export/archive selected results

Legacy code exposed export/ZIP paths. Modern plan: first build a safe COPY-only
export engine using Kodi VFS, collision handling, cancellation, missing-item
reporting and a manifest. Archive creation can reuse that engine later. No move
or delete operation should be introduced as part of parity.

Recommended target: 0.8.16.

### 7. GPS/map view

Legacy MyPicsDB had a GoogleMap dialog/context action for GPS-tagged pictures.
Modern plan: provider-neutral location details and an explicit opt-in map action.
Do not embed an API key or silently send a user's photo coordinates to a network
provider.

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

## Recommended roadmap after 0.8.13

1. 0.8.14 — Advanced Metadata Browser.
2. 0.8.15 — collection snapshots.
3. 0.8.16 — safe export/copy + manifest.
4. Later — light video metadata, map/location UX, optional generic provider API,
   rebuild catalogue while preserving sources.
5. Later/high-risk — legacy import, duplicate reporting, sidecar-only refresh,
   mixed picture/video/music state machine.

This order is a recommendation, not a release contract. User priorities can
change it, but new work should preserve the scanner, Query Model, migration,
source-file and playback safety boundaries already established in MyPicsDB 3.
