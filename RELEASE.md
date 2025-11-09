# Release Process

This document describes how to create a new release of ppxai with automated executable builds.

## Automated Release (Recommended)

The GitHub Actions workflow will automatically build executables for all platforms when you push a version tag.

### Steps:

1. **Update version information** (if you have a version file or want to update CHANGELOG)

2. **Commit your changes:**
   ```bash
   git add .
   git commit -m "Release v1.0.0"
   ```

3. **Create and push a version tag:**
   ```bash
   git tag -a v1.0.0 -m "Release version 1.0.0"
   git push origin v1.0.0
   ```

4. **Wait for builds to complete:**
   - Go to your repository on GitHub
   - Click on "Actions" tab
   - Watch the "Build Executables" workflow run
   - It will build for Linux, macOS, and Windows simultaneously

5. **Release is created automatically:**
   - Once builds complete, a new GitHub Release is created
   - The release will include:
     - `ppxai-linux-amd64` - Linux executable
     - `ppxai-macos` - macOS executable (works on both Intel and Apple Silicon)
     - `ppxai-windows.exe` - Windows executable
   - Release notes are auto-generated from commits

6. **Edit the release (optional):**
   - Add a more detailed description
   - Add upgrade notes
   - Add screenshots or examples

## Manual Build and Release

If you prefer to build and release manually:

1. **Build on each platform:**

   **On macOS:**
   ```bash
   ./build.sh
   mv dist/ppxai dist/ppxai-macos
   ```

   **On Linux:**
   ```bash
   ./build.sh
   mv dist/ppxai dist/ppxai-linux-amd64
   ```

   **On Windows:**
   ```batch
   build.bat
   move dist\ppxai.exe dist\ppxai-windows.exe
   ```

2. **Create GitHub Release:**
   - Go to your repository on GitHub
   - Click "Releases" → "Create a new release"
   - Choose a tag (or create new tag like `v1.0.0`)
   - Upload the executables:
     - `ppxai-linux-amd64`
     - `ppxai-macos`
     - `ppxai-windows.exe`
   - Write release notes
   - Publish release

## Version Numbering

Use [Semantic Versioning](https://semver.org/):
- **Major** (v1.0.0 → v2.0.0): Breaking changes
- **Minor** (v1.0.0 → v1.1.0): New features, backward compatible
- **Patch** (v1.0.0 → v1.0.1): Bug fixes, backward compatible

## Pre-releases

For beta or release candidate versions:

```bash
git tag -a v1.0.0-beta.1 -m "Beta release"
git push origin v1.0.0-beta.1
```

Then edit the GitHub release and mark it as "pre-release".

## Testing Before Release

Before creating a release tag:

1. **Test locally:**
   ```bash
   ./build.sh  # or build.bat on Windows
   ./dist/ppxai
   ```

2. **Test basic functionality:**
   - Run the executable
   - Select a model
   - Send a test query
   - Check citations display
   - Test commands (/help, /model, /clear, /quit)

3. **Test on clean system (if possible):**
   - Copy executable to a machine without Python
   - Create .env file with API key
   - Run and verify it works

## Checklist Before Release

- [ ] All tests pass
- [ ] Documentation is up to date (README.md, CLAUDE.md, BUILD.md)
- [ ] CHANGELOG updated (if you maintain one)
- [ ] Version number updated (if stored anywhere)
- [ ] Built and tested locally on at least one platform
- [ ] API key setup is documented
- [ ] .env.example is up to date

## Troubleshooting Release Builds

### Build fails on GitHub Actions

Check the Actions tab for error logs. Common issues:
- Missing dependencies in requirements.txt
- PyInstaller version compatibility
- Hidden imports not specified in ppxai.spec

### Executables don't work

- Test locally first before releasing
- Check that all required data files are included in ppxai.spec
- Verify .env handling works in bundled mode

### Users report antivirus warnings

- This is common with PyInstaller executables
- Consider code signing (see BUILD.md)
- Add instructions for users to whitelist

## Release Announcement

After release, consider announcing on:
- Repository README
- Social media
- Community forums
- Product Hunt (for major releases)

## Rollback

If you need to rollback a release:

1. Delete the tag:
   ```bash
   git tag -d v1.0.0
   git push origin :refs/tags/v1.0.0
   ```

2. Delete or mark the GitHub release as draft
3. Fix the issues
4. Create a new patch version
