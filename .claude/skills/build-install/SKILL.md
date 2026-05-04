---
name: build-install
description: Rebuild all four ppxai binaries (ppxai, ppxaide, ppxai-server, ppxai-desktop), the VSCode extension VSIX, and (on macOS) the .app + DMG, then install everything to system locations as a user-side install would. Cross-platform — covers macOS Apple Silicon, macOS Intel, Linux, and Windows. Use when the user asks to "rebuild and reinstall", "build and install", "redeploy locally", "install from DMG", or similar.
---

# build-install

End-to-end local install of ppxai. Build all binaries + VSCode extension
(+ macOS-only `.app` and DMG), then install everything to system
locations exactly as a user-side install would. Useful for testing a
branch before release, or for verifying a release artifact after CI
uploads it.

## Preconditions

### All platforms
- Working tree at the version you want to ship — version files already
  bumped (see `tests/test_version_consistency.py` for the SoT list).
- `uv` resolvable per CLAUDE.md "uv Resolution" (system or `.uv/uv`).
- `node` + `npm` for the VSCode extension build.
- A POSIX-ish shell. Bash works on all four platforms (macOS native,
  Linux native, Windows via Git Bash). PowerShell alternatives are
  noted where they meaningfully simplify Windows-only flows.

### Platform-specific
- **macOS Apple Silicon** — host is arm64. `uname -m` prints `arm64`.
  `create-macos-app.sh` writes `ppxai-X.Y.Z-macos-arm64.dmg`.
- **macOS Intel** — host is x86_64. `uname -m` prints `x86_64`.
  `create-macos-app.sh` writes `ppxai-X.Y.Z-macos-intel.dmg`. The
  alternate `scripts/build-intel.sh` orchestrates the same flow with
  upload-to-release support.
- **Linux** — `linux-amd64` is the only platform built today. Binaries
  install to `~/.local/bin/` (must be on `$PATH`).
- **Windows** — PyInstaller produces `.exe` suffixes automatically.
  Binaries install to `~/.ppxai/bin/` (NOT `~/.local/bin/`; see
  CLAUDE.md "Installation Locations"). `~/.ppxai/bin/` must be on
  `$env:PATH`. Easiest run-shell is Git Bash (matches steps below);
  PowerShell variants noted where useful.

## Platform matrix

Steps marked ✅ apply on the platform; ⛔ skip; macOS-only sections are
called out inline.

| Step | macOS arm64 | macOS Intel | Linux | Windows |
|------|:-:|:-:|:-:|:-:|
| 1. Reset + first PyInstaller build | ✅ | ✅ | ✅ | ✅ |
| 2. Three parallel PyInstaller builds | ✅ | ✅ | ✅ | ✅* |
| 3. VSCode extension VSIX | ✅ | ✅ | ✅ | ✅ |
| 4. macOS `.app` + DMG | ✅ | ✅ | ⛔ | ⛔ |
| 5. Install binaries | `~/.local/bin/` | `~/.local/bin/` | `~/.local/bin/` | `~/.ppxai/bin/` |
| 5b. Refresh `~/.ppxai/web/` | ✅ | ✅ | ✅ | ✅ |
| 6. DMG mount → `/Applications/` | ✅ | ✅ | ⛔ | ⛔ |
| 7. `code --install-extension` | ✅ | ✅ | ✅ | ✅ |
| 8. Version sanity checks | ✅ (5 binaries) | ✅ (5) | ✅ (4) | ✅ (4) |

\*Windows: PowerShell `&` is the call-operator, not bash background.
Use Git Bash for the parallel form, or run the three builds
sequentially under PowerShell with `Start-Job` (see step 2).

## Steps

The Bash form below is the canonical run; per-step Windows-PowerShell
notes are inline where they meaningfully differ.

### 1. Reset previous build artifacts and build the first binary

```bash
cd /path/to/ppxai
rm -rf build dist
uv run --no-sync pyinstaller ppxai.spec --noconfirm
```

The first build is run alone because PyInstaller initialises `build/`
state on the first invocation; subsequent builds share enough that
running them in parallel is safe.

**Windows PowerShell:**
```powershell
Set-Location C:\git\utils\ppxai
Remove-Item -Recurse -Force build, dist -ErrorAction SilentlyContinue
uv run --no-sync pyinstaller ppxai.spec --noconfirm
```

### 2. Build the remaining three binaries in parallel

```bash
uv run --no-sync pyinstaller ppxaide.spec --noconfirm        2>&1 | tail -2 &
uv run --no-sync pyinstaller ppxai-server.spec --noconfirm   2>&1 | tail -2 &
uv run --no-sync pyinstaller ppxai-desktop.spec --noconfirm  2>&1 | tail -2 &
wait
```

After completion, list the binaries:

```bash
# macOS / Linux
ls dist/{ppxai,ppxaide,ppxai-server,ppxai-desktop}

# Windows (Git Bash works the same; PowerShell below)
ls dist/ppxai*.exe
```

**Windows PowerShell (sequential — safe but slower):**
```powershell
uv run --no-sync pyinstaller ppxaide.spec --noconfirm
uv run --no-sync pyinstaller ppxai-server.spec --noconfirm
uv run --no-sync pyinstaller ppxai-desktop.spec --noconfirm
Get-ChildItem dist\*.exe
```

**Windows PowerShell (parallel via Start-Job):**
```powershell
$jobs = @(
  Start-Job { uv run --no-sync pyinstaller ppxaide.spec --noconfirm },
  Start-Job { uv run --no-sync pyinstaller ppxai-server.spec --noconfirm },
  Start-Job { uv run --no-sync pyinstaller ppxai-desktop.spec --noconfirm }
)
$jobs | Wait-Job | Receive-Job; $jobs | Remove-Job
```

All four binaries should appear in `dist/`. Each is roughly 33–40 MB
(macOS / Linux) or 35–45 MB (Windows .exe).

### 3. Build the VSCode extension VSIX

Wrap the whole thing in a subshell `( ... )` so the `cd` is scoped and
cannot leak to step 4. Earlier runs ate a `cd vscode-extension` that
persisted into step 4 — `bash scripts/create-macos-app.sh` then
failed with "No such file or directory" because the script lives at
the project root.

```bash
(cd vscode-extension && \
    { [ -d node_modules ] || npm install; } && \
    npm run compile && \
    npx vsce package --allow-missing-repository)
# subshell exits — parent cwd unchanged
```

What each line does:
- `[ -d node_modules ] || npm install` — only on first run / after dep bump
- `npm run compile` — esbuild → `dist/extension.js` (~107 KB minified)
- `npx vsce package --allow-missing-repository` — produces
  `vscode-extension/ppxai-X.Y.Z.vsix` (~128 KB)

Do NOT use a bare `cd vscode-extension && ...` chain without the
surrounding parens. The Bash tool persists the working directory
across calls; a leaked cwd silently breaks downstream steps.

**Windows PowerShell** uses `Push-Location` / `Pop-Location` instead of
the bash subshell:
```powershell
Push-Location vscode-extension
if (-not (Test-Path node_modules)) { npm install }
npm run compile
npx vsce package --allow-missing-repository
Pop-Location
```
`Pop-Location` runs even if the npm steps fail, restoring the parent
cwd. (Wrap in `try { ... } finally { Pop-Location }` if you want
guarantee even after `throw`.)

If `npm run compile` fails with `Cannot find module 'esbuild'`, the
v1.18.2 esbuild bundling rewrite never had `npm install` run on this
checkout — run `npm install` first. The size budget gate is 500 KB;
expected size is ~128 KB.

### 4. Build the macOS `.app` + DMG (macOS only)

⛔ Skip on Linux and Windows.

```bash
# Apple Silicon (arm64) and Intel both run the same script —
# uname -m is consulted internally for the DMG suffix.
bash scripts/create-macos-app.sh
```

Produces:
- `dist/ppxai.app` — macOS application bundle.
- `dist/ppxai-{version}-macos-{arm64|intel}.dmg` — DMG installer
  (~70-75 MB). The `arm64`/`intel` suffix comes from `uname -m`
  passed through `sed 's/x86_64/intel/'`.

For the macOS Intel cross-/native-build flow with auto-upload, the
older `scripts/build-intel.sh v<tag>` orchestrates steps 1-4 + uploads
the resulting binaries and DMG to a GitHub release. Use it when
preparing an Intel asset for an existing release tag.

### 5. Install binaries

The destination differs per platform — pick the row that matches your
host. Each path is taken verbatim from CLAUDE.md "Installation
Locations".

#### 5.macos / 5.linux — `~/.local/bin/`
```bash
mkdir -p ~/.local/bin
cp dist/ppxai dist/ppxaide dist/ppxai-server dist/ppxai-desktop ~/.local/bin/
chmod +x ~/.local/bin/{ppxai,ppxaide,ppxai-server,ppxai-desktop}  # PyInstaller usually sets this; harmless to repeat
```
Confirm `~/.local/bin/` is on `$PATH`. On Linux without a desktop
manager, you may need to add it to `~/.bashrc` or `~/.zshrc`:
```bash
[[ ":$PATH:" == *":$HOME/.local/bin:"* ]] || echo "$HOME/.local/bin missing from PATH"
```

#### 5.windows — `~/.ppxai/bin/`
The repo ships `scripts/install-local.ps1` which stops a running
`ppxai-server.exe`, creates the target dir, and copies three of the
four binaries (NB: it does NOT copy `ppxaide.exe` — copy it manually
if you want the Textual TUI).

```powershell
powershell -ExecutionPolicy Bypass -File scripts\install-local.ps1
# Then add ppxaide manually:
Copy-Item dist\ppxaide.exe -Destination "$env:USERPROFILE\.ppxai\bin\" -Force
```

Or via Git Bash:
```bash
mkdir -p ~/.ppxai/bin
cp dist/ppxai.exe dist/ppxaide.exe dist/ppxai-server.exe dist/ppxai-desktop.exe ~/.ppxai/bin/
```

Confirm `~/.ppxai/bin/` is on `$env:PATH`. CLAUDE.md notes Windows
also probes `~/AppData/Local/ppxai` — that's a search path, NOT an
install target. Don't install there.

### 5b. Refresh `~/.ppxai/web/` — server reads from disk, not bundle

`ppxai-server` reads the web UI from `~/.ppxai/web/` at request time
(see `ppxai/server/routes/static.py::WEB_UI_DIR`). `ppxai-desktop`
auto-installs that directory **only when it doesn't exist** —
subsequent launches don't refresh it. So a freshly-rebuilt server
binary still serves stale JS/CSS unless `~/.ppxai/web/` is also
synced. Caught on 2026-05-02 v1.18.3 build-install: Item 16's
`CompositeResult` handler in `web/shared/result-renderer.js` was
present in the binary AND the .app bundle, but the server still
served the old file because nobody refreshed the on-disk copy.

Universal across all platforms:

```bash
# macOS / Linux / Windows-via-Git-Bash
TS=$(date +%Y%m%d-%H%M%S)
[ -d ~/.ppxai/web ] && mv ~/.ppxai/web ~/.ppxai/web.backup.$TS
cp -R ppxai/web ~/.ppxai/web
```

**Windows PowerShell:**
```powershell
$ts = Get-Date -Format "yyyyMMdd-HHmmss"
$webPath = Join-Path $env:USERPROFILE ".ppxai\web"
if (Test-Path $webPath) {
    Move-Item $webPath "$webPath.backup.$ts"
}
Copy-Item -Recurse ppxai\web $webPath
```

The backup is per-run-timestamp and uses the same `.backup.*`
convention as `ppxai-config.json` backups, so cleanup is uniform.

If you only changed Python code (no `web/` edits), this step is a
no-op functionally — but it's cheap (~3 MB copy) and the alternative
is silent staleness.

### 6. Install the `.app` from the DMG (macOS only)

⛔ Skip on Linux and Windows.

When the user asks to "install the DMG" they mean running the install
flow that an end user would run — mount, copy, unmount. Don't just
`cp dist/ppxai.app /Applications/` (that bypasses the DMG):

```bash
DMG="dist/ppxai-$(grep '^version' pyproject.toml | head -1 | cut -d'"' -f2)-macos-$(uname -m | sed 's/x86_64/intel/').dmg"

# If a previous mount is still attached from `open <dmg>`, reuse it; otherwise mount.
MOUNT="/Volumes/ppxai Desktop"
if ! [ -d "$MOUNT" ]; then
    hdiutil attach "$DMG" -nobrowse
fi

rm -rf /Applications/ppxai.app
cp -R "$MOUNT/ppxai.app" /Applications/
hdiutil detach "$MOUNT"
```

Notes:
- The volume name from `create-macos-app.sh` is `ppxai Desktop` (with
  the space). Adjust if you change the script's `DISPLAY_NAME`.
- The `arm64`/`intel` suffix in the DMG name is from `uname -m`
  passed through the script; mirror that here so we pick the file
  that was actually built.

### 7. Install the VSCode extension

Universal across all platforms:

```bash
# macOS / Linux / Git Bash
code --install-extension vscode-extension/ppxai-*.vsix --force
```

```powershell
# Windows PowerShell — explicit path, no glob
code --install-extension (Resolve-Path vscode-extension\ppxai-*.vsix) --force
```

`--force` overwrites a previously-installed version of the same
extension. A fresh load of any open VS Code window picks up the new
build automatically; no restart needed.

If `code` is not on `$PATH` on Windows, ensure VS Code's `bin/` is
shimmed (some installers don't add it). On this user's setup,
`~/.bashrc` holds a `code` alias to the Microsoft VS Code shim.

### 8. Verify versions agree AND web sync took effect

#### macOS (5 binaries — includes the .app)
```bash
~/.local/bin/ppxai --version
~/.local/bin/ppxaide --version
~/.local/bin/ppxai-server --version
~/.local/bin/ppxai-desktop --version
/Applications/ppxai.app/Contents/MacOS/ppxai-desktop --version
```

#### Linux (4 binaries — no .app)
```bash
~/.local/bin/ppxai --version
~/.local/bin/ppxaide --version
~/.local/bin/ppxai-server --version
~/.local/bin/ppxai-desktop --version
```

#### Windows (4 binaries — no .app)
```bash
# Git Bash
~/.ppxai/bin/ppxai.exe --version
~/.ppxai/bin/ppxaide.exe --version
~/.ppxai/bin/ppxai-server.exe --version
~/.ppxai/bin/ppxai-desktop.exe --version
```

```powershell
# PowerShell
& "$env:USERPROFILE\.ppxai\bin\ppxai.exe" --version
& "$env:USERPROFILE\.ppxai\bin\ppxaide.exe" --version
& "$env:USERPROFILE\.ppxai\bin\ppxai-server.exe" --version
& "$env:USERPROFILE\.ppxai\bin\ppxai-desktop.exe" --version
```

All four (or five on macOS) should print the same `X.Y.Z`. If
`ppxai-desktop` reports a stale version, the v1.17.7 fix (PyInstaller
hidden-import for `ppxai.version`) regressed — investigate before
shipping.

Then sanity-check the on-disk web sync against a known-recent string.
Pick something from `ppxai/web/` that you know was added in this
branch — e.g. for v1.18.3 Item 16, `CompositeResult` was added to
`result-renderer.js`:

```bash
diff -q ppxai/web/shared/result-renderer.js ~/.ppxai/web/shared/result-renderer.js
# Expected: no output (files identical)
```

```powershell
# Windows PowerShell
$src = Get-FileHash ppxai\web\shared\result-renderer.js
$dst = Get-FileHash "$env:USERPROFILE\.ppxai\web\shared\result-renderer.js"
if ($src.Hash -ne $dst.Hash) { Write-Warning "web sync mismatch — re-run step 5b" }
else { "web sync OK" }
```

If `diff` reports a difference (or PowerShell hashes differ), step
5b didn't run or didn't take — re-run it before claiming the install
is complete. A 0-output diff / matching hash proves the on-disk copy
matches what the binaries expect.

## Don't

- Don't sign the DMG / .app from this skill — code signing is a
  separate release-CI step. This is a local-test build.
- Don't push or tag from here — that's `/release v1.x.y`.
- Don't run the macOS-only sections (4, 6) on Linux or Windows; they
  fail outright (`hdiutil`, `/Applications/`, `.app` bundle don't exist).
- Don't bypass the platform install path — Windows ships to
  `~/.ppxai/bin/`, macOS / Linux ship to `~/.local/bin/`. Mixing leaks
  binaries into search-path-only locations and the launcher won't find
  them. CLAUDE.md "Installation Locations (CRITICAL)" is the SoT.
- Don't `cp dist/ppxai.app /Applications/` instead of mounting the
  DMG. Mount-and-copy is what end users do; copying the staging dir
  bypasses any DMG-time integrity checks.

## When to extend

If the build flow changes (new spec file, new platform, new asset),
update this skill and the `tests/test_version_consistency.py` sentinel
in the same commit so they stay in sync. The CLAUDE.md "Files Updated
by Release Script" table is the canonical list of touched files.

If a new platform is added (e.g. Linux ARM, FreeBSD), add a row to the
"Platform matrix" table at the top, a section under "Preconditions",
and per-platform variants under steps 5 and 8. Treat the macOS-only
DMG/app flow (steps 4, 6) as a template if the new platform has its
own bundle format (e.g. AppImage on Linux, MSI on Windows).
