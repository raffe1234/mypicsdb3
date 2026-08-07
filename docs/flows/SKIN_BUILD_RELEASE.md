# Estuary integration, builds, GitHub Actions and releases

This guide covers the optional Estuary MyPicsDB 3 skin, the picture add-on, the
separate screensaver, generated packages and the GitHub workflows that validate
and publish them.

## Source and generated content

The repository does not commit a complete copied Estuary source tree.
Instead it stores:

```text
contrib/estuary/upstream.json     pinned official Kodi releases
contrib/estuary/patches/...       maintained MyPicsDB 3 changes
```

The build process:

```text
pinned official Estuary archive
→ extract skin.estuary only
→ change add-on id
→ add MyPicsDB 3 dependency
→ apply maintained Pictures-home and Picture Info patches
→ verify generated skin
→ package per Kodi channel
```

Generated skin source under `build/` and downloaded archives under `.cache/`
are intentionally excluded from Git history.

## Main files

| Path | Responsibility |
| --- | --- |
| `contrib/estuary/upstream.json` | Official release pins and independent skin versions |
| `contrib/estuary/patches/` | Maintained skin modifications |
| `tools/estuary_skin.py` | Fetch/extract/patch logic |
| `tools/update_estuary_upstreams.py` | Finds newer official release pins |
| `tools/build.py` | Creates packages, checksums and Kodi repository tree |
| `repository.mypicsdb3/` | Kodi repository add-on metadata |
| `.github/workflows/ci.yml` | Python matrix, tests, full build and add-on checker |
| `.github/workflows/mariadb.yml` | Shared-database integration test |
| `.github/workflows/pages.yml` | Published Kodi repository on GitHub Pages |
| `.github/workflows/release.yml` | Tagged release assets |
| `.github/workflows/estuary-upstream.yml` | Scheduled verified upstream refresh |

## Widget and skin contract

MyPicsDB 3 exposes stable provider URLs and preferences that skins can read.
The maintained Estuary fork consumes that contract to show picture rows on the
Pictures home screen. It also adds the guarded current-picture collection action
to `DialogPictureInfo.xml`; that skin change has its own focus-navigation
contract and does not change Kodi keymaps.

Before changing a provider URL, label, artwork property, row limit or preference
serialization, read:

- `docs/WIDGET_URLS.md`;
- `docs/SKIN_INTEGRATION.md`;
- `docs/ESTUARY_INTEGRATION.md`.

A provider change may be a public integration change even when the Python edit
looks small.

## Local builds

Normal verification without an Estuary download:

```bash
python3 tools/verify.py
python3 -m pytest
python3 tools/build.py --skip-skin
```

Full current-channel build:

```bash
python3 tools/build.py
```

Offline/local upstream source for one channel:

```bash
python3 tools/build.py --channel omega --estuary-source /path/to/skin.estuary
```

The build writes the picture add-on, screensaver, repository add-on, compatible
Estuary skin archives and repository tree under `dist/`.

## GitHub Actions after a push

For a branch or pull request:

1. Open the pull request's **Checks** section or repository **Actions** tab.
2. Confirm the **CI** Python matrix is green.
3. Confirm **MariaDB integration** is green.
4. For skin/build changes, inspect the Python 3.11 build and add-on checker
   steps and download the workflow artifact when manual package testing is
   needed.
5. Correct failures in a new commit on the same branch.

For `main`, the normal workflows repeat the checks. Pages or scheduled Estuary
workflows run according to their own triggers.

## Release flow

A release is intentional and tag-driven:

```text
update versions and changelog
→ run tests, verification and full build
→ commit and push main
→ wait for main workflows to pass
→ create annotated v<version> tag
→ push tag
→ release workflow rebuilds and attaches assets
```

The plug-in, screensaver, repository add-on, Estuary skin, database schema and
Query Model have different versions. Change only the version that belongs to the
modified contract, and keep the screensaver's declared MyPicsDB 3 dependency
compatible with the core API it imports.

## Scheduled upstream refresh

The Estuary updater checks for newer official release pins. When a pin changes,
GitHub Actions applies the maintained patch, verifies, tests, builds and runs
the add-on checker before committing the pin. On failure it leaves the existing
published repository in place and reports the problem for manual review.

Do not manually accept a new upstream pin merely because it downloads. The
patched home screen and both supported Kodi channels must still build and test.

## Useful tests

- `tests/test_estuary_skin.py`, including Picture Info insertion and focus
  navigation;
- `tests/test_estuary_updater.py`;
- `tests/test_repository_assets.py`;
- `tests/test_home_layout_editor.py`;
- `tests/test_home_screen_settings.py`;
- `tests/test_settings_display.py`;
- relevant UI/widget tests.

## Invariants

- Generated official Estuary files are not committed.
- Upstream tags and hashes remain pinned and reviewable.
- Both supported Kodi channels are built where the workflow requires them.
- Public widget URLs remain stable or are documented as compatibility changes.
- The Picture Info action remains reachable by keyboard/remote only while visible,
  and its hidden state preserves native Estuary list navigation.
- Repository artwork paths and manifests remain valid.
- A release tag is created only after the exact main commit is green.
- The repository add-on version changes only when that add-on changes.
