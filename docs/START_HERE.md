# Start here: developing MyPicsDB 3

This page is the shortest route from a new checkout to a useful first change.
It is written for contributors who know Python and Git at a basic level but do
not yet know Kodi add-ons or the MyPicsDB 3 codebase.

You do not need to read every file before helping. Start with the overview,
follow one complete data flow, run the tests, and then read only the documents
that belong to your task.

## Recommended reading order

1. Read the first sections of the root [README](../README.md) to understand what
   the add-on does for a Kodi user.
2. Read this page from top to bottom.
3. Read [Architecture](ARCHITECTURE.md) for the component boundaries and safety
   rules.
4. Open the [data-flow index](flows/README.md) and follow the flow closest to
   your intended change.
5. Set up the project with [Local development](LOCAL_DEVELOPMENT.md).
6. Read one relevant test before changing production code.
7. Use [Contributing](../CONTRIBUTING.md) for the branch, commit, push and pull
   request workflow.

For a small documentation-only change, steps 1, 2, 5 and 7 are usually enough.
For scanner, database, slideshow or skin changes, complete all seven steps.

## The project in one paragraph

MyPicsDB 3 is a Kodi picture add-on with an optional home-video catalogue. Kodi
starts the add-on for browser and action requests and starts a separate service
for background work. The code reads Kodi picture sources through an adapter,
extracts metadata, stores a searchable catalogue in SQLite or MySQL/MariaDB,
and converts database rows into Kodi directory items, widgets and slideshows.
A separate build tool creates the optional Estuary MyPicsDB 3 skin and Kodi
repository packages.

## The two entry points

There are two small files at the top of the add-on package:

- `plugin.image.mypicsdb3/addon.py` calls `plugin_main()` for menu, widget and
  action requests.
- `plugin.image.mypicsdb3/service.py` calls `service_main()` for background
  maintenance, automatic scans and mixed-slideshow monitoring.

Most implementation code lives under:

```text
plugin.image.mypicsdb3/resources/lib/mypicsdb3/
```

## The architecture at a glance

```text
Kodi
├── addon.py
│   └── entrypoints.plugin_main()
│       ├── router.parse_request()
│       ├── KodiContext
│       ├── Runtime
│       │   ├── DatabaseEngine
│       │   ├── Catalog
│       │   └── KodiFilesystem
│       └── PluginUI.dispatch()
│           ├── browsing and widgets
│           ├── search and saved collections
│           ├── source and scan actions
│           └── slideshow actions
│
└── service.py
    └── entrypoints.service_main()
        └── ServiceLoop
            ├── automatic scans
            ├── scan progress and cancellation
            ├── date-sensitive refreshes
            ├── setting-change handling
            └── mixed-slideshow monitoring
```

The important design direction is:

```text
Kodi-specific UI and adapters
            ↓
application orchestration
            ↓
database, scanning, metadata and query logic
```

Core logic should not import Kodi modules directly when an adapter or injected
interface can be used instead. This is what allows most of the project to be
tested without running Kodi.

## A first complete request

When Kodi opens `plugin://plugin.image.mypicsdb3/recent-taken`, the main path is:

```text
Kodi URL
→ addon.py
→ entrypoints.plugin_main()
→ router.parse_request()
→ KodiContext and Runtime
→ PluginUI.dispatch()
→ Catalog.recent_taken()
→ SQLite or MySQL/MariaDB
→ Kodi ListItems
→ xbmcplugin.endOfDirectory()
```

Follow this route in the editor before attempting a larger change. It touches
all major layers without involving scanner or slideshow complexity.

## Repository map

| Path | Purpose |
| --- | --- |
| `plugin.image.mypicsdb3/` | Kodi picture add-on package |
| `plugin.image.mypicsdb3/resources/lib/mypicsdb3/` | Main Python package |
| `plugin.image.mypicsdb3/resources/settings.xml` | Kodi settings UI |
| `plugin.image.mypicsdb3/resources/language/` | Localized strings |
| `repository.mypicsdb3/` | Kodi update-repository add-on |
| `contrib/estuary/` | Pinned upstream versions and maintained Estuary patches |
| `tests/` | Unit, integration and adapter tests |
| `tools/` | Verification, build, version and inspection tools |
| `.github/workflows/` | GitHub Actions for CI, MariaDB, Pages and releases |
| `docs/` | Current technical documentation |
| `docs/adr/` | Long-lived architectural decisions |
| `docs/patches/` | Historical reports for individual releases |

The patch reports explain why older changes were made. They are useful for
history, but they are not the best first description of the current system.
Prefer this page, `ARCHITECTURE.md` and the current source code when they differ.

## Where should I start changing code?

| Task | Start here | Usually also inspect |
| --- | --- | --- |
| Add or change a menu route | `views.py` | `router.py`, UI tests |
| Change a database query | `db/catalog.py` | `query_model.py`, catalogue tests |
| Change database schema | `db/schema.py` | `db/migrations.py`, migration tests and an ADR |
| Change scanning | `scanner.py` | `filesystem.py`, `metadata.py`, checkpoint tests |
| Change metadata extraction | `metadata.py` | `models.py`, metadata tests |
| Add a setting | `resources/settings.xml` | `config.py`, `kodi.py`, typed-setting tests |
| Change global or saved search | `search.py`, `query_model.py` | `saved_searches.py`, search tests |
| Change the smart-filter editor | `smart_filter_editor.py` | `query_model.py`, editor tests |
| Change a slideshow | `views.py`, `slideshow.py` | `service_loop.py`, slideshow tests |
| Change background behaviour | `service_loop.py` | `kodi.py`, service tests |
| Change home rows | `preferences.py`, `home_layout_editor.py` | Estuary tests and skin docs |
| Change the Estuary fork | `contrib/estuary/` | `tools/estuary_skin.py`, skin tests |
| Change packaging or release logic | `tools/build.py` | workflows, repository tests |

## Rules that protect user data and Kodi stability

Treat these as invariants, not suggestions:

1. A source that cannot be reached or completely traversed must not be treated
   as proof that unseen media was deleted.
2. Scanning must remain cancellable and must not start from widget routes.
3. Database schema changes must use versioned, deterministic migrations. Do not
   add ad-hoc schema changes to `Catalog.initialize()`.
4. Stored and user-created queries must pass the validated Query Model. Never
   expose raw SQL through routes, settings or saved searches.
5. Kodi-specific operations belong behind the Kodi and filesystem adapters when
   practical.
6. Existing SQLite catalogues must be backed up safely before migration; shared
   MySQL/MariaDB users are responsible for external backups.
7. Generated Estuary source, `build/`, `.cache/` and release output must not be
   committed.
8. A behaviour change should normally include a regression test that fails
   before the change and passes afterwards.

See [Architecture](ARCHITECTURE.md),
[Database migrations](DATABASE_MIGRATIONS.md) and
[Query Model](QUERY_MODEL.md) for the full rules.

## Data-flow guides

The detailed walkthroughs are split into reasonably sized groups so that a new
contributor does not need to open one very large architecture document:

- [Plug-in requests, browsing and widgets](flows/PLUGIN_BROWSING.md)
- [Scanning, filesystems, metadata and catalogue writes](flows/SCANNING_METADATA.md)
- [Search, Query Model and saved smart collections](flows/SEARCH_COLLECTIONS.md)
- [Slideshows and the background service](flows/SLIDESHOW_SERVICE.md)
- [Estuary integration, builds, GitHub Actions and releases](flows/SKIN_BUILD_RELEASE.md)

Start from the [data-flow index](flows/README.md) when you are unsure which one
applies.

## Your first local run

From the repository root:

```bash
python3 -m venv .venv
. .venv/bin/activate
python3 -m pip install --upgrade pip
python3 -m pip install -r requirements-dev.txt
python3 tools/verify.py
python3 -m pytest
python3 tools/build.py --skip-skin
```

On Windows PowerShell, activate the environment with:

```powershell
.venv\Scripts\Activate.ps1
```

The tests provide Kodi stubs, so most work can be developed without Kodi. A
real Kodi installation is still required for manual checks involving windows,
skin behaviour, playback, network sources or device-specific decoders.

## A good first contribution

Choose a contained issue with an existing nearby test. A useful first cycle is:

1. Create a focused branch.
2. Find the production file using the table above.
3. Find the closest test by searching for the route, class or method name.
4. Add or adjust the test.
5. Make the smallest production change that satisfies it.
6. Run the focused test, then the complete verification commands.
7. Review the diff and push the branch.
8. Open a pull request and confirm that GitHub Actions is green.

Detailed commands are in [Local development](LOCAL_DEVELOPMENT.md) and
[Publishing from a QNAP shell](QNAP_GITHUB.md).

## Version names that can look confusing

The project maintains several related versions:

- the MyPicsDB 3 plug-in version in `plugin.image.mypicsdb3/addon.xml`;
- the repository add-on version in `repository.mypicsdb3/addon.xml`;
- independent Estuary skin versions in `contrib/estuary/upstream.json`;
- the database schema version in `db/schema.py` and the migration history;
- the Query Model version in `query_model.py`.

These versions do not always change together. Do not bump the repository add-on
only because the plug-in changed, and do not modify a released migration
checksum.

## Where to ask questions

For a proposed large change, open a GitHub issue before writing the patch. State
which data flow is affected, what compatibility you expect to preserve, and
which automated and manual checks you plan to run. That gives maintainers a
small, concrete review surface instead of requiring them to reconstruct the
whole design from the patch.
