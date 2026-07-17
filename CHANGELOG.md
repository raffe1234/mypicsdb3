# Changelog

## 0.2.2

- Fixed missing labels for the General item-limit settings.
- Home screen Row 1 through Row 9 now show their selected or default content.
- Normalized the English gettext catalogue.
- Published skin artwork and screenshots at the paths declared in addon.xml.
- Added a short retry for the transient Kodi add-on registration race during updates.
- Updated Estuary MyPicsDB 3 to 21.3.3.

## 0.2.1 - 2026-07-17

- Show visible headings for all MyPicsDB 3 Pictures home-screen rows.
- Add nine configurable row positions and a Media sources visibility setting.
- Add Favorites, Rated pictures and Geotagged pictures as home-screen choices.
- Document row configuration and global Kodi repository-update diagnostics.
- Bump the generated Estuary MyPicsDB 3 skin to 21.3.2.

## 0.2.0 - 2026-07-17

- Add the separately installed `skin.estuary.mypicsdb3` skin for Kodi 21 Omega.
- Build the skin reproducibly from Kodi's official `21.3-Omega` Estuary source.
- Add Pictures home-screen rows for media sources, recent pictures, random memories, albums and On this day.
- Keep standard Estuary installed and untouched so Kodi updates cannot overwrite the custom skin.
- Publish the generated skin through the MyPicsDB 3 repository with its own independent version.
- Document automatic scan intervals and installation, update and fallback procedures.
- Update GitHub Actions to current Node.js 24-compatible action releases.

## 0.1.1 - 2026-07-17

- Fix source activation from Picture sources.
- Build every plugin link from the add-on root instead of the current nested route.
- Show Enable source and Disable source actions in the source context menu.
- Add regression tests for nested plugin URLs and source activation items.

## 0.1.0 - 2026-07-17

- Initial Kodi 21 Omega release candidate.
- SQLite catalogue with WAL mode and incremental scanning.
- Optional shared MySQL/MariaDB catalogue through PyMySQL.
- EXIF, basic XMP, IPTC, GPS, camera, rating and keyword indexing.
- Source management based on Kodi picture sources.
- Background and manual scanning with unavailable-source protection.
- Widget endpoints for recent, random, folder, date, camera and tag views.
- Favorites, rated pictures and geotagged picture views.
- Repository builder, GitHub Actions and Estuary integration documentation.
