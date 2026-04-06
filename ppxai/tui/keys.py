"""
Key binding registry — single source of truth for all ppxaide keyboard shortcuts.

This module defines all key bindings, their owners (app vs widget), and descriptions.
It generates BINDINGS lists for Textual widgets and formatted tables for /keys.

This is a LEAF MODULE — no ppxai imports, only textual.binding.Binding.

Kitty Keyboard Protocol (Textual 8.x)
──────────────────────────────────────
Textual 8.1.1 does NOT auto-negotiate Kitty keyboard protocol (issue #6074 open).
Progressive enhancement (\\x1b[>1u) is not enabled — it breaks printable char recognition.
- Ctrl+Enter: only works in Kitty (native), Ghostty (explicit keybind),
  WezTerm (enable_kitty_keyboard). Fallback: Ctrl+J.
- Ctrl+[: sends ESC in non-Kitty terminals. Primary resize: minus/equals.
No changes planned — fallback keys cover all terminals.
"""

from dataclasses import dataclass

from textual.binding import Binding


@dataclass(frozen=True)
class KeyDef:
    """Definition of a single key binding."""

    key: str               # Textual key string (e.g., "ctrl+enter")
    action: str            # Action name (e.g., "quit") or empty for on_key handlers
    description: str       # Human-readable description shown in /keys
    owner: str             # "app" or widget class name (e.g., "FileTree")
    show: bool = False     # Show in Textual footer
    context: str = ""      # When active (e.g., "when file tree focused")
    notes: str = ""        # Implementation notes
    is_binding: bool = True  # True = Textual BINDINGS, False = on_key handler


# =============================================================================
# Complete key inventory — grouped by owner
# =============================================================================

ALL_KEYS: list[KeyDef] = [
    # ── App-level bindings ──────────────────────────────────────────────────
    # These are active globally unless overridden by a focused widget.
    KeyDef("ctrl+enter", "noop", "Send", "app", show=True,
           notes="Display-only. Actual handling: ChatTextArea.on_key() and FileTree.action_edit()"),
    KeyDef("ctrl+c", "quit", "Quit", "app", show=True,
           notes="Double-press confirmation; first press cancels active stream"),
    KeyDef("ctrl+b", "toggle_file_tree", "Files", "app", show=True),
    KeyDef("ctrl+l", "clear", "Clear", "app", show=True),
    KeyDef("ctrl+t", "cycle_theme", "Theme", "app", show=True),
    KeyDef("ctrl+w", "close_panel", "Close", "app"),
    KeyDef("ctrl+s", "save_panel", "Save", "app"),
    KeyDef("f6", "toggle_focus", "Switch Pane", "app"),
    KeyDef("ctrl+tab", "toggle_focus", "Switch Pane", "app"),
    KeyDef("escape", "cancel", "Cancel", "app",
           notes="Priority: help panel > modal > file tree focus > side panel"),
    KeyDef("q", "hide_help_panel", "Close Help", "app"),
    # Split resize — minus/equals are primary (all terminals), ctrl+[/] are fallback.
    # Note: ctrl+[ sends ESC in most terminals, ctrl+] sends GS — both unreliable.
    KeyDef("minus", "resize_panel('left')", "Shrink", "app"),
    KeyDef("equals", "resize_panel('right')", "Grow", "app"),
    KeyDef("ctrl+left_square_bracket", "resize_panel('left')", "Shrink Panel", "app",
           notes="Fallback — sends ESC in most terminals, only works in Ghostty/Kitty"),
    KeyDef("ctrl+right_square_bracket", "resize_panel('right')", "Grow Panel", "app",
           notes="Fallback — only works in Ghostty/Kitty"),

    # ── ChatTextArea (on_key handler, not BINDINGS) ─────────────────────────
    KeyDef("ctrl+enter", "", "Send message", "ChatTextArea", is_binding=False,
           context="when input focused",
           notes="Primary submit — requires Kitty protocol (Ghostty/Kitty/WezTerm)"),
    KeyDef("ctrl+j", "", "Send message (fallback)", "ChatTextArea", is_binding=False,
           context="when input focused",
           notes="Universal fallback — works in ALL terminals"),

    # ── InputBox (on_key handler, not BINDINGS) ─────────────────────────────
    KeyDef("tab", "", "Autocomplete", "InputBox", is_binding=False,
           context="when input focused"),
    KeyDef("up", "", "History back", "InputBox", is_binding=False,
           context="when input focused"),
    KeyDef("down", "", "History forward", "InputBox", is_binding=False,
           context="when input focused"),

    # ── FileTree ────────────────────────────────────────────────────────────
    KeyDef("ctrl+enter", "edit", "Edit", "FileTree", show=True,
           context="when file tree focused"),
    KeyDef("space", "inject", "@file", "FileTree", show=True,
           context="when file tree focused"),
    KeyDef("a", "attach_file", "Attach", "FileTree", show=True,
           context="when file tree focused",
           notes="v1.17.4 Phase 7.1: Stage highlighted file as upload for next chat turn"),
    KeyDef("escape", "dismiss_tree", "Back", "FileTree", show=True,
           context="when file tree focused"),

    # ── App-level: Ctrl+U attach shortcut ──────────────────────────────────
    KeyDef("ctrl+u", "attach_shortcut", "Attach File", "app",
           notes="v1.17.4 Phase 7.2: Opens file tree if hidden, or focuses it for attach"),

    # ── SidePanel ───────────────────────────────────────────────────────────
    KeyDef("escape", "close_panel", "Close", "SidePanel", show=True,
           context="when side panel focused"),
    KeyDef("ctrl+l", "cycle_language", "Lang", "SidePanel", show=True,
           context="when side panel focused"),

    # ── DataViewer ──────────────────────────────────────────────────────────
    KeyDef("v", "toggle_view", "Toggle View", "DataViewer", show=True,
           context="when data viewer focused"),
    KeyDef("e", "expand_all", "Expand All", "DataViewer",
           context="when data viewer focused"),
    KeyDef("c", "collapse_all", "Collapse All", "DataViewer",
           context="when data viewer focused"),

    # ── TableViewer ─────────────────────────────────────────────────────────
    KeyDef("v", "toggle_view", "Toggle View", "TableViewer", show=True,
           context="when table viewer focused"),

    # ── EditorScreen ────────────────────────────────────────────────────────
    KeyDef("ctrl+s", "save", "Save", "EditorScreen", show=True,
           context="full-screen editor"),
    KeyDef("escape", "close", "Close", "EditorScreen", show=True,
           context="full-screen editor"),

    # ── ConfirmCloseScreen ──────────────────────────────────────────────────
    KeyDef("y", "save", "Save & Close", "ConfirmCloseScreen", show=True,
           context="unsaved changes dialog"),
    KeyDef("n", "discard", "Discard", "ConfirmCloseScreen", show=True,
           context="unsaved changes dialog"),
    KeyDef("escape", "cancel", "Cancel", "ConfirmCloseScreen", show=True,
           context="unsaved changes dialog"),

    # ── ViewerScreen ────────────────────────────────────────────────────────
    KeyDef("escape", "close", "Close", "ViewerScreen", show=True,
           context="full-screen viewer"),
    KeyDef("q", "close", "Close", "ViewerScreen",
           context="full-screen viewer"),
]


# =============================================================================
# Known conflicts — documented, all resolved by Textual focus system
# =============================================================================

KNOWN_CONFLICTS = [
    ("ctrl+w", "app: close_panel", "TextArea: delete-word-left",
     "TextArea wins when focused — app binding only fires from non-text widgets"),
    ("f6", "app: toggle_focus", "TextArea: select-line",
     "TextArea wins when focused"),
    ("ctrl+c", "app: quit", "TextArea: copy",
     "TextArea wins when focused — app quit requires double-press anyway"),
    ("ctrl+l", "app: clear", "SidePanel: cycle_language",
     "SidePanel wins when focused"),
]


# =============================================================================
# Binding generators
# =============================================================================

def get_app_bindings() -> list[Binding]:
    """Generate the BINDINGS list for PPXAIDEApp from the registry."""
    return [
        Binding(k.key, k.action, k.description, show=k.show)
        for k in ALL_KEYS
        if k.owner == "app" and k.is_binding
    ]


def get_widget_bindings(owner: str) -> list[Binding]:
    """Generate the BINDINGS list for a named widget from the registry."""
    return [
        Binding(k.key, k.action, k.description, show=k.show)
        for k in ALL_KEYS
        if k.owner == owner and k.is_binding
    ]


# =============================================================================
# Formatted output for /keys command
# =============================================================================

def _format_key(key: str) -> str:
    """Format a Textual key string for display (e.g., 'ctrl+enter' → 'Ctrl+Enter')."""
    replacements = {
        "ctrl+left_square_bracket": "Ctrl+[",
        "ctrl+right_square_bracket": "Ctrl+]",
    }
    if key in replacements:
        return replacements[key]
    parts = key.split("+")
    return "+".join(p.capitalize() for p in parts)


def get_keys_table() -> str:
    """Generate formatted key binding table for /keys command output."""
    sections = [
        ("App-Level (always active)", "app", True),
        ("Chat Input", "ChatTextArea", False),
        ("Chat Input", "InputBox", False),
        ("File Tree", "FileTree", True),
        ("Side Panel", "SidePanel", True),
        ("Data Viewer", "DataViewer", True),
        ("Table Viewer", "TableViewer", True),
        ("Editor (full-screen)", "EditorScreen", True),
        ("Viewer (full-screen)", "ViewerScreen", True),
    ]

    lines = ["Keyboard Shortcuts", ""]
    seen_sections: set[str] = set()

    for section_name, owner, _show_all in sections:
        keys = [k for k in ALL_KEYS if k.owner == owner]
        if not keys:
            continue

        # Merge sections with same name (ChatTextArea + InputBox → "Chat Input")
        if section_name in seen_sections:
            # Append to existing section — no header
            pass
        else:
            seen_sections.add(section_name)
            lines.append(f"  {section_name}")
            lines.append(f"  {'─' * 35}")

        for k in keys:
            display_key = _format_key(k.key)
            lines.append(f"  {display_key:<14}{k.description}")

        lines.append("")

    return "\n".join(lines)


def get_conflicts_table() -> str:
    """Generate formatted conflict documentation for /keys conflicts."""
    lines = [
        "Known Key Binding Conflicts",
        "",
        "All resolved by Textual's focus-based dispatch — the focused widget's",
        "bindings take priority over app-level bindings.",
        "",
    ]
    for key, app_action, widget_action, resolution in KNOWN_CONFLICTS:
        display_key = _format_key(key)
        lines.append(f"  {display_key}")
        lines.append(f"    {app_action}")
        lines.append(f"    {widget_action}")
        lines.append(f"    → {resolution}")
        lines.append("")

    return "\n".join(lines)
