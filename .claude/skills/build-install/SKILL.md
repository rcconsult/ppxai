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
- **Build venv MUST have the `[data]` extras.** The office-preview pipeline
  needs `pypdfium2` (PDF→PNG) + `python-pptx`/`openpyxl`, which live in the
  `[data]` optional extra. Step 1 runs `uv sync --all-extras` to guarantee it.
  Without it the binaries build fine but ship **WITHOUT office support** —
  LibreOffice is detected yet `render_pptx_slides` returns `[]` → "No slides
  rendered" (caught live 2026-06-14). Matches the CI build
  (`.github/workflows/build.yml`) and the release-script test step, both of
  which use `--all-extras`.
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
# Sync the build venv with ALL extras FIRST so the office-preview deps
# (pypdfium2 / python-pptx / openpyxl) are present. The per-build
# `--no-sync` below then reuses this env; without this sync it would build
# against whatever happens to be installed and silently drop office support.
uv sync --all-extras
rm -rf build dist
uv run --no-sync pyinstaller ppxai.spec --noconfirm
```

The first build is run alone because PyInstaller initialises `build/`
state on the first invocation; subsequent builds share enough that
running them in parallel is safe. The `uv sync --all-extras` runs once
up front; every `pyinstaller` invocation uses `--no-sync` to reuse that
synced env (re-syncing per build is wasted work and can race).

**Windows PowerShell:**
```powershell
Set-Location C:\git\utils\ppxai
uv sync --all-extras   # bundle the [data] office-preview deps (see Bash note above)
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

Two gotchas that the obvious form trips on, both verified 2026-05-10
on this checkout (rtk 0.39.0, PowerShell 7.6.1):

1. **Don't put `Start-Job { ... }` calls inside a comma-separated array
   literal.** PowerShell parses the comma-list as one big call with
   multiple `-ScriptBlock` arguments and errors with `Cannot bind
   parameter because parameter 'Name' is specified more than once`.
   Assign each job to its own variable first, then build the array.
2. **`Start-Job` runs the scriptblock in a fresh PowerShell child
   process with CWD = `$HOME`.** A bare `uv run ...` inside the
   scriptblock won't find `.\.uv\uv.exe` because the child isn't in
   the project dir. Pass the working directory in via `-ArgumentList`
   and `Set-Location` before invoking `uv`.

Use this form, which works:

```powershell
$wd = (Get-Location).Path
$j1 = Start-Job -Name ppxaide -ScriptBlock {
    param($wd) Set-Location $wd
    .\.uv\uv.exe run --no-sync pyinstaller ppxaide.spec --noconfirm
} -ArgumentList $wd
$j2 = Start-Job -Name server -ScriptBlock {
    param($wd) Set-Location $wd
    .\.uv\uv.exe run --no-sync pyinstaller ppxai-server.spec --noconfirm
} -ArgumentList $wd
$j3 = Start-Job -Name desktop -ScriptBlock {
    param($wd) Set-Location $wd
    .\.uv\uv.exe run --no-sync pyinstaller ppxai-desktop.spec --noconfirm
} -ArgumentList $wd
$jobs = $j1, $j2, $j3
$jobs | Wait-Job | Out-Null
foreach ($j in $jobs) { "=== $($j.Name) ==="; Receive-Job -Job $j | Select-Object -Last 2 }
$jobs | Remove-Job
```

Replace `.\.uv\uv.exe` with `uv` if you have a system uv on PATH.
Verified parallel run: ~84s for the three binaries on this machine
vs ~159s for the first sequential build, so parallelization is
working as intended. Use `Get-Job` to inspect state mid-run.

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

**Every** client (`ppxai-server`, `ppxai-desktop`, and `uv run` alike)
serves the web UI from `~/.ppxai/web/` at request time — NOT from the
PyInstaller bundle and NOT from the source tree (see
`ppxai/server/routes/static.py::_resolve_web_ui_dir`). So a freshly-rebuilt
binary still serves stale JS/CSS unless `~/.ppxai/web/` is also synced.
Caught on 2026-05-02 v1.18.3 build-install: Item 16's `CompositeResult`
handler in `web/shared/result-renderer.js` was present in the binary AND
the .app bundle, but the server still served the old file because nobody
refreshed the on-disk copy.

> **Web-dev shortcut (v1.19.0):** set `PPXAI_WEB_DIR` to serve a checkout
> directly and skip this sync entirely while iterating —
> `PPXAI_WEB_DIR=$PWD/ppxai/web ~/.local/bin/ppxai-server` (or with
> `uv run ppxai-server`). The override takes precedence over `~/.ppxai/web`.
> Do the real sync below for the actual install.

> **Correction (was wrong before 2026-06-19):** an earlier version of this
> step claimed `ppxai-desktop` "auto-installs `~/.ppxai/web/` only when it
> doesn't exist — subsequent launches don't refresh it." There is **no such
> installer in the code** — nothing in `ppxai/` (nor the ppxai-desktop `.app`,
> which has no launcher wrapper) copies `Contents/Resources/web` into
> `~/.ppxai/web/`. The `.app` ships a build-time copy at
> `Contents/Resources/web` that is **not consulted at runtime** (`WEB_UI_DIR`
> is hardcoded to `~/.ppxai/web`). During a v1.19.0 web trial, `~/.ppxai/web/`
> was *observed* reverting to the `.app`'s build-time snapshot after launching
> the `.app` (the served `index.html` mtime matched the bundle and a
> newer file vanished), but the mechanism was **not located in code** — treat
> it as unconfirmed. Practical rule: **don't trial web changes against the
> `.app`**; use `PPXAI_WEB_DIR` or sync `~/.ppxai/web/` and run
> `ppxai-server`/`ppxai-desktop` instead. Re-sync after the `.app` runs.

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
# macOS / Linux / Git Bash — version-pinned (avoids the multi-VSIX
# glob hazard documented below).
VER=$(grep '^version' pyproject.toml | head -1 | cut -d'"' -f2)
code --install-extension "vscode-extension/ppxai-$VER.vsix" --force
```

```powershell
# Windows PowerShell — explicit version-pinned path (no glob).
# Resolve the CLI shim explicitly because plain `code` may resolve
# to Code.exe (the GUI) which rejects --install-extension with
# `bad option`.
$codeCli = "$env:LOCALAPPDATA\Programs\Microsoft VS Code\bin\code.cmd"
if (-not (Test-Path $codeCli)) {
    # Fallback: assume `code` is the proper shim
    $codeCli = "code"
}
# Pin to the version we just built — derived from pyproject.toml so
# the install always matches the build, and stale older VSIXes
# lingering in the directory don't get picked up first.
$ver = (Select-String -Path pyproject.toml -Pattern '^version = "(.+)"').Matches[0].Groups[1].Value
$vsix = "vscode-extension\ppxai-$ver.vsix"
if (-not (Test-Path $vsix)) { throw "Expected VSIX not found: $vsix" }
& $codeCli --install-extension $vsix --force

# Optional cleanup — delete older VSIXes from the directory so the
# Bash glob form below doesn't trip on them on future builds.
Get-ChildItem vscode-extension\ppxai-*.vsix | Where-Object {
    $_.Name -ne "ppxai-$ver.vsix"
} | Remove-Item -Force
```

`--force` overwrites a previously-installed version of the same
extension. A fresh load of any open VS Code window picks up the new
build automatically; no restart needed.

If `code` is not on `$PATH` on Windows, ensure VS Code's `bin/` is
shimmed (some installers don't add it). On this user's setup,
`~/.bashrc` holds a `code` alias to the Microsoft VS Code shim.

**Windows gotcha — `code` may resolve to the GUI binary.** If your
PATH includes the VS Code install root before its `bin/` subdirectory,
plain `code` resolves to `Code.exe` (the GUI exe) which rejects
`--install-extension` with `Code.exe: bad option: --install-extension`.
The PowerShell snippet above handles this by going straight to
`bin\code.cmd`. On Git Bash, `~/.bashrc` typically aliases `code` to
the shim; verify with `type code` if the install fails.

**Multi-VSIX gotcha — `ppxai-*.vsix` glob picks the OLDEST.**
Caught 2026-05-15 v1.18.6 build-install: the directory had
`ppxai-1.18.2.vsix`, `ppxai-1.18.3.vsix`, `ppxai-1.18.4.vsix`, AND
`ppxai-1.18.6.vsix`. `Resolve-Path ppxai-*.vsix` returns an array,
PowerShell collapses it into space-separated args, and `code.cmd`
installs only the FIRST (which alphabetically is the oldest
version). The same hazard applies to the Bash form above. The
version-pinned snippet here avoids it. The Bash form should
similarly be updated to pin: `code --install-extension
"vscode-extension/ppxai-$(grep '^version' pyproject.toml | cut -d'\"' -f2).vsix" --force`.

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

#### Office-preview acceptance (catches a missing-`[data]` build)

A binary built without the `[data]` extras builds and runs fine but
returns "No slides rendered" for PPTX preview — the silent failure the
Step-1 `uv sync --all-extras` exists to prevent. Confirm the *installed
server* can actually rasterize a slide (needs LibreOffice on the host —
on macOS the v1.18.8 resolver finds `/Applications/LibreOffice.app`
without a symlink):

```bash
# macOS / Linux
( ~/.local/bin/ppxai-server >/tmp/srv.log 2>&1 & )
for i in $(seq 1 25); do curl -s -m2 -o /dev/null http://127.0.0.1:54320/status && break; sleep 0.5; done
PPTX="/path/to/any.pptx"   # any .pptx in a workdir
curl -s -m120 -o /tmp/s.png -w "%{http_code} %{content_type}\n" \
    "http://127.0.0.1:54320/files/preview?path=$PPTX&slide=1"
file /tmp/s.png   # expect: PNG image data
```

Expect `200 image/png` and a real PNG. If you instead get a JSON
`text_fallback` saying "install LibreOffice … or `pip install
'ppxai[data]'`", the build is missing `[data]` (rebuild after
`uv sync --all-extras`) OR LibreOffice isn't installed/discoverable.

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
