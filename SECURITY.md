# Security policy

Do not publish database passwords, source credentials, logs containing private
paths, or GPS metadata in public issues. Report a security problem privately to
the repository owner through GitHub's security advisory feature.

## Metadata refresh and diagnostics

Version 0.8.23 diagnostics are deliberately local to the Kodi dialog. Do not log
raw EXIF payloads, complete source paths, GPS coordinates or other private metadata
when extending this feature. The diagnostic route passes only an indexed picture ID;
the source URI and metadata are resolved locally. Coordinates are displayed only
when **Store GPS coordinates** is enabled, while GPS-tag presence may be reported as
a boolean without exposing the coordinate pair.

Explicit metadata refresh is a catalogue write, not a source-file write. It must
continue to use the `metadata-refresh` lock so scans and schema migrations cannot
rewrite the same catalogue state concurrently. Source media remain read-only.

### Metadata fallback privacy (0.8.24)

The core EXIF resilience fallback is local and read-only. It operates only on the
already-read metadata prefix, ignores MakerNote/UserComment payloads, makes no
network requests, and does not log recovered camera/GPS values. Diagnostics shows
those values only in the local Kodi UI when explicitly requested.

### XMP location diagnostics (0.8.27)

XMP GPS/location compatibility is offline and read-only at extraction time. The
diagnostics view may display matched location/GPS property names and values only in
the local Kodi text viewer after the user explicitly opens diagnostics; those values
must not be copied to normal logs, support-bundle summaries or network requests.
Version 0.8.28 adds reverse geocoding only as an explicit opt-in single-picture
action. It must remain disabled by default, must never send image bytes, filenames or
source paths, and must block before network I/O while a scan/migration/metadata refresh
owns the catalogue. Provider results are cached locally and attribution is retained.
Do not add background, folder or periodic public-Nominatim geocoding: the public
service policy limits applications to one request per second, requires identifying
User-Agent/attribution/caching, and discourages bulk use. MyPicsDB persists a
per-endpoint request timestamp and spaces cache misses by at least 1.1 seconds. The
endpoint remains configurable so a provider can be switched without a software
release. Remember that the configured server necessarily sees normal HTTP connection
metadata such as the client's public IP address even though image bytes/path/name are
not sent.
