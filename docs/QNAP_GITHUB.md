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

## Later updates

```bash
cd /share/Public/Temp/work/Github/mypicsdb3

git pull --rebase
# Edit files and run tests.
python3 tools/verify.py
python3 -m pytest
python3 tools/build.py

git add -A
git status
git commit -m "Describe the change"
git push
```

For a new release, update the version first:

```bash
python3 tools/set_version.py 0.2.0
# Update CHANGELOG.md, test, commit and push.
git tag -a v0.2.0 -m "MyPicsDB 3 0.2.0"
git push origin v0.2.0
```
