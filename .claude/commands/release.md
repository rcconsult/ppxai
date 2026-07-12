# Release Workflow

Automated release for ppxai using `scripts/release.py`.

## Arguments
- `$ARGUMENTS` - Version number (e.g., v1.11.8)

## Usage

Run the release script:

```bash
python scripts/release.py $ARGUMENTS
```

The script handles everything automatically:
1. ✅ Checks git status (clean working directory)
2. ✅ Checks branch (must be on master, use `--force` to release from feature branch)
3. ✅ Merges to master (if on feature branch with `--force`)
4. ✅ Updates ALL version references:
   - pyproject.toml
   - ppxai/__init__.py
   - vscode-extension/package.json
   - vscode-extension/package-lock.json
   - ppxai/common/event_handler.py
   - README.md (vsix references)
   - vscode-extension/README.md (vsix references)
   - CLAUDE.md (current version + version alignment)
   - ROADMAP.md (current release)
5. ✅ Validates all version references with validate-release.py
6. ✅ Creates release notes template if missing
7. ✅ Runs TypeScript lint on VSCode extension
8. ✅ Runs tests
9. ✅ Creates commit and tag
10. ✅ Pushes to GitHub (always pushes master branch)
11. ✅ Waits for CI to complete
12. ✅ Publishes release notes to GitHub release
13. ✅ Builds Intel Mac assets (auto-detects platform)
14. ✅ Verifies all assets are present

## Script Options

```bash
# Dry run - show what would be done without making changes
python scripts/release.py v1.11.8 --dry-run

# Skip tests (use with caution)
python scripts/release.py v1.11.8 --skip-tests

# Don't wait for CI (useful if you'll check manually)
python scripts/release.py v1.11.8 --skip-ci-wait

# Force release from feature branch (merges to master first)
python scripts/release.py v1.11.8 --force

# REDO: Delete broken release and rebuild from scratch
python scripts/release.py v1.11.8 --redo
```

## Redo a Broken Release

If something went wrong with a release, use `--redo` to:
1. Delete the GitHub release
2. Delete the remote and local tags
3. Reset master if the last commit was the release commit
4. Then proceed with a fresh release

```bash
# Redo a broken release
python scripts/release.py v1.11.7 --redo

# Redo with force (if you have local changes to include)
python scripts/release.py v1.11.7 --redo --force
```

## Before Running

1. **Edit release notes** - The script creates a template at `docs/release-notes-v{version}.md`
   - Fill in the summary, features, and bug fixes before running
   - Or run with `--dry-run` first to create the template

2. **Update CHANGELOG.md** - Add an entry for the new version manually

3. **Review ROADMAP.md** - The script updates "Current Release" version, but you may want to update the content

## After Running

1. **Verify the release** - Check https://github.com/rcconsult/ppxai/releases/tag/v{version}

Note: Intel Mac builds are now automatic. If you run the release on an Intel Mac, the script will detect the platform and build/upload the Intel binaries automatically.

## Manual Override

If the script fails partway through, you can continue manually:

```bash
# If commit was created but not pushed:
git push origin master
git push origin v{version}

# If CI completed but release notes not published:
unset GITHUB_TOKEN && source .github/gh-tokenv.env && export GH_TOKEN
gh release edit v{version} --notes-file docs/release-notes-v{version}.md

# To view release status:
gh release view v{version}
```

## Troubleshooting

**"Git working directory is not clean"**
- Commit or stash your changes first
- Or use `--force` if you know what you're doing

**"Tests failed"**
- Fix the failing tests before releasing
- Or use `--skip-tests` if you've already verified tests pass

**"CI timeout"**
- Check GitHub Actions manually: https://github.com/rcconsult/ppxai/actions
- Once CI passes, manually publish release notes

**"Missing assets"**
- Intel Mac builds require running `build-intel.sh` on a Mac
- Other missing assets indicate CI failure

**"Tests failed in CI but pass locally"**
- Check if test relies on registration order or other non-deterministic behavior
- Fix the test and push to master
- CI failure prevents asset builds, but release is already created
- Option 1: Manual build and upload (see below)
- Option 2: Create patch release (v1.X.Y+1) with test fix

## Manual Build & Upload

If CI fails after release is created, manually build and upload assets:

```bash
# On Linux/macOS
cd scripts
./build-all.sh v1.15.2

# On Windows
cd scripts
.\build-windows.ps1 -Version v1.15.2

# Upload assets
cd ..
gh release upload v1.15.2 dist/ppxai-*
gh release upload v1.15.2 dist/ppxaide-*
gh release upload v1.15.2 dist/ppxai-server-*
gh release upload v1.15.2 dist/ppxai-desktop-*
gh release upload v1.15.2 vscode-extension/ppxai-*.vsix

# Verify
gh release view v1.15.2 --json assets --jq '.assets[].name'
```
