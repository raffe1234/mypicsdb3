# Kodi compatibility review — 2026-10-29

## Scope and input

Reviewed the supplied 0.8.39 source archive against the V25 handover and Kodi's
contribution guidance, Python API documentation and relevant implementation.
The source ZIP comment identifies commit
`986b3c8be5af7128a1a780dbb10a842293db31fe`; its SHA-256 is
`17cd1525398a7e63896c388be749864c68660b73a1d52906a7e188795d924fa5`.
The archive is dated September 26 internally despite the October 29 filename.
It exactly matches the source checksum recorded in the handover.

This is a targeted compatibility review, not certification of every runtime
path or confirmation that the live GitHub main branch still matches the archive.
The handover's previous test results and user reports are historical evidence,
separate from the fresh checks below. Issue #20 reporter acceptance is not proven
by this patch; the existing EXIF fix is retained.

## Guidelines and architecture

[Kodi CONTRIBUTING](https://github.com/xbmc/xbmc/blob/master/docs/CONTRIBUTING.md)
asks for focused changes, meaningful commits and relevant review/test evidence.
The repository already has contributor documentation, CI, regression tests and
architecture/data-flow guides. This patch keeps one behavioral topic with tests
and release notes. Kodi's topic-branch/PR rules apply when contributing to xbmc;
the owner's separate repository may use its documented direct-main workflow.

[Kodi CODE_GUIDELINES](https://github.com/xbmc/xbmc/blob/master/docs/CODE_GUIDELINES.md)
is primarily C++ guidance. Its C++ language level, brace style, naming and
clang-format rules should not be applied mechanically to this Python add-on.
The existing four-space Python style is appropriate. Readability and small,
reviewable diffs remain relevant; no whole-project formatting is included.

Separation of catalogue/query/scanner code from Kodi adapters, versioned database
migrations and regression coverage are strengths. `views.py` is very large and
some compatibility boundaries swallow broad exceptions. Future work should
extract cohesive UI helpers and improve targeted diagnostics when a concrete
failure warrants it. A broad refactor is outside this patch.

## API findings

| Area | Finding and disposition |
| --- | --- |
| Picture timestamps | Confirmed bug fixed in 0.8.40: SQL space separator loses the time of day in Kodi's W3C parser. Convert at the InfoTag boundary. |
| Picture resolution | Modern path already uses `InfoTagPicture.setResolution(width, height)`. Keep it. |
| Picture title/path | `setInfo("pictures", ...)` still accepts title and picturepath in inspected Omega/Piers source. Removing all setInfo calls would be unjustified. |
| Legacy picture fallback | The no-InfoTag path sends bare `resolution` with `WxH`. Inspected Kodi source expects `exif:resolution` with a comma. This dormant fallback needs a separate decision/test if older or partial API runtimes are supported; normal Kodi 21/22 uses InfoTag. |
| Video metadata | Uses `getVideoInfoTag().setTitle()` / `setDateAdded()` with a legacy fallback. Video date-added format is a separate API and is not changed. |
| Settings | Adapter prefers `getSettings()` typed access and retains fallbacks. No new settings migration is needed. |
| Progress dialogs | Inspected foreground calls use heading/message and percent/message rather than removed multi-line positional arguments; existing 0.8.30 fix retained. |
| VFS and logging | Modern `xbmcvfs.translatePath`, binary VFS reads and LOGINFO are already used. Old translatePath calls remain as fallbacks, not the normal Kodi 21/22 route. |
| ListItem performance | `_item()` uses default GUI locking. `offscreen=True` may help plugin listings, but should be profiled and limited to items not subsequently managed by a live WindowXML container. Deferred. |
| Skin/API packaging | Build uses the archive's pinned 21.3-Omega and 22.0b2-Piers skins. Building these is not proof of compatibility with every later skin/API version. Pins are not advanced in this fix. |

API references:

- [InfoTagPicture API](https://xbmc.github.io/docs.kodi.tv/master/kodi-dev-kit/group__python___info_tag_picture.html)
- [ListItem API](https://xbmc.github.io/docs.kodi.tv/master/kodi-dev-kit/group__python__xbmcgui__listitem.html)
- [Omega InfoTagPicture implementation](https://github.com/xbmc/xbmc/blob/a3a448d26b8d560a65655dab2cd122994dc4e146/xbmc/interfaces/legacy/InfoTagPicture.cpp)
- [Omega W3C parser](https://github.com/xbmc/xbmc/blob/a3a448d26b8d560a65655dab2cd122994dc4e146/xbmc/XBDateTime.cpp)
- [Piers InfoTagPicture implementation](https://github.com/xbmc/xbmc/blob/e513e0ff4331fc25fd2454659a9dd3e6b7670146/xbmc/interfaces/legacy/InfoTagPicture.cpp)
- [Piers W3C parser](https://github.com/xbmc/xbmc/blob/e513e0ff4331fc25fd2454659a9dd3e6b7670146/xbmc/XBDateTime.cpp)
- [Omega ListItem implementation](https://github.com/xbmc/xbmc/blob/f8815ee40f49a700c047982d752be4b2a61420e2/xbmc/interfaces/legacy/ListItem.cpp)

[Official add-on repository rules](https://kodi.wiki/view/Add-on_rules) and
[addon.xml documentation](https://kodi.wiki/view/Addon.xml) are additional concerns,
separate from xbmc core contribution style. The project includes Python 3 code,
license files, metadata/assets and localized strings. Passing local checks does
not imply acceptance into Kodi's official repository. Complete localization,
platform behavior and distribution requirements still need submission review.

## Fresh validation and limits

- Original source: 513 tests passed, 9 MariaDB integration tests skipped.
- New regression against original implementation: 8 failures, 16 passes.
- Patched source: 536 tests passed, 9 MariaDB integration tests skipped.
- `tools/verify.py`: passed.
- Full `tools/build.py`: passed, including both pinned Estuary variants.
- `kodi-addon-checker` 0.0.36: see the delivered validation log for results.
  Repository add-on validation uses tools/verify.py, as in existing CI.
- Local interpreter: Python 3.13; pytest 9.2.0, ExifRead 3.5.1,
  IPTCInfo3 2.4.0, Pillow 12.3.0 and PyMySQL 1.2.3.
- Kodi itself, real NAS/network media, playback, MariaDB and other Python
  versions were not executed locally. The existing CI matrix does not include
  Python 3.8, reported in the handover's Kodi runtime. Add that coverage in a
  separate compatibility change with suitable test-dependency constraints.

Manual acceptance: install 0.8.40 on Kodi 21 and the intended Kodi 22 build;
open a known image captured at a non-midnight time in a normal listing and a
collection slideshow. Check picture date/time, dimensions, caption and playback.
Confirm time agrees with the catalogue and that video entries still work.
Do not reindex solely for this presentation fix. Check CI/MariaDB Actions on the
pushed commit before tagging a release.
