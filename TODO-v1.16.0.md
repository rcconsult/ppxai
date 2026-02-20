# TODO: v1.16.0 - File Navigation & Tree Explorer

**Created:** 2026-02-06
**Branch:** feature/1-16-0 (to be created)
**Status:** Planning
**Previous Release:** v1.15.6

---

## Overview

Add file tree exploration and navigation capabilities to ppxai clients. Three-phase rollout prioritizing quick wins and architectural fit.

---

## Phase 0: Command-Based Navigation (MVP) - v1.16.0

**Priority:** High
**Status:** ⏳ Planned
**Effort:** 2 days
**Target:** v1.16.0 release

### Goal

Add simple commands for file/directory navigation that work in ALL clients (ppxaide, Web App, ppxai Rich CLI).

### Features

**New Commands:**
- `/ls [path]` - List files and directories (like Unix `ls -lah`)
  - Shows file sizes, permissions, modification times
  - Color-coded: directories (blue), files (white), executables (green)
  - Respects `.gitignore` patterns

- `/tree [depth]` - Render directory tree structure
  - Default depth: 3 levels
  - Shows folder hierarchy with indentation
  - Icons: 📁 for directories, 📄 for files
  - Counts: "3 directories, 12 files"

- `/pwd` - Print working directory (already exists)
- `/cd [path]` - Change working directory (already exists)

### Implementation

**Files to Create:**
- `ppxai/commands/builtin/navigation.py` - Implement `/ls` and `/tree` commands

**Files to Modify:**
- `ppxai/commands/handler.py` - Register new commands
- `ppxai/rich/ui.py` - Rich Tree rendering for CLI output
- `ppxai/rendering/rich_renderer.py` - Handle DirectoryListing result type
- `ppxai/rendering/textual_renderer.py` - Handle DirectoryListing for TUI

**Command Result Types:**
```python
@dataclass
class DirectoryListingResult:
    """Result of /ls command - list files in directory"""
    path: str
    entries: List[FileEntry]  # name, size, modified, type, permissions
    total_size: int

@dataclass
class DirectoryTreeResult:
    """Result of /tree command - hierarchical tree"""
    path: str
    tree_data: Dict[str, Any]  # Nested dict for rendering
    total_dirs: int
    total_files: int
    max_depth: int
```

### Testing

- [ ] Test `/ls` in all three clients (ppxaide, Web, CLI)
- [ ] Test `/ls` with relative and absolute paths
- [ ] Test `/ls` with non-existent paths (error handling)
- [ ] Test `/tree` with different depth levels (1, 3, 5)
- [ ] Test `/tree` on large repositories (performance)
- [ ] Verify `.gitignore` patterns are respected
- [ ] Test with directories containing special characters
- [ ] Test with network drives / slow file systems

### Documentation

- Update `AGENTS.md` with new commands
- Add examples to `/help` output
- Document in `docs/COMMANDS.md`

---

## Phase 1: ppxaide Interactive File Tree - v1.16.1

**Priority:** High
**Status:** ⏳ Planned
**Effort:** 5 days
**Target:** v1.16.1 release

### Goal

Add NvChad-inspired interactive file tree to ppxaide (Textual TUI).

### Features

**Interactive File Explorer:**
- Left sidebar with expandable directory tree
- Keyboard navigation: Arrow keys, Enter to open, Space to expand/collapse
- File icons: 📁 folders, 📄 files, git-aware icons (optional)
- Click to select file → opens in side panel (read-only view)
- `Ctrl+I` on selected file → injects `@file path` into input
- Resizable with `Ctrl+[` / `Ctrl+]` (existing bindings)
- Filter files by typing (fuzzy search)

**Keyboard Bindings:**
- `Ctrl+E` - Toggle file tree visibility
- `Enter` - Open selected file in side panel
- `Ctrl+Enter` - Inject `@file path` into input
- `Space` - Expand/collapse folder
- Arrow keys - Navigate tree
- `/` - Focus search filter

**Layout:**
```
┌─────────────────────────────────────────────────┐
│  Header (Provider/Model/Tools/Badges)          │
├──────────────┬──────────────────────────────────┤
│ File Tree    │ Chat Messages                    │
│ (left panel) │                                  │
│              │                                  │
│ 📁 src/      ├──────────────────────────────────┤
│   📄 main.py │ Code Preview / Editor            │
│   📄 utils.py│ (side panel - optional)          │
│ 📁 tests/    │                                  │
├──────────────┴──────────────────────────────────┤
│ Input Box                                       │
└─────────────────────────────────────────────────┘
```

### Implementation

**Files to Create:**
- `ppxai/tui/widgets/file_tree.py` - FileTree widget wrapping Textual's DirectoryTree
  - ~200 lines
  - Handles file selection events
  - Manages expand/collapse state
  - Implements filtering/search

**Files to Modify:**
- `ppxai/tui/app.py` - Layout integration
  - Add file tree to main layout
  - Wire up keyboard bindings
  - Handle file selection events
  - Sync with working directory changes

- `ppxai/tui/themes/layout.tcss` - Styling
  - File tree panel sizing
  - Colors for different file types
  - Hover/selection styles

- `ppxai/tui/widgets/input_box.py` - Context injection
  - Add method to inject `@file path` at cursor position
  - Handle focus management when injecting

- `ppxai/tui/widgets/side_panel.py` - File opening
  - Minor tweaks to handle file tree selections
  - Already supports opening files (existing code)

### Technical Details

**Using Textual's DirectoryTree:**
```python
from textual.widgets import DirectoryTree

class FileTree(Widget):
    def compose(self) -> ComposeResult:
        yield DirectoryTree(
            self.root_path,
            id="file-tree-widget"
        )

    def on_directory_tree_file_selected(
        self,
        event: DirectoryTree.FileSelected
    ) -> None:
        # Open file in side panel or inject @file
        if self.modifier_key_pressed("ctrl"):
            self.inject_file_reference(event.path)
        else:
            self.app.open_file_in_panel(event.path)
```

**Lazy Loading:**
- DirectoryTree automatically lazy-loads directories
- Only scans visible nodes (performance optimization)
- Handles large repositories efficiently

**Git Awareness (Optional):**
- Show modified files in different color
- Mark new files with indicator
- Read git status once on load, cache results

### Performance Considerations

**Large Repositories:**
- DirectoryTree uses lazy loading by default
- Only expand/scan when user clicks folder
- Limit initial depth to 2 levels
- Background loading for git status

**Ignore Patterns:**
- Respect `.gitignore` by default
- Hardcoded ignores: `node_modules/`, `.git/`, `__pycache__/`, `.venv/`
- User-configurable ignore list in `ppxai-config.json`

### Testing

- [ ] Test with small project (<100 files)
- [ ] Test with large project (>10,000 files)
- [ ] Test keyboard navigation (all bindings)
- [ ] Test file opening in side panel
- [ ] Test `@file` injection into input
- [ ] Test filtering/search functionality
- [ ] Test with symbolic links
- [ ] Test with permission errors (unreadable directories)
- [ ] Test working directory sync (`/cd` updates tree root)
- [ ] Test resize with `Ctrl+[` / `Ctrl+]`

### Documentation

- Add section to ppxaide documentation
- Screenshot/demo GIF of file tree in action
- Document keyboard bindings in `/help`

---

## Phase 2: Web App File Tree Sidebar - v1.17.0

**Priority:** Medium
**Status:** ⏳ Planned
**Effort:** 7 days
**Target:** v1.17.0 release

### Goal

Add collapsible file tree sidebar to Web App (browser client).

### Features

**Sidebar File Explorer:**
- Collapsible left sidebar (like VSCode)
- File tree with expandable folders
- Click file → opens in split preview panel
- Right-click → context menu ("Insert @file reference")
- Search/filter files by name
- Persistent state (localStorage): remember expanded folders

**UI Elements:**
- Hamburger menu (`☰`) in header to toggle sidebar
- Collapse to icon-only mode (show only icons)
- Resize handle to adjust sidebar width
- File icons: 📁 folders, 📄 files

**Layout:**
```
┌─────────────────────────────────────────────────┐
│  [☰] Header (Provider/Model/Tools)            │
├──────────────┬──────────────────────────────────┤
│ File Tree    │ Chat Messages                    │
│ Sidebar      │                                  │
│ [🗁] Collapse│                                  │
│ 📁 src/      │                                  │
│   📄 main.py │                                  │
│   📄 utils.py│                                  │
├──────────────┴──────────────────────────────────┤
│ Input Box                                       │
└─────────────────────────────────────────────────┘
```

### Implementation

**Files to Create:**
- `ppxai/web/components/file-tree.js` - File tree component
  - ~400 lines
  - Handles file/folder expansion
  - Manages selection state
  - Communicates with server for directory listing

- `ppxai/web/styles/file-tree.css` - Styling
  - Sidebar layout
  - Tree node indentation
  - Hover/selection effects
  - Collapse animation

**Files to Modify:**
- `ppxai/web/app.js` - Integration
  - Initialize FileTreeComponent
  - Handle file selection events
  - Toggle sidebar visibility
  - Save/restore sidebar state

- `ppxai/web/index.html` - Structure
  - Add sidebar container element
  - Add hamburger menu button

- `ppxai/server/http.py` - Backend endpoint
  - Add `/files/list` endpoint
  - Returns directory tree as JSON
  - Respects `.gitignore` patterns

- `ppxai/web/styles.css` - Layout
  - Adjust main layout for sidebar
  - Responsive design (mobile: sidebar overlay)

### Server API

**Endpoint:** `GET /files/list?path=<path>&depth=<depth>`

**Response:**
```json
{
  "path": "/path/to/project",
  "entries": [
    {
      "name": "src",
      "type": "directory",
      "children": [
        {"name": "main.py", "type": "file", "size": 1234},
        {"name": "utils.py", "type": "file", "size": 567}
      ]
    },
    {
      "name": "README.md",
      "type": "file",
      "size": 890
    }
  ]
}
```

### Technical Details

**Reusing tree-viewer.js Pattern:**
```javascript
class FileTreeComponent {
    constructor(container, options = {}) {
        this.container = container;
        this.rootPath = options.rootPath || '/';
        this.onFileSelect = options.onFileSelect || (() => {});
        this.expandedFolders = new Set();

        this.loadDirectory(this.rootPath);
    }

    async loadDirectory(path) {
        const response = await fetch(
            `${serverUrl}/files/list?path=${encodeURIComponent(path)}`
        );
        const data = await response.json();
        this.renderTree(data.entries);
    }

    renderTree(entries) {
        // Render tree with expand/collapse icons
        // Handle clicks for file selection
        // Save expanded state to localStorage
    }
}
```

**Persistent State:**
- Save expanded folders to `localStorage['ppxai_file_tree_state']`
- Restore on page load
- Clear on working directory change

### Performance Considerations

**Server-Side:**
- Limit depth to 3 levels by default
- Implement pagination for large directories (>1000 files)
- Cache directory listings (5 second TTL)
- Background worker for file system monitoring (optional)

**Client-Side:**
- Virtual scrolling for large trees (>500 nodes visible)
- Debounce search input (300ms)
- Lazy-load subtrees on expand

### Testing

- [ ] Test with various project sizes
- [ ] Test file opening in preview panel
- [ ] Test `@file` injection from context menu
- [ ] Test search/filter functionality
- [ ] Test sidebar collapse/expand
- [ ] Test sidebar resize
- [ ] Test persistent state (reload page)
- [ ] Test working directory sync
- [ ] Test on mobile (responsive layout)
- [ ] Test with slow network (loading states)

### Documentation

- Add section to Web App documentation
- Demo video/screenshot
- Document server API endpoint

---

## Explicitly NOT Planned

### ppxai (Rich CLI) Interactive File Tree

**Status:** ❌ Not Feasible

**Why:**
- Rich is a **rendering library**, not a TUI framework
- Cannot handle keyboard input or maintain interactive state
- Would require complete rewrite of input handling system
- Architecturally inappropriate

**Alternative:**
Users can:
1. Use `/ls` and `/tree` commands (static output) - Phase 0
2. Use `ppxaide` for interactive file browsing - Phase 1
3. Use `@tree` context injection to include directory structure in prompts

---

## Testing Strategy

### Unit Tests

- [ ] Test DirectoryListing command result rendering
- [ ] Test DirectoryTree command result rendering
- [ ] Test file path resolution (relative vs absolute)
- [ ] Test `.gitignore` pattern matching
- [ ] Test permission error handling

### Integration Tests

- [ ] Test commands in all clients (ppxaide, Web, CLI)
- [ ] Test file tree widget events (ppxaide)
- [ ] Test server `/files/list` endpoint (Web)
- [ ] Test working directory sync across components

### Performance Tests

- [ ] Benchmark `/ls` on directory with 10,000 files
- [ ] Benchmark `/tree` on repository with 50,000 files
- [ ] Measure DirectoryTree lazy loading performance
- [ ] Measure Web file tree render time

---

## Documentation Updates

- [ ] Update `AGENTS.md` with new commands
- [ ] Add file tree section to ppxaide guide
- [ ] Document Web App sidebar in user manual
- [ ] Update CHANGELOG.md for each phase release
- [ ] Add keyboard shortcuts to keybindings reference

---

## Success Metrics

**Phase 0 (Commands):**
- Commands work in all 3 clients
- Performance: `/tree` completes in <2s on 10K file repo
- User feedback: Positive response to basic navigation

**Phase 1 (ppxaide Tree):**
- File tree renders in <500ms for typical projects
- Users can navigate without keyboard lag
- 80% of file operations done via tree (not commands)

**Phase 2 (Web Sidebar):**
- Sidebar loads in <1s for typical projects
- Search/filter performs in <100ms
- Users prefer sidebar over `/ls` command

---

## Future Enhancements (v1.17+)

- [ ] Git integration: show modified/new files with indicators
- [ ] File watchers: auto-refresh on file system changes
- [ ] Multi-root workspaces: browse multiple projects simultaneously
- [ ] Context menu: right-click with actions (copy path, reveal in system explorer)
- [ ] Drag-and-drop: drag file from tree to input for `@file` injection
- [ ] Quick open: `Ctrl+P` fuzzy search across all files (like VSCode)
- [ ] Breadcrumb navigation in header showing current path
- [ ] File preview on hover (tooltip with first few lines)
