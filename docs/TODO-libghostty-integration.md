# TODO: libghostty-vt Integration

**Status:** Infrastructure ready, waiting for C API stabilization
**Priority:** Medium
**Target:** v1.17.x (once C API is tagged)
**Created:** 2026-03-19

---

## Overview

Integrate [libghostty-vt](https://mitchellh.com/writing/libghostty-is-coming) as a native
terminal library for ppxai, replacing heuristic-based terminal detection with a proven,
SIMD-optimized VT implementation. The library is bundled as a platform-specific shared
library with PyInstaller builds.

## Architecture

```
ghostty-org/ghostty (GitHub)
  │
  ├── build-libghostty.yml (our CI)
  │   ├── zig build lib-vt (4 platforms)
  │   └── gh release create libghostty-<date> (ppxai repo)
  │
  ├── ppxai/terminal/ghostty.py (ctypes wrapper)
  │   └── loads libghostty_vt.{so,dylib,dll}
  │
  └── PyInstaller bundles shared lib per platform
```

## What It Solves

| Problem | Current workaround | libghostty fix |
|---------|-------------------|----------------|
| Ctrl+Enter requires Kitty protocol | Ctrl+J fallback, per-terminal config | `ghostty_key_encode()` produces correct sequence |
| Terminal detection heuristics | `TERM_PROGRAM` env var sniffing | Proper capability queries via VT state |
| Image protocol guessing | Multiple try/except fallback chains | Query terminal state for supported protocols |
| Escape sequence correctness | Hand-coded sequences per protocol | Library generates correct sequences |

## Implementation Phases

### Phase 1: CI Pipeline (done)
- [x] `.github/workflows/build-libghostty.yml` — builds from Ghostty source
- [x] Publishes shared libs + headers as GitHub release assets
- [ ] Run first build to verify workflow works

### Phase 2: Python Wrapper (scaffolded)
- [x] `ppxai/terminal/__init__.py` — package with `is_available()`, `get_version()`
- [x] `ppxai/terminal/ghostty.py` — ctypes loader with platform detection
- [ ] Define C function signatures once API stabilizes
- [ ] Implement `encode_key()` using `ghostty_key_encode`
- [ ] Implement `detect_capabilities()` using terminal state API
- [ ] Add unit tests

### Phase 3: Integration
- [ ] Replace Ctrl+J fallback in `ppxai/tui/widgets/input_box.py`
- [ ] Replace terminal detection in `ppxai/tui/terminal.py`
- [ ] Replace image protocol detection in `ppxai/tui/widgets/image_handlers.py`
- [ ] Update PyInstaller specs to bundle shared lib
- [ ] Graceful fallback when library not available (existing behavior)

### Phase 4: Advanced Features
- [ ] Terminal-to-HTML export for session sharing (`ghostty_formatter`)
- [ ] Proper sixel/kitty graphics rendering via library
- [ ] Mouse event encoding

## Pinned Ghostty Commit

```
Repository: ghostty-org/ghostty
Working build: libghostty-20260319 release (built from main as of 2026-03-19)
Zig version: 0.15.2
Build step: zig build lib-vt (removed from main ~2026-03-20, now part of default install)
```

**NOTE (2026-03-21):** The `lib-vt` build step was removed from Ghostty's main branch.
The default `zig build` now installs the shared lib but also tries to build the GUI
(which fails without platform deps on CI). The workflow needs updating to either:
1. Find the new correct build step name
2. Use `zig build -Dapp=false` or similar flag to skip GUI
3. Use the CMake integration path (like ghostling does)
Current `libghostty-20260319` binaries work and are published.

## Reference Implementation: Ghostling

[ghostty-org/ghostling](https://github.com/ghostty-org/ghostling) is a **complete minimal terminal emulator**
in a single C file (~800 lines) using libghostty-vt + Raylib. This proves the C API is production-ready.

**Data flow:**
```
PTY output → ghostty_terminal_vt_write() → render state → your renderer
User input → key/mouse encoder → escape sequences → PTY write
```

**Key API functions (from ghostling/main.c):**
```c
// Terminal lifecycle
ghostty_terminal_new(allocator, &terminal, opts)  // create terminal
ghostty_terminal_vt_write(terminal, data, len)     // feed VT data

// Keyboard encoding (Kitty protocol)
ghostty_key_encoder_new(&encoder)
ghostty_key_event_set_key(event, key)
ghostty_key_event_set_mods(event, mods)
ghostty_key_encoder_encode(encoder, event, buf, buflen, &written)

// Mouse encoding (SGR, X10, URxvt modes)
ghostty_mouse_encoder_new(&encoder)
ghostty_mouse_encoder_setopt_from_terminal(encoder, terminal)
ghostty_mouse_encoder_encode(encoder, event, buf, buflen, &written)

// Render state (row/cell iteration)
ghostty_render_state_new(&state)
ghostty_render_state_update(state, terminal)
ghostty_render_state_row_iterator_next(iter)  // walk rows
ghostty_render_state_row_cells_next(cells)    // walk cells per row

// Terminal queries
ghostty_terminal_mode_get(terminal, mode, &value)
ghostty_terminal_get(terminal, data_type, &result)
```

**Features ghostling demonstrates working:**
- 24-bit + 256-color, bold/italic/inverse styles
- Unicode/multi-codepoint grapheme rendering
- Text reflow on resize, scrollback
- Kitty keyboard protocol (key + modifiers → escape sequences)
- Mouse tracking (SGR, URxvt, UTF8, X10 modes)
- Focus reporting, scrollbar with drag

## C API Headers (reference)

The public API surface from `include/ghostty/vt.h`:
- `types.h` — Type definitions
- `allocator.h` — Memory management
- `key.h` — Keyboard event encoding (Kitty protocol)
- `terminal.h` — Terminal state and rendering
- `formatter.h` — Output formatting (text, VT, HTML)
- `mouse.h` — Mouse event encoding
- `modes.h` — Terminal modes
- `osc.h` — OSC sequence parsing
- `sgr.h` — SGR sequence parsing
- `focus.h` — Focus event encoding
- `paste.h` — Paste safety utilities
- `size_report.h` — Size reporting
- `wasm.h` — WebAssembly utilities

## Dependencies

**Build time (CI only):**
- Zig 0.15.2 (via `goto-bus-stop/setup-zig@v2`)
- Ghostty source checkout

**Runtime (bundled with ppxai):**
- One shared library per platform (~2-5 MB)
- No other dependencies

## References

- [Libghostty Is Coming](https://mitchellh.com/writing/libghostty-is-coming) — Mitchell Hashimoto
- [VT API Reference](https://ghostty.org/docs/vt/reference) — ghostty.org
- [ghostty-vt Zig Module PR #8840](https://github.com/ghostty-org/ghostty/pull/8840)
- [Ghostty 1.3 Release Notes](https://ghostty.org/docs/install/release-notes/1-3-0)
