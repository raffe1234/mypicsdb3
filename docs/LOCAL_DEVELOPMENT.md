# Local development and GitHub workflow

This guide covers a normal contributor workflow from cloning the repository to
checking GitHub Actions. For the architecture first, read
[Start here](START_HERE.md). For owner-specific commands on a QNAP/NAS, see
[Publish from a QNAP shell](QNAP_GITHUB.md).

## Prerequisites

Recommended tools:

- Git;
- Python 3.11 for the main local environment;
- a Python virtual environment;
- Docker only when running the optional MariaDB integration test locally;
- Kodi 21 Omega or Kodi 22 Piers for manual integration checks.

CI also runs unit tests on the Python versions listed in
`.github/workflows/ci.yml`. Do not assume that code tested only on one local
Python version is sufficient.

## Clone and create a branch

A contributor normally forks the repository in GitHub, clones the fork and adds
the original repository as `upstream`:

```bash
git clone git@github.com:YOUR-NAME/mypicsdb3.git
cd mypicsdb3
git remote add upstream https://github.com/raffe1234/mypicsdb3.git
git fetch upstream
git switch main
git pull --ff-only upstream main
git push origin main
git switch -c docs/clear-developer-onboarding
```

The repository owner can clone the main repository directly:

```bash
git clone git@github.com:raffe1234/mypicsdb3.git
cd mypicsdb3
git switch -c docs/clear-developer-onboarding
```

Use a branch name that describes one change. Avoid mixing unrelated cleanup,
features and formatting in the same pull request.

## Create the Python environment

Linux, macOS and most NAS shells:

```bash
python3 -m venv .venv
. .venv/bin/activate
python3 -m pip install --upgrade pip
python3 -m pip install -r requirements-dev.txt
```

Windows PowerShell:

```powershell
py -3.11 -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements-dev.txt
```

The virtual environment is ignored by Git.

## Run a first verification

```bash
python3 tools/verify.py
python3 -m pytest
python3 tools/build.py --skip-skin
```

What these commands cover:

- `tools/verify.py` checks source/package structure, manifests, versions and
  repository contracts;
- `pytest` runs the normal automated suite with Kodi stubs;
- `tools/build.py --skip-skin` builds plug-in and repository output without
  downloading official Estuary source.

A full build is required before changes that affect Estuary integration,
repository generation or releases:

```bash
python3 tools/build.py
```

The full build may download pinned official Kodi archives. Generated `build/`,
`.cache/` and `dist/` output must not be committed.

## Run focused tests while editing

Examples:

```bash
python3 -m pytest tests/test_utils_router.py
python3 -m pytest tests/test_scanner.py -q
python3 -m pytest tests/test_query_model.py -k validation
python3 -m pytest tests/test_slideshow.py tests/test_mixed_slideshow_monitor.py
```

Search for the method, route or setting name to find nearby tests:

```bash
git grep -n "recent-taken"
git grep -n "scan_sources"
git grep -n "home_widget_limit"
```

Prefer adding a regression test close to the existing tests for that component.

## Test without Kodi

Most tests do not require Kodi. `tests/conftest.py` installs controlled stubs for
modules such as `xbmc`, `xbmcgui`, `xbmcplugin`, `xbmcaddon` and `xbmcvfs`.

This means you can test:

- routing and list-item construction;
- database and migration behaviour;
- source scanning with fake or local filesystems;
- settings and shared Kodi window properties;
- service scheduling and cancellation;
- playlist JSON-RPC behaviour.

A real Kodi installation is still needed for final checks involving:

- active windows, focus and view modes;
- the Estuary home screen;
- SMB/NFS behaviour and authentication;
- actual EXIF/IPTC decoder combinations;
- picture and video player differences between Kodi platforms;
- installation and update packages.

## Optional MariaDB integration test

```bash
docker compose -f dev/docker-compose.yml up -d
export MYPICSDB3_MYSQL_HOST=127.0.0.1
export MYPICSDB3_MYSQL_PORT=3307
export MYPICSDB3_MYSQL_DATABASE=mypicsdb3
export MYPICSDB3_MYSQL_USERNAME=mypicsdb3
export MYPICSDB3_MYSQL_PASSWORD=mypicsdb3
python3 -m pytest tests/test_mysql_integration.py
```

Stop the local service afterwards:

```bash
docker compose -f dev/docker-compose.yml down
```

GitHub runs a separate MariaDB workflow for pushes and pull requests.

## Review your change before committing

```bash
git status --short --branch
git diff --check
git diff --stat
git diff
```

Then stage and inspect exactly what will be committed:

```bash
git add -A
git diff --cached --check
git diff --cached --stat
git diff --cached
```

Do not stage local databases, logs, generated builds, credentials or media
samples containing private data.

## Commit and push

```bash
git commit -m "Improve developer onboarding documentation"
git push -u origin docs/clear-developer-onboarding
```

For later updates on the same branch:

```bash
git add -A
git commit -m "Clarify GitHub Actions checks"
git push
```

## What to do in GitHub after pushing

1. Open the repository and select **Pull requests**.
2. Create a pull request from your branch to `raffe1234/mypicsdb3:main`.
3. In the description, explain the problem, the changed data flow or documents,
   and the checks you ran.
4. Open the **Checks** section on the pull request, or the repository's
   **Actions** tab.
5. Confirm that at least the normal **CI** and **MariaDB integration** workflows
   complete successfully. A change affecting builds may also exercise Pages,
   release or Estuary workflows at the appropriate time.
6. Open any failed job, expand the first failed step and correct the cause in a
   new commit on the same branch.
7. Wait for review and merge. Do not create a release tag for an ordinary pull
   request.

GitHub's public Actions page is the source of truth for remote checks. A green
local run is necessary but does not replace the workflow matrix and service
containers used by CI.

## Optional GitHub CLI commands

When the `gh` command is installed and authenticated:

```bash
gh pr create --fill
gh pr checks --watch
gh run list --limit 10
gh run view --log-failed
```

These commands are optional. The same information is available in the GitHub
web interface.

## Updating a branch after main changes

Keep the working tree clean, then update without rewriting published history
unless the maintainer specifically requests it:

```bash
git status --short
git fetch upstream
git merge --ff-only upstream/main
```

If a fast-forward is not possible, merge `upstream/main` into the feature branch
or discuss the preferred rebase policy in the pull request. Never force-push
`main`.

## Owner workflow for a very small change

The safer default is still a branch and pull request. When the repository owner
intentionally makes a small, reviewed change directly on `main`:

```bash
git switch main
git pull --ff-only origin main
python3 tools/verify.py
python3 -m pytest
git add -A
git diff --cached --check
git commit -m "Clarify developer documentation"
git push origin main
```

Then open **Actions** and wait for the main-branch workflows to turn green.
Create a version tag only as part of an intentional release, after the release
checklist in `docs/DEVELOPMENT.md` has been completed.

## Short command list

For a normal documentation or code branch:

```bash
git switch main
git pull --ff-only origin main
git switch -c <type>/<short-description>

# edit files
python3 tools/verify.py
python3 -m pytest

git diff --check
git status --short
git add -A
git diff --cached --check
git commit -m "Describe the change"
git push -u origin <type>/<short-description>
```

Then create a pull request and check **Actions** or pull-request **Checks**.
