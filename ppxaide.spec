# -*- mode: python ; coding: utf-8 -*-

block_cipher = None

a = Analysis(
    ['ppxaide.py'],
    pathex=[],
    binaries=[],
    datas=[
        ('.env.example', '.'),
        ('ppxai-config.example.json', '.'),
        ('ppxai/tui/themes', 'ppxai/tui/themes'),  # Include CSS themes
    ],
    hiddenimports=[
        'textual',
        'textual.app',
        'textual.widgets',
        'textual.containers',
        'textual.binding',
        'textual.message',
        'textual.reactive',
        'textual.theme',
        'rich',
        'rich.markdown',
        'rich.syntax',
        'openai',
        'dotenv',
        'ppxai.tui.themes.themes',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
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
    name='ppxaide',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon='resources/ppxai-tui.ico',
)
