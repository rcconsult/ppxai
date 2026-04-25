# v1.18.2 — Inline image rendering inside TUI markdown

**Status:** Deferred from v1.18.1 hotfix.
**Trigger to revisit:** when there is appetite to expand the TUI's
markdown experience. ppxai is a chat client, not a markdown IDE —
this is a "nice to have," not a "must ship."

## Background

The Rich TUI (`ppxai`) and Textual TUI (`ppxaide`) both already
render terminal images for **standalone** `ImageResult` payloads:
- `ppxai/tui/renderable/iterm2.py::ITerm2Image` (Rich, OSC iTerm2 / WezTerm protocol)
- `ppxai/tui/widgets/iterm2_widget.py` (Textual, render_lines() injection)
- `ppxai/rendering/rich_renderer.py::render_image` and
  `ppxai/rendering/textual_renderer.py::render_image`

**But:** when the user does `/show README.md` and the markdown body
contains `![alt](docs/foo.png)`, neither Rich's `Markdown` nor
Textual's `Markdown` widget knows about ppxai's image-rendering
pipeline. They emit:
- Rich `Markdown`: an OSC 8 hyperlink with the alt text as the
  visible label. The user sees a clickable text label, not the image.
- Textual `Markdown`: same shape — hyperlink, no inline image.

v1.18.1's hotfix (`ppxai/common/markdown_links.py::rewrite_relative_links`)
makes the link clickable (file:// URI resolves to a real file the OS
can open) but **doesn't render the image inline.**

## Why deferred

ppxai's identity is "multi-LLM chat client with code-aware
agent loop." Inline image rendering inside markdown is a markdown-
viewer feature. The work doesn't trade off against any v1.18.1
correctness fix — the hotfix paths (cwd, session isolation, link
clicks) are orthogonal.

Cost estimate: 150–300 LoC across both renderers + an interface for
walking the markdown AST that doesn't exist today.

## Scope when picked up

### 1. Custom Rich console renderable for markdown

Replace `Markdown(content)` with a custom renderable that walks the
parsed AST and dispatches each block:
- text / heading / list / table → existing Rich Markdown rendering
- image node → emit an `ITerm2Image` for the absolute path
  (already resolved by `rewrite_relative_links`)

Rich's `Markdown` is built on `markdown-it-py` internally; reuse the
same parser to get the AST, then walk it. Skip emitting the OSC 8
hyperlink for image nodes (the inline image replaces it).

### 2. Custom Textual Markdown widget extension

Textual's `Markdown` widget renders via Rich. Easiest path: subclass
and override the image-block rendering to insert an `ITerm2ImageWidget`
inline within the scrolling content.

Trade-off: Textual's content-flow uses `render_lines()` per chunk;
images need to occupy multiple terminal rows. Need to interleave
image widgets with text content. Likely requires a custom widget
that owns the markdown AST and lays out image + text blocks.

### 3. Path resolution

Already done by `rewrite_relative_links` in v1.18.1. The image
renderers receive absolute paths.

### 4. Terminal capability detection

Reuse `ppxai/rendering/rich_renderer.py::_get_terminal_type` and
`ppxai/tui/widgets/image_handlers.py`. If terminal doesn't support
images, fall back to current behavior (alt text + hyperlink).

### 5. Tests

- `test_rich_markdown_inline_images.py` — markdown with `![](file.png)`
  emits an `ITerm2Image` segment in the Rich render output.
- `test_textual_markdown_inline_images.py` — markdown with
  `![](file.png)` mounts an image widget in the side panel.
- Cross-TUI parity: same input markdown, both TUIs surface the
  image (or both fall back gracefully on dumb terminals).

## Acceptance criteria when picked up

- [ ] `/show README.md` in Rich TUI renders inline images for
      `![](relative.png)` references on iTerm2/WezTerm/Kitty.
- [ ] Same for `ppxaide` (Textual TUI).
- [ ] Falls back to alt-text + clickable link on terminals without
      image protocol support.
- [ ] Resolves paths via `rewrite_relative_links` (no path-handling
      duplication).
- [ ] Cross-TUI parity test passes.

## What v1.18.1 ships (for context)

The hotfix ship-set:
- `ppxai/common/markdown_links.py` — shared path-rewrite helper.
- `ppxai/rendering/rich_renderer.py::render_markdown` — calls helper.
- `ppxai/rendering/textual_renderer.py::render_markdown` — calls helper.
- `ppxai/server/state.py::get_session_or_query` — image route accepts
  session via query string (web `<img>` fix).
- `ppxai/server/routes/files.py::serve_image` — uses new dependency.
- `ppxai/server/routes/file_serve.py::serve_file/preview_file` — same.
- `ppxai/web/app.js` and `markdown-file-view.js` — append `?session=`
  to image URLs.

After this hotfix:
- Web: README images load (session-isolated paths now work).
- Rich/Textual TUI: README links open the right file (file:// URIs)
  instead of "invalid link" popups; **images still render as
  alt-text labels, not inline images** — that's this TODO.
