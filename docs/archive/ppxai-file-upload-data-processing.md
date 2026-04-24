# ppxai — File Upload & Data Processing Research (archived)
**Date:** April 3, 2026
**Status:** Archived 2026-04-24. Original research that drove v1.17.4
file upload (shipped). Pseudocode below is illustrative — the live
API has evolved (e.g. `has_vision_model` was renamed to
`has_vision_sidecar` in v1.17.4 and the back-compat alias was
removed in v1.18.0). For the current architecture see
[docs/ARCHITECTURE.md](../ARCHITECTURE.md) and the engine source.

---

## Overview

This document captures the full design for adding file upload to context in ppxai, with a focus on supporting data processing workflows involving Excel, PowerPoint, PDF, and mixed-modality files (charts, screenshots, visual data).

---

## 1. Architecture

### Core flow (all clients)

```
Client (TUI / VSCode / Web)
  → file picked/dropped → base64 encoded
  → POST /chat with { message, files: [{name, type, data}] }
  → EngineClient builds multimodal message content
  → LLM API (Anthropic/OpenAI support images + PDFs natively)
```

### Key design decision: lazy tool-based extraction

Rather than eagerly extracting file content before sending to the model, files are saved to a **session store** and a lightweight `<uploaded_file>` reference is injected into context. The model calls targeted tools when it needs content — selective, model-driven, context-efficient.

---

## 2. Model Capability Matrix

### Your DGX vLLM models

| Model | Type | Images | PDFs | Text/Code |
|---|---|---|---|---|
| GPT-OSS 120B AWQ4 | Text-only | ❌ auto-caption via VL | ✅ tool: `read_pdf` | ✅ decode |
| Qwen3.5-27B Dense | Text-only | ❌ auto-caption via VL | ✅ tool: `read_pdf` | ✅ decode |
| Qwen3-VL 8B | Vision-language | ✅ native | ✅ tool: `read_pdf` or `get_pdf_page_image` | ✅ decode |

### Important: Qwen3.5-27B is text-only at inference time

Qwen3.5's "unified vision-language foundation" refers to training methodology, not inference-time vision capability. The vLLM serve command uses `--language-model-only` — no vision encoder is loaded.

**Vision at inference requires Qwen3-VL** (separate model series, requires `vllm>=0.11.0`).

### vLLM serve commands

```bash
# Qwen3.5-27B (text only)
vllm serve Qwen/Qwen3.5-27B \
  --port 8000 --tensor-parallel-size 8 \
  --max-model-len 262144 \
  --reasoning-parser qwen3 \
  --enable-auto-tool-choice --tool-call-parser qwen3_coder

# Qwen3-VL 8B (vision)
vllm serve Qwen/Qwen3-VL-8B-Instruct \
  --port 8001 \
  --mm-encoder-tp-mode data \
  --mm-processor-cache-type shm
```

---

## 3. Preprocessing Strategy

### Provider/model routing

```python
def _is_vision_model(model: str) -> bool:
    vision_patterns = ["vl", "vision", "qwen3-vl", "llava", "pixtral", "minicpm-v"]
    return any(p in model.lower() for p in vision_patterns)
```

### Config-driven vision model registration (`config.yaml`)

```yaml
vision_model:
  endpoint: "http://dgx-node:8001/v1"
  model: "qwen3-vl-8b"
  auto_caption: true   # false = disable fallback for text-only models
```

### Preprocessing flow

```python
def preprocess_file(name, media_type, data, provider, model, engine_client=None):
    if media_type.startswith("image/"):
        if _is_vision_model(model):
            # Native vision — pass as image_url
            return [{"type": "image_url",
                     "image_url": {"url": f"data:{media_type};base64,{data}"}}]
        elif engine_client and engine_client.has_vision_model():
            # Auto-caption via Qwen3-VL 8B
            description = engine_client.caption_image(name, media_type, data)
            return [{"type": "text",
                     "text": f"<image name='{name}' captioned_by='qwen3-vl-8b'>\n{description}\n</image>"}]
        else:
            return [{"type": "text",
                     "text": f"[Image '{name}': no vision model available]"}]

    if media_type == "application/pdf":
        # Save raw bytes, inject reference — model calls read_pdf tool
        raw = base64.b64decode(data)
        file_id = SessionFileStore.save(name, raw)
        return [{"type": "text",
                 "text": f"<uploaded_file id='{file_id}' name='{name}' "
                         f"type='application/pdf' pages='{_get_page_count(raw)}'/>"}]

    # Text/code files — decode and inject inline
    raw = base64.b64decode(data).decode("utf-8", errors="replace")
    return [{"type": "text", "text": f"<file name='{name}'>\n{raw}\n</file>"}]
```

---

## 4. Session File Store

PDFs and binary files persist between upload and tool calls:

```python
# ppxai/session_store.py
import uuid, tempfile
from pathlib import Path

_store: dict[str, str] = {}
_tmp_dir = Path(tempfile.mkdtemp(prefix="ppxai_uploads_"))

class SessionFileStore:
    @staticmethod
    def save(name: str, data: bytes) -> str:
        file_id = f"upload_{uuid.uuid4().hex[:8]}"
        path = _tmp_dir / f"{file_id}_{name}"
        path.write_bytes(data)
        _store[file_id] = str(path)
        return file_id

    @staticmethod
    def get(file_id: str) -> str | None:
        return _store.get(file_id)

    @staticmethod
    def cleanup(file_id: str):
        path = _store.pop(file_id, None)
        if path:
            Path(path).unlink(missing_ok=True)
```

---

## 5. Tool Set

### PDF tools (`ppxai/tools/pdf_tools.py`)

| Tool | Purpose |
|---|---|
| `read_pdf(file_id, pages)` | Extract text. `pages`: "all", "3", or "2-5" |
| `get_pdf_page_image(file_id, page, dpi)` | Rasterize page to PNG base64 for VL model |

```python
def read_pdf(file_id: str, pages: str = "all") -> str:
    path = _resolve_session_file(file_id)
    reader = PdfReader(path)
    page_indices = _parse_page_range(pages, len(reader.pages))
    chunks = []
    for i in page_indices:
        text = reader.pages[i].extract_text() or "[no extractable text]"
        chunks.append(f"[Page {i+1}]\n{text}")
    return "\n\n".join(chunks)

def get_pdf_page_image(file_id: str, page: int = 1, dpi: int = 150) -> str:
    path = _resolve_session_file(file_id)
    images = convert_from_bytes(path.read_bytes(), dpi=dpi,
                                 first_page=page, last_page=page)
    buf = io.BytesIO()
    images[0].save(buf, format="PNG")
    return f"data:image/png;base64,{base64.b64encode(buf.getvalue()).decode()}"
```

### Excel tools (`ppxai/tools/excel_tools.py`)

| Tool | Purpose |
|---|---|
| `list_excel_sheets(file_id)` | Sheet names + row/col dimensions |
| `read_excel_sheet(file_id, sheet, rows, as_markdown)` | Sheet data as markdown table or CSV |
| `list_excel_charts(file_id, sheet)` | Chart titles and types per sheet |
| `render_excel_chart(file_id, sheet, chart_index)` | Rasterize chart to PNG via matplotlib |

### PowerPoint tools (`ppxai/tools/pptx_tools.py`)

| Tool | Purpose |
|---|---|
| `list_pptx_slides(file_id)` | Slide inventory with shape flags: TEXT, TABLE, CHART, IMAGE |
| `read_pptx_slide_text(file_id, slide)` | All text + tables from a slide as markdown |
| `render_pptx_slide(file_id, slide, dpi)` | Rasterize full slide via LibreOffice headless |
| `extract_pptx_images(file_id, slide)` | Extract embedded images/screenshots as base64 PNGs |

---

## 6. Model Workflow for Data Analyst Tasks

Example: *"Summarize the revenue trends across Q1-Q4 in this deck"*

```
1. list_pptx_slides(file_id)
   → finds slides 3, 7, 11 contain CHART

2. render_pptx_slide(file_id, slide=3)       ← sends to Qwen3-VL 8B
   → "Bar chart: Q1 EMEA 4.2M, APAC 3.1M..."

3. read_pptx_slide_text(file_id, slide=3)
   → extracts speaker notes / tables on same slide

4. Repeat for slides 7, 11

5. Synthesize trends across all extracted data
```

### Two-pass tool strategy

- **Pass 1 — structural inventory**: `list_pptx_slides`, `list_excel_sheets` — cheap, no vision
- **Pass 2 — selective deep read**: model calls targeted tools only for relevant pages/sheets/charts

---

## 7. Client Integration

### TUI — Textual (`Ctrl+U` to attach)

```python
BINDINGS = [("ctrl+u", "attach_file", "Attach file")]

def action_attach_file(self):
    self.push_screen(FilePathDialog(), self._on_file_selected)

def _on_file_selected(self, path: str | None):
    if not path:
        return
    p = Path(path).expanduser().resolve()
    media_type, _ = mimetypes.guess_type(str(p))
    data = base64.b64encode(p.read_bytes()).decode()
    self._pending_files.append({"name": p.name, "media_type": media_type, "data": data})
    self.notify(f"📎 {p.name} attached")
```

### VS Code / Web — file picker + drag-drop

```javascript
let pendingFiles = [];

async function handleFileSelect(event) {
    for (const file of Array.from(event.target.files)) {
        const base64 = await fileToBase64(file);
        pendingFiles.push({ name: file.name, media_type: file.type, data: base64 });
        renderAttachmentBadge(file.name);
    }
}

// In send:
vscode.postMessage({ type: 'chat', message: text, files: pendingFiles });
pendingFiles = [];
```

---

## 8. Dependencies

```toml
[project.optional-dependencies]
data = [
    "openpyxl>=3.1",        # Excel read/write + chart access
    "python-pptx>=1.0",     # PowerPoint parsing
    "pypdf>=4.0",           # PDF text extraction
    "pdf2image>=1.17",      # PDF rasterization (needs poppler system package)
    "matplotlib>=3.9",      # Chart re-rendering from Excel data
]
```

**System dependencies:**
- `poppler-utils` — for `pdf2image` PDF rasterization
- `libreoffice` (headless) — for PPTX full-slide rendering (already available on Ubuntu/DGX nodes)

---

## 9. Tool Registration Summary

```python
DATA_TOOLS = [
    # Excel
    ("list_excel_sheets",   list_excel_sheets,   "List sheets and dimensions"),
    ("read_excel_sheet",    read_excel_sheet,    "Read sheet data as markdown table"),
    ("list_excel_charts",   list_excel_charts,   "List embedded charts in a sheet"),
    ("render_excel_chart",  render_excel_chart,  "Rasterize chart to PNG for vision"),
    # PowerPoint
    ("list_pptx_slides",      list_pptx_slides,      "Inventory slides with shape flags"),
    ("read_pptx_slide_text",  read_pptx_slide_text,  "Extract text and tables from slide"),
    ("render_pptx_slide",     render_pptx_slide,     "Rasterize full slide to PNG"),
    ("extract_pptx_images",   extract_pptx_images,   "Extract embedded images from slide"),
    # PDF
    ("read_pdf",              read_pdf,              "Extract text from PDF pages"),
    ("get_pdf_page_image",    get_pdf_page_image,    "Rasterize PDF page to PNG"),
]
```

---

## 10. Open Items

- [ ] `_render_chart_to_axes()` — matplotlib Excel chart re-render from openpyxl chart data
- [ ] Session cleanup hooks — purge temp files when conversation ends
- [ ] `vision_model` config section wired into ppxai's existing config system
- [ ] File size guard (default: 10MB cap, base64-adjusted)
- [ ] Provider capability check — reject image uploads for Perplexity / text-only endpoints without VL fallback
- [ ] Scanned PDF support — rasterize + route pages through Qwen3-VL 8B (v2 scope)
- [ ] DOCX support — `python-docx` text extraction for Office Word files
