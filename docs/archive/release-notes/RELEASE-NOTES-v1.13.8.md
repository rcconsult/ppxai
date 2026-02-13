# Release Notes - v1.13.8

**Release Date:** 2026-01-11

This is the final stabilization release in the v1.13.x series before v1.14.x. It focuses on data visualization features for the Desktop Web App and TUI, plus container management tools.

## Highlights

### Data Visualization

View CSV, TSV, JSON, YAML, TOML, and HCL files with rich formatting:

**TUI (Terminal)**
```bash
/show data.csv           # Interactive table with pagination
/show config.json        # Collapsible tree view
/show data.csv --source  # Raw syntax-highlighted view
```

**Web App**
- CSV/TSV files display as sortable, filterable tables
- JSON files display as expandable tree structures
- Toggle between "Rendered" and "Source" views with one click

### Container Management Tools

New AI-powered tools for Docker, Podman, and Kubernetes:

**Docker/Podman**
- `container_list` - List running/all containers
- `container_logs` - View container logs
- `container_start/stop/restart` - Manage container state
- `container_exec` - Run commands in containers

**Kubernetes**
- `pod_list`, `pod_logs`, `pod_describe` - Pod management
- `deployment_list`, `service_list` - Resource listing
- `kubectl_apply` - Apply manifests
- `namespace_list` - List namespaces

All destructive operations require user consent.

## New Features

### Data Format Detection
- Auto-detect format from file extension
- Content sniffing for ambiguous files
- Support for: CSV, TSV, JSON, JSONL, YAML, TOML, HCL, Terraform

### Interactive Viewers (TUI)
- **Table Viewer**: Pagination, row numbers, alternating row styles
- **Tree Viewer**: Expand/collapse nodes, depth control
- **View Toggle**: Press `s` to switch to source view, `r` to return

### Interactive Viewers (Web)
- **DataTableViewer**: Sortable columns, search filter, pagination
- **DataTreeViewer**: Expand all/collapse all, search, copy path
- **View Toggle**: Button in preview header to switch views

### Configuration Options

New `visualization` section in `ppxai-config.json`:
```json
{
  "visualization": {
    "max_rows": 10000,
    "page_size": 50,
    "tree_depth": 3,
    "auto_detect": true,
    "csv_delimiter": "auto"
  }
}
```

New `tools.container` section:
```json
{
  "tools": {
    "container": {
      "enabled": true,
      "require_consent": true,
      "timeout": 60
    }
  }
}
```

## Installation

### Optional Dependencies for YAML/HCL

```bash
# Install with data visualization extras
pip install ppxai[data]

# Or with uv
uv pip install ppxai[data]
```

This installs:
- `pyyaml>=6.0` - YAML parsing
- `python-hcl2>=4.3` - HCL/Terraform parsing

JSON, CSV, TSV, and TOML work without extra dependencies.

## Usage Examples

### View CSV Data
```
You: /show sales.csv
[Interactive table with pagination]

You: /show sales.csv --source
[Raw CSV with syntax highlighting]
```

### View JSON Configuration
```
You: /show package.json
[Collapsible tree view]
```

### Container Operations
```
You: List my running containers
AI: [Uses container_list tool]

You: Show logs from the nginx container
AI: [Uses container_logs tool]

You: Stop the redis container
AI: [Requests consent, then uses container_stop]
```

### Kubernetes Operations
```
You: What pods are running in the default namespace?
AI: [Uses pod_list tool]

You: Show logs from the api-server pod
AI: [Uses pod_logs tool]
```

## New Files

### Python Modules
- `ppxai/data/__init__.py` - Data module exports
- `ppxai/data/format_detector.py` - Format detection logic
- `ppxai/data/parsers.py` - CSV/JSON/YAML/TOML/HCL parsers
- `ppxai/data/renderers_tui.py` - Rich-based TUI renderers
- `ppxai/engine/tools/builtin/container.py` - Container management tools

### Web Components
- `ppxai/web/components/table-viewer.js` - Interactive table component
- `ppxai/web/components/tree-viewer.js` - Interactive tree component
- `ppxai/web/styles/data-viewers.css` - Viewer styling

### Tests
- `tests/test_data.py` - Data module unit tests
- `tests/fixtures/sample.csv` - Test CSV fixture
- `tests/fixtures/sample.json` - Test JSON fixture

## Modified Files

- `ppxai/commands.py` - Enhanced `/show` command with data viewers
- `ppxai/config.py` - Added `get_visualization_config()`, `get_container_config()`
- `ppxai/web/app.js` - Data viewer dispatch and toggle functionality
- `ppxai/web/index.html` - New viewer elements and script loading
- `ppxai/engine/tools/builtin/__init__.py` - Container tools registration
- `pyproject.toml` - Added optional `data` dependencies

## Compatibility

- **Python**: 3.11+
- **TUI**: Works out of the box
- **Web App**: Works out of the box
- **VSCode Extension**: Uses web viewers (no changes needed)

## Known Limitations

- YAML parsing requires `pyyaml` (optional dependency)
- HCL/Terraform parsing requires `python-hcl2` (optional dependency)
- Web app YAML/TOML/HCL parsing falls back to source view (no browser parsers)
- Container tools require Docker/Podman/kubectl to be installed and accessible
- **Container tools are new and may need additional testing** - please report issues on GitHub

## Upgrade Notes

This is a backward-compatible release. Existing configurations continue to work.

To use new visualization features with YAML/HCL:
```bash
pip install ppxai[data]
```

To enable container tools, ensure Docker/Podman or kubectl is installed and in PATH.
