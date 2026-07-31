# Contributing

Thank you for helping improve MyPicsDB 3. Contributions can include code,
tests, documentation, Kodi compatibility reports, translations and review.

## Start with the contributor guide

New contributors should read:

1. [Start here: developing MyPicsDB 3](docs/START_HERE.md);
2. [Architecture](docs/ARCHITECTURE.md);
3. the relevant guide in the [data-flow index](docs/flows/README.md);
4. [Local development and GitHub workflow](docs/LOCAL_DEVELOPMENT.md).

Open an issue before starting a large change, a database-schema change, a public
widget-contract change or work that could alter scanner safety. Describe the
problem and expected compatibility before implementing a large solution.

## Development setup

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

Use `.venv\Scripts\Activate.ps1` to activate the environment in Windows
PowerShell.

Most automated tests use Kodi stubs and do not require a Kodi installation. A
real Kodi installation is still needed for manual checks involving windows,
skins, network sources, decoders and playback.

## Branch and pull request workflow

1. Fork the repository when you do not have write access.
2. Update your local `main` with `git pull --ff-only`.
3. Create one focused branch for one logical change.
4. Add or update a regression test when behaviour changes.
5. Run the relevant focused tests while developing.
6. Run the complete verification commands before pushing.
7. Review the staged diff for generated files, credentials, logs and private
   media.
8. Push the branch and open a pull request against `main`.
9. Confirm that GitHub Actions completes successfully.

Example:

```bash
git switch main
git pull --ff-only origin main
git switch -c fix/short-description

# edit files and run focused tests
python3 tools/verify.py
python3 -m pytest

git diff --check
git add -A
git diff --cached --check
git commit -m "Describe the change"
git push -u origin fix/short-description
```

## Pull request description

Include:

- the problem being solved;
- the affected data flow or components;
- user-visible or compatibility effects;
- automated checks run locally;
- manual Kodi checks completed or still required;
- schema, Query Model, settings, skin or release implications.

Keep pull requests small enough that a reviewer can follow the complete change
without reconstructing unrelated work.

## Design and safety expectations

- Keep Kodi-specific code behind the adapter/UI layer where practical.
- Widget routes must remain read-only and must never start scans.
- Preserve missing-source safety: incomplete or unavailable sources are not
  proof of deletion.
- Keep scanner cancellation, lock refresh and checkpoints safe.
- Use versioned database migrations; do not add ad-hoc DDL to
  `Catalog.initialize()`.
- Use the validated Query Model for dynamic or stored queries. Never expose raw
  SQL.
- Do not commit generated `build/`, `.cache/` or `dist/` output.
- Do not silently change public widget URLs or the skin integration contract.
- Do not change a released migration checksum.

See [Architecture](docs/ARCHITECTURE.md) for the complete invariants.

## Tests and checks

Minimum before pushing:

```bash
python3 tools/verify.py
python3 -m pytest
```

Also run a full build for skin, package, repository or release changes:

```bash
python3 tools/build.py
```

Run the MariaDB integration test when changing backend-neutral SQL, migrations,
locks or shared-catalogue behaviour. See
[Local development](docs/LOCAL_DEVELOPMENT.md#optional-mariadb-integration-test).

After pushing, inspect the pull request's **Checks** section or the repository's
**Actions** tab. The remote workflow matrix and MariaDB service test are part of
the contribution, not an optional follow-up.

## Documentation changes

Update documentation with the code:

- README for user-visible behaviour and installation;
- `docs/START_HERE.md` for the newcomer path;
- `docs/ARCHITECTURE.md` for component boundaries or invariants;
- `docs/flows/` for call paths;
- specialist documents for migrations, Query Model, search or skins;
- an ADR for a long-lived architectural decision;
- `CHANGELOG.md` and a patch report when preparing a release.

## Licensing

All contributions are accepted under GNU GPL version 2.
