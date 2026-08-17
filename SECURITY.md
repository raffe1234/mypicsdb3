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
