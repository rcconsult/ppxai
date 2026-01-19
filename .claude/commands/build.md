# Build and Install

Build ppxai binaries and VSCode extension for the current platform and install locally.

## Arguments
- `$ARGUMENTS` - Optional: `binaries`, `extension`, or `all` (default: `all`)

## Usage

Build and install everything:
```
/build
/build all
```

Build only binaries:
```
/build binaries
```

Build only VSCode extension:
```
/build extension
```

## Platform Detection

The skill automatically detects the current platform and uses appropriate commands:

### Windows
- **Binaries location**: `~/.ppxai/bin/`
- **Build command**: `pyinstaller` with SSL cert for corporate proxy
- **Outputs**: `ppxai.exe`, `ppxai-server.exe`, `ppxai-desktop.exe`

### macOS / Linux
- **Binaries location**: `~/.local/bin/`
- **Build command**: `pyinstaller`
- **Outputs**: `ppxai`, `ppxai-server`, `ppxai-desktop`

### VSCode Extension
- **Build**: `npm run compile && npx vsce package`
- **Install**: `code --install-extension ppxai-{version}.vsix --force`

## Build Steps

### 1. Build Binaries (if requested)

**Windows:**
```bash
SSL_CERT_FILE="C:/.ssh/Fortinet_CA_SSL.cer" .uv/uv run pyinstaller ppxai.spec --noconfirm
SSL_CERT_FILE="C:/.ssh/Fortinet_CA_SSL.cer" .uv/uv run pyinstaller ppxai-server.spec --noconfirm
SSL_CERT_FILE="C:/.ssh/Fortinet_CA_SSL.cer" .uv/uv run pyinstaller ppxai-desktop.spec --noconfirm
```

**macOS/Linux:**
```bash
uv run pyinstaller ppxai.spec --noconfirm
uv run pyinstaller ppxai-server.spec --noconfirm
uv run pyinstaller ppxai-desktop.spec --noconfirm
```

### 2. Install Binaries

**Windows:**
```bash
mkdir -p "$USERPROFILE/.ppxai/bin"
cp dist/ppxai.exe "$USERPROFILE/.ppxai/bin/"
cp dist/ppxai-server.exe "$USERPROFILE/.ppxai/bin/"
cp dist/ppxai-desktop.exe "$USERPROFILE/.ppxai/bin/"
```

**macOS/Linux:**
```bash
mkdir -p ~/.local/bin
cp dist/ppxai ~/.local/bin/
cp dist/ppxai-server ~/.local/bin/
cp dist/ppxai-desktop ~/.local/bin/
```

### 3. Build VSCode Extension (if requested)

```bash
cd vscode-extension
npm run compile
npx vsce package --allow-missing-repository
```

### 4. Install VSCode Extension

```bash
code --install-extension vscode-extension/ppxai-{version}.vsix --force
```

## Notes

- All three PyInstaller builds can run in parallel for faster builds
- The VSCode extension version is read from `vscode-extension/package.json`
- Binary outputs go to `dist/` directory before being copied to install location
- Use `--noconfirm` flag to overwrite existing builds without prompting

## Troubleshooting

**"SSL certificate error" (Windows)**
- Ensure the Fortinet CA cert exists at `C:/.ssh/Fortinet_CA_SSL.cer`
- Or remove the `SSL_CERT_FILE` prefix if not behind corporate proxy

**"pyinstaller not found"**
- Run `uv sync --all-extras` to install dependencies

**"vsce not found"**
- Run `npm install` in the `vscode-extension/` directory

**"code command not found"**
- Install VSCode shell command: Command Palette > "Shell Command: Install 'code' command in PATH"
