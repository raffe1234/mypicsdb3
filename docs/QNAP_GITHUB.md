# Publish MyPicsDB 3 from a QNAP shell

This page contains compact Git commands for the repository owner and for
applying a supplied patch on a QNAP/NAS. General contributors should use a
branch and pull request as described in
[Local development](LOCAL_DEVELOPMENT.md).

The examples assume:

- the working directory is `/share/Public/Temp/work/Github/mypicsdb3`;
- the GitHub account is `raffe1234`;
- SSH authentication to GitHub already works on the QNAP.

## Normal small update from the NAS

Use this when files have already been edited in the existing checkout:

```bash
cd /share/Public/Temp/work/Github/mypicsdb3

git status --short --branch
git pull --ff-only origin main
git log -3 --oneline --decorate

# inspect the edited files
git diff --check
git diff --stat
git status --short

git add -A
git diff --cached --check
git diff --cached --stat

git commit -m "Improve developer onboarding documentation"
git push origin main
```

Then open the repository in GitHub:

1. Select **Actions**.
2. Open the newest run for the pushed commit.
3. Confirm that **CI** and **MariaDB integration** are green.
4. Open the first failed step if a workflow is red; fix the cause in a new
   commit rather than creating a release tag.

The QNAP does not need to run Python or the Kodi skin builder when those tools
are unavailable. GitHub Actions performs the authoritative remote checks. When
Python is available on the NAS, running `python3 tools/verify.py` and
`python3 -m pytest` before the commit is still recommended.

## Safer branch and pull request from the NAS

A branch is preferred for a larger documentation change or any code change:

```bash
cd /share/Public/Temp/work/Github/mypicsdb3

git switch main
git pull --ff-only origin main
git switch -c docs/developer-onboarding

# edit or apply files
git diff --check
git status --short
git add -A
git diff --cached --check
git commit -m "Improve developer onboarding documentation"
git push -u origin docs/developer-onboarding
```

In GitHub, open **Pull requests**, create a pull request into `main`, and review
the **Checks** section. Merge only after the workflows are green and the diff
has been reviewed.

## Apply a supplied patch

Place the patch in the parent directory, then apply it only to a clean and
up-to-date checkout:

```bash
cd /share/Public/Temp/work/Github/mypicsdb3

git status --short --branch
git pull --ff-only origin main
git log -3 --oneline --decorate

sha256sum ../mypicsdb3-onboarding-docs.patch
git apply --check ../mypicsdb3-onboarding-docs.patch
git apply ../mypicsdb3-onboarding-docs.patch

git diff --check
git diff --stat
git status --short
```

Commit directly to `main` only when that is intentional:

```bash
git add -A
git diff --cached --check
git diff --cached --stat
git commit -m "Improve developer onboarding documentation"
git push origin main
```

Or create a branch before applying the patch:

```bash
git switch -c docs/developer-onboarding
# run git apply --check and git apply as above
git add -A
git commit -m "Improve developer onboarding documentation"
git push -u origin docs/developer-onboarding
```

If `git apply --check` fails, stop. Confirm that the checkout matches the version
for which the patch was created. Do not force the patch with rejected hunks or
manual partial application without reviewing the resulting documentation.

## Optional GitHub CLI checks

Only when the `gh` command is installed and authenticated:

```bash
gh run list --limit 10
gh run watch
gh run view --log-failed
```

The GitHub web interface provides the same status when `gh` is not installed.

## First publication

These older bootstrap commands are retained for a completely new checkout and
empty GitHub repository:

```bash
cd /share/Public/Temp/work/Github

tar -xzf mypicsdb3-0.1.0.tar.gz
mv mypicsdb3-0.1.0 mypicsdb3
cd mypicsdb3

git init
git checkout -b main
git remote add origin git@github.com:raffe1234/mypicsdb3.git

git add -A
git status
git commit -m "Initial MyPicsDB 3 Omega release candidate"
git push -u origin main
```

In GitHub, open **Settings > Pages** and select **GitHub Actions** as the source.
The included workflow builds and publishes the Kodi repository files.

## Release tags

Do not create a tag for an ordinary documentation or code update. For an
intentional release, first complete the release checklist in
`docs/DEVELOPMENT.md`, push `main`, and wait for the exact commit's workflows to
pass.

Then create and push the annotated tag:

```bash
cd /share/Public/Temp/work/Github/mypicsdb3

git switch main
git pull --ff-only origin main
git log -1 --oneline --decorate

git tag -a vX.Y.Z -m "MyPicsDB 3 X.Y.Z"
git push origin vX.Y.Z
```

The release workflow verifies, tests and builds the packages again and attaches
the archives to the GitHub release. The repository add-on version changes only
when `repository.mypicsdb3` itself changes.
