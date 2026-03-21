# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec for ppxai-native (Native desktop app with Raylib + libghostty-vt)

import platform
import sys
from pathlib import Path

block_cipher = None

# Determine platform-specific libghostty binary
_system = platform.system().lower()
_machine = platform.machine().lower()

_ghostty_binaries = []
_ghostty_lib_dir = Path('ppxai/terminal/lib')

if _system == 'darwin':
    _plat = 'macos-arm64' if _machine == 'arm64' else 'macos-intel'
    _lib_name = 'libghostty_vt.dylib'
elif _system == 'linux':
    _plat = 'linux-amd64'
    _lib_name = 'libghostty_vt.so'
elif _system == 'windows':
    _plat = 'windows'
    _lib_name = 'ghostty_vt.dll'
else:
    _plat = None
    _lib_name = None

if _plat and (_ghostty_lib_dir / _plat / _lib_name).exists():
    _ghostty_binaries = [
        (str(_ghostty_lib_dir / _plat / _lib_name),
         f'ppxai/terminal/lib/{_plat}')
    ]

a = Analysis(
    ['ppxai-native.py'],
    pathex=[],
    binaries=_ghostty_binaries,
    datas=[
        # JetBrains Mono fonts
        ('ppxai/native/assets', 'ppxai/native/assets'),
        # Config examples
        ('.env.example', '.'),
        ('ppxai-config.example.json', '.'),
    ],
    hiddenimports=[
        # Raylib (CFFI-based, needs explicit import)
        'raylib',
        'raylib._raylib_cffi',
        'pyray',
        'cffi',
        # Engine core
        'openai',
        'dotenv',
        'httpx',
        # ppxai modules
        'ppxai.native',
        'ppxai.native.app',
        'ppxai.native.renderer',
        'ppxai.native.input_handler',
        'ppxai.native.layout',
        'ppxai.native.text_engine',
        'ppxai.native.theme',
        'ppxai.terminal',
        'ppxai.terminal.ghostty',
        'ppxai.engine',
        'ppxai.engine.client',
        'ppxai.engine.chat',
        'ppxai.engine.types',
        'ppxai.engine.session',
        'ppxai.engine.context',
        'ppxai.engine.bootstrap',
        'ppxai.engine.providers',
        'ppxai.engine.providers.base',
        'ppxai.engine.providers.openai_compat',
        'ppxai.engine.providers.openai_native',
        'ppxai.engine.providers.perplexity',
        'ppxai.engine.providers.gemini',
        'ppxai.engine.tools',
        'ppxai.engine.tools.base',
        'ppxai.engine.tools.manager',
        'ppxai.engine.tools.parser',
        'ppxai.engine.tools.builtin',
        'ppxai.config',
        'ppxai.config.providers',
        'ppxai.config.tools',
        'ppxai.config.features',
        'ppxai.config.paths',
        'ppxai.config.prompts',
        'ppxai.config.context',
        'ppxai.config.loader',
        'ppxai.config.store',
        'ppxai.commands',
        'ppxai.commands.factory',
        'ppxai.commands.protocol',
        'ppxai.commands.results',
        'ppxai.commands.system',
        'ppxai.commands.provider',
        'ppxai.commands.session',
        'ppxai.commands.tools',
        'ppxai.commands.display',
        'ppxai.commands.utility',
        'ppxai.commands.coding',
        'ppxai.commands.agent',
        'ppxai.common',
        'ppxai.common.logger',
        'ppxai.common.consent',
        'ppxai.prompts',
        'ppxai.checkpoint',
        # OpenAI SDK dependencies
        'pydantic',
        'pydantic.deprecated',
        'pydantic_core',
        'annotated_types',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # Exclude TUI-only packages
        'textual',
        'blinker',
        'tree_sitter',
        # Exclude server packages
        'fastapi',
        'uvicorn',
        # Exclude test/dev packages
        'pytest',
        'pytest_asyncio',
        'ruff',
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
    name='ppxai-native',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,  # GUI app — no console window
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon='resources/ppxai.ico',
)
