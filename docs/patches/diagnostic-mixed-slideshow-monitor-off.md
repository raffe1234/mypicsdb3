# Diagnostic patch: mixed slideshow monitor off

This branch is an A/B diagnostic build for the reported Kodi crash during
recursive slideshows. It keeps `MixedSlideshowVideoMonitor` completely inactive,
which removes its twice-per-second `Player.GetActivePlayers` polling,
`getPlayingFile()` calls, catalogue lookups and transition-time `Player.GoTo`.

The patch deliberately does **not** change the plug-in version and must not be
tagged or published as a normal release. Install the branch build manually and
compare it with the unmodified 0.2.27 build using the same media and order.

Expected trade-off: the earlier black-screen or repeated-image behaviour after a
video may return. That is acceptable for this diagnostic test.

Record these results for both builds:

- photo-only recursive slideshow;
- mixed slideshow with video first, in the middle and last;
- whether stutter starts, and after how many items;
- whether Kodi crashes and whether it happens during or after a video;
- local storage compared with SMB/NFS;
- video container, codec, resolution and duration;
- Kodi debug log plus the platform crash log or coredump.

Interpretation:

- If the monitor-off build is stable while 0.2.27 crashes, replace the polling
  monitor with a guarded event-driven transition design before a public release.
- If both builds crash, focus next on Kodi's native slideshow/video path, codec,
  network source and platform crash data instead of the monitor.
