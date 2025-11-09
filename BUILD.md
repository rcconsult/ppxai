# Building ppxai Executables

This guide explains how to build standalone executables for ppxai on Windows, macOS, and Linux.

## Prerequisites

- Python 3.8 or higher
- pip (Python package installer)
- Git (optional, for cloning the repository)

## Quick Build

### macOS / Linux

```bash
./build.sh
```

The executable will be created at `dist/ppxai`

### Windows

```batch
build.bat
```

The executable will be created at `dist\ppxai.exe`

## Manual Build Steps

If you prefer to build manually or the automated scripts don't work:

### 1. Set up virtual environment

**macOS/Linux:**
```bash
python3 -m venv venv
source venv/bin/activate
```

**Windows:**
```batch
python -m venv venv
venv\Scripts\activate.bat
```

### 2. Install dependencies

```bash
pip install -r requirements.txt
```

### 3. Build with PyInstaller

```bash
pyinstaller ppxai.spec
```

### 4. Find your executable

**macOS/Linux:** `dist/ppxai`
**Windows:** `dist\ppxai.exe`

## Distribution

### Single File Distribution

The build creates a single standalone executable that includes:
- Python interpreter
- All required libraries (openai, rich, prompt-toolkit, python-dotenv)
- Your application code

Users don't need Python installed to run it!

### What to Include

When distributing to users, provide:
1. The executable (`ppxai` or `ppxai.exe`)
2. The `.env.example` file (as a template)
3. Instructions to create `.env` with their `PERPLEXITY_API_KEY`

### Installation Instructions for Users

**macOS/Linux:**
```bash
# Make executable if needed
chmod +x ppxai

# Run from current directory
./ppxai

# Optional: Install system-wide
sudo cp ppxai /usr/local/bin/
ppxai  # Now can run from anywhere
```

**Windows:**
```batch
# Run from current directory
ppxai.exe

# Optional: Add to PATH for system-wide access
# Move ppxai.exe to a folder in your PATH
```

## Platform-Specific Notes

### macOS

**Code Signing (Optional):**
If you want to distribute the app without security warnings:
```bash
codesign --sign "Developer ID Application: Your Name" dist/ppxai
```

**Notarization (Optional):**
For distribution outside the App Store, you may need to notarize:
```bash
xcrun notarytool submit dist/ppxai.zip --apple-id your@email.com --wait
xcrun stapler staple dist/ppxai
```

**Apple Silicon (M1/M2/M3) vs Intel:**
The executable is built for your current architecture. To build for both:
- Build on M1/M2/M3 Mac → ARM64 executable
- Build on Intel Mac → x86_64 executable

### Linux

**Dependencies:**
Some Linux systems may need additional libraries:
```bash
# Ubuntu/Debian
sudo apt-get install -y libffi-dev libssl-dev

# Fedora/RHEL
sudo dnf install -y libffi-devel openssl-devel
```

**Static Linking:**
The PyInstaller build includes most dependencies, but glibc is dynamically linked. Build on the oldest Linux version you want to support.

### Windows

**Windows Defender:**
Users may see a SmartScreen warning for unsigned executables. Options:
1. Distribute as-is (users click "More info" → "Run anyway")
2. Code sign with a certificate from a trusted CA
3. Build reputation by having many users download it

**Antivirus False Positives:**
PyInstaller executables sometimes trigger antivirus software. If this happens:
- Submit the executable to antivirus vendors as a false positive
- Consider code signing
- Use `--noupx` in the spec file (makes the file larger but sometimes helps)

## Advanced Configuration

### Customizing the Build

Edit `ppxai.spec` to customize:

- **Icon:** Add an icon file
  ```python
  exe = EXE(
      ...
      icon='icon.ico',  # Windows
      icon='icon.icns',  # macOS
  )
  ```

- **One File vs One Directory:**
  Current config creates one file. For one directory (faster startup):
  ```python
  exe = EXE(
      ...
      onefile=False,  # Add this line
  )
  ```

- **Reduce File Size:**
  ```python
  exe = EXE(
      ...
      upx=True,  # Already enabled (compresses executable)
      strip=True,  # Remove debugging symbols
  )
  ```

### Debugging Build Issues

If the build fails or the executable doesn't work:

1. **Test the executable:**
   ```bash
   ./dist/ppxai --version  # Add version flag to your app
   ```

2. **Check for missing modules:**
   ```bash
   pyinstaller --log-level DEBUG ppxai.spec
   ```

3. **Add hidden imports:**
   Edit `ppxai.spec` and add to `hiddenimports`:
   ```python
   hiddenimports=[
       'openai',
       'rich',
       'prompt_toolkit',
       'dotenv',
       'missing_module_name',  # Add here
   ],
   ```

4. **Test with PyInstaller directly:**
   ```bash
   pyinstaller --onefile --name ppxai ppxai.py
   ```

## Automated Builds with GitHub Actions

See the `.github/workflows/build.yml` file for automated builds on all platforms using GitHub Actions.

## Troubleshooting

### "Permission denied" on macOS/Linux
```bash
chmod +x dist/ppxai
```

### "Cannot be opened because the developer cannot be verified" on macOS
```bash
xattr -d com.apple.quarantine dist/ppxai
```

Or: System Preferences → Security & Privacy → Click "Open Anyway"

### Missing .env file error
Make sure users create a `.env` file with:
```
PERPLEXITY_API_KEY=your_api_key_here
```

### Executable is very large
This is normal. It includes the entire Python runtime and all dependencies. Typical sizes:
- macOS: 15-25 MB
- Linux: 15-25 MB
- Windows: 10-20 MB

## Support

For issues related to building, check:
- [PyInstaller Documentation](https://pyinstaller.org/)
- [PyInstaller GitHub Issues](https://github.com/pyinstaller/pyinstaller/issues)
