# -*- mode: python ; coding: utf-8 -*-
import importlib
from pathlib import Path

block_cipher = None

# Locate textual's tree-sitter highlight queries (.scm files)
_textual_root = Path(importlib.import_module('textual').__file__).parent
_highlights_src = str(_textual_root / 'tree-sitter' / 'highlights')

a = Analysis(
    ['ppxaide.py'],
    pathex=[],
    binaries=[],
    datas=[
        ('.env.example', '.'),
        ('ppxai-config.example.json', '.'),
        ('ppxai/tui/themes', 'ppxai/tui/themes'),  # Include CSS themes
        (_highlights_src, 'textual/tree-sitter/highlights'),  # Syntax highlight queries
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
        'blinker',  # EventBus dependency
        'ppxai.tui.themes.themes',
        'ppxai.common.preview',
        'ppxai.preview_server',
        'tree_sitter',
        'tree_sitter_python',
        'tree_sitter_javascript',
        'tree_sitter_json',
        'tree_sitter_yaml',
        'tree_sitter_toml',
        'tree_sitter_html',
        'tree_sitter_css',
        'tree_sitter_markdown',
        'tree_sitter_bash',
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
    icon='resources/ppxaide-nobg.ico',
)
