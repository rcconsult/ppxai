# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec for ppxai-desktop (Desktop launcher for web UI)

block_cipher = None

a = Analysis(
    ['ppxai-desktop.py'],
    pathex=[],
    binaries=[],
    datas=[
        ('ppxai/engine/app_state_schema.json', 'ppxai/engine'),
        # Include entire web UI directory tree
        ('ppxai/web', 'ppxai/web'),
        ('ppxai-config.example.json', '.'),
    ],
    hiddenimports=['ppxai.version'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # Exclude heavy packages not needed for desktop launcher
        'pytest',
        'pytest_asyncio',
        'ruff',
        'openai',
        'httpx',
        'rich',
        'prompt_toolkit',
        'fastapi',
        'uvicorn',
        'pydantic',
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='ppxai-desktop',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon='resources/ppxai.ico',
)
