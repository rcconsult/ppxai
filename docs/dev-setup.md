# Development Setup

## File encoding

All source files MUST be UTF-8 encoded **without** BOM.

- Windows PowerShell's `Out-File` cmdlet adds BOM by default — avoid it.
- Use `Set-Content -Encoding UTF8` or write files via Python with `encoding='utf-8'`.
- The config loader uses `utf-8-sig` to handle BOM gracefully when reading.

## uv resolution (all platforms)

Use the system-installed `uv` if available, otherwise bootstrap `.uv/uv` via the project script.

**macOS / Linux:**
```bash
command -v uv >/dev/null 2>&1 || python scripts/bootstrap.py --all
export UV=$(command -v uv 2>/dev/null || echo ".uv/uv")

$UV sync --all-extras
$UV run ppxai
$UV run pytest tests/ -v
```

**Windows (cmd):**
```cmd
where uv >nul 2>&1 && set UV=uv || (python scripts\bootstrap.py --all && set UV=.uv\uv)
%UV% sync --all-extras
%UV% run ppxai
```

**Windows (PowerShell):**
```powershell
if (Get-Command uv -ErrorAction SilentlyContinue) { $UV = "uv" } else { python scripts\bootstrap.py --all; $UV = ".uv\uv" }
& $UV sync --all-extras
& $UV run ppxai
```

## Quick start

```bash
$UV sync --all-extras
cp .env.example .env
# edit .env, add API keys
$UV run ppxai           # Rich TUI
$UV run ppxaide         # Textual TUI
$UV run ppxai-server    # HTTP server for VSCode
$UV run pytest tests/ -v
```

Alternative (pip):
```bash
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
python ppxai.py
```

## Web UI development (`PPXAI_WEB_DIR`)

The web clients (`ppxai-server`, `ppxai-desktop`) serve the web UI from
`~/.ppxai/web` by default — **not** the source tree — so editing
`ppxai/web/...` has no effect until that dir is synced. While iterating, set
`PPXAI_WEB_DIR` to serve a checkout directly and skip the sync:

```bash
PPXAI_WEB_DIR=$PWD/ppxai/web $UV run ppxai-server   # serves live source; hard-refresh the browser
```

The override (`ppxai/server/routes/static.py::_resolve_web_ui_dir`) takes
precedence over `~/.ppxai/web`. See
[lessons/web-assets-served-from-ppxai-home.md](lessons/web-assets-served-from-ppxai-home.md)
for the full hazard (incl. the `.app` wrinkle).

## Browser E2E (Playwright)

Two suites live in `tests/e2e/`, and the difference matters:

```bash
cd tests/e2e && npm install          # first time only

npm test                              # widget specs — file:// harnesses, no server
npm run test:live                     # the REAL web app against a REAL server
PPXAI_E2E_PROVIDER=<provider> npm run test:live   # + live LLM steps
npm run test:live:headed              # same, with a visible browser
```

- **Default (`npm test`)** loads a static `*-harness.html` per spec and
  exercises one widget's logic in isolation. Fast, no server, no credentials.
- **Live (`npm run test:live`)** boots `.venv/…/ppxai-server` with
  `PPXAI_WEB_DIR` pointed at the checkout, so it tests THIS working tree
  rather than the installed binary or `~/.ppxai/web`. It covers what the
  harnesses structurally cannot: command-envelope round-trips, SSE, and the
  AppState-driven header badges. LLM-dependent assertions skip unless
  `PPXAI_E2E_PROVIDER` names a configured provider, so the suite stays green
  on a box with no credentials.

Playwright runs **headless** by default — no browser window appears even
though real Chromium is driving the page. Use the `:headed` variants (or
`npx playwright test --ui`) to watch it.

## Windows Store Python + uv/venv recovery (CRITICAL)

**Problem:** Windows Store Python prevents uv from creating temporary virtualenvs (Error 1920: "The file cannot be accessed by the system").

### Use existing venv with `$UV run`

```bash
# Use --no-sync to skip package rebuild
$UV run --no-sync python -m <command>

# Without --no-sync triggers temp virtualenv creation (fails on Windows Store Python)
```

### Check venv / lock status

```bash
$UV lock --check                                           # is lock fresh?
$UV pip list | grep ppxai                                  # installed version
.venv/Scripts/python.exe -c "import ppxai; print(ppxai.__version__)"
```

### Corporate proxy / TLS

```bash
# Use UV_NATIVE_TLS=true to use Windows native TLS (SChannel) — trusts system cert store
set UV_NATIVE_TLS=true            # cmd
$env:UV_NATIVE_TLS="true"         # PowerShell

$UV run python -m PyInstaller ppxai.spec --noconfirm
$UV pip install hatchling editables
```

`UV_NATIVE_TLS=true` tells uv to use the OS native TLS stack instead of bundled rustls. This trusts certificates from the Windows certificate store (including corporate proxy CAs). No need for `SSL_CERT_FILE`.

That covers **uv's own** downloads. ppxai's *runtime* outbound TLS (provider
calls, `fetch_url`, `web_search`) is separate and resolved by
`ppxai/config/tls.py`: `SSL_VERIFY` → `SSL_CERT_FILE` → `network.ssl.verify`
→ `network.ssl.cert_file` → system store. Setting the CA once in
`ppxai-config.json` is usually easier than an env var per shell:

```json
{ "network": { "ssl": { "cert_file": "/path/to/corporate-ca.pem" } } }
```

A custom CA is **added to** the system trust store, not substituted for it,
so a laptop moving between the corporate network and the open internet keeps
working. `/doctor` prints the resolved policy and the rule that produced it.

### Refresh package metadata after version bump

When version numbers change in source but venv metadata is stale:

```bash
$UV pip install hatchling editables
$UV pip install --no-build-isolation --reinstall --no-deps -e .
$UV pip list | grep ppxai
```

### Build binaries with PyInstaller

```bash
# Preferred: UV_NATIVE_TLS for corporate proxy environments
set UV_NATIVE_TLS=true && %UV% run python -m PyInstaller ppxai.spec --noconfirm

# Alternative: venv's Python directly
.venv/Scripts/python.exe -m PyInstaller ppxai.spec --noconfirm
```

### Key insights

- **Editable install:** changes to `.py` files reflect immediately without reinstall.
- **Metadata stale:** package metadata (version, dependencies) requires reinstall to update.
- **Lock file:** only needs refresh when `pyproject.toml` dependencies change, not for source code changes.
- **Windows Store Python:** fundamental limitation — uv cannot create temp virtualenvs from Store Python executables.
- **UV_NATIVE_TLS:** preferred over `SSL_CERT_FILE` — uses OS native TLS, no hardcoded cert paths.
- **Workaround:** use existing venv with `--no-sync` or `.venv/Scripts/python.exe` directly.
