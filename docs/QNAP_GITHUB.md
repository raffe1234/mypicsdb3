# Publish MyPicsDB 3 from a QNAP shell

These commands assume:

- the archive is in `/share/Public/Temp/work/Github`;
- the GitHub account is `raffe1234`;
- an empty GitHub repository named `mypicsdb3` already exists;
- SSH authentication to GitHub already works on the QNAP.

## First publication

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
The included workflow will build and publish the Kodi repository files.

After the main-branch workflows pass, create the first release:

```bash
cd /share/Public/Temp/work/Github/mypicsdb3

git tag -a v0.1.0 -m "MyPicsDB 3 0.1.0"
git push origin v0.1.0
```

The release workflow verifies the project, runs tests, builds all archives and
attaches them to the GitHub release.

## Later updates with a supplied patch

The QNAP does not need Python, pytest or the Kodi skin builder. Run those checks
in GitHub Actions. Apply the supplied version-to-version patch from the parent
directory and inspect the staged change before committing:

```bash
cd /share/Public/Temp/work/Github/mypicsdb3

git status --short --branch
git pull --ff-only origin main
git log -3 --oneline --decorate

sha256sum ../mypicsdb3-X-from-Y.patch
git apply --check ../mypicsdb3-X-from-Y.patch
git apply ../mypicsdb3-X-from-Y.patch

git diff --check
git diff --stat
git status --short

git add -A
git diff --cached --check
git diff --cached --stat

git commit -m "Prepare MyPicsDB 3 vX"
git push origin main
```

Wait for the GitHub test and package workflows to pass, then tag the exact
commit:

```bash
git tag -a vX -m "MyPicsDB 3 vX"
git push origin vX
```

Use `--ff-only` rather than rebasing a dirty work tree. If `git apply --check`
fails, stop and compare the checked-out version with the patch's `from-Y`
version instead of forcing the patch. The repository add-on version changes
only when `repository.mypicsdb3` itself changes.
