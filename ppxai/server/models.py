"""
Pydantic request/response models for the ppxai HTTP server.
"""


from pydantic import BaseModel, Field


class FileAttachment(BaseModel):
    """A file attached to a chat request (v1.17.4 Phase 3.1).

    Clients (web app drag-drop, VSCode file picker) base64-encode the
    file bytes and include them in the `files` array of a ChatRequest.
    The server chat route decodes, validates via `preprocess_file`, and
    builds multimodal content parts.

    Attributes:
        name: Original filename (basename only).
        media_type: MIME type (e.g. "image/png", "application/pdf").
                    Used as a hint — the preprocessing pipeline may
                    override it via magic-byte sniffing for images.
        data: Base64-encoded file bytes.
    """
    name: str
    media_type: str
    data: str  # base64


class ChatRequest(BaseModel):
    """Chat request body.

    v1.17.4 Phase 3.1: Added optional `files` array for multimodal
    attachments. When present, each file is preprocessed through
    `engine.file_preprocessing.preprocess_file` and merged into the
    user message as multimodal content parts (image_url blocks for
    images, `<uploaded_file>` references for PDFs/Office, inline
    `<file>` blocks for text/code). The chat route builds the content
    list exactly the way the Rich TUI's `build_multimodal_content`
    does — same pipeline, same validation, same vision routing.
    """
    message: str
    provider: str | None = None
    model: str | None = None
    files: list[FileAttachment] = Field(default_factory=list)


class CodingTaskRequest(BaseModel):
    """Coding task request body."""
    message: str
    task_type: str = "generate"  # generate, debug, explain, test, docs, implement
    provider: str | None = None
    model: str | None = None


class SetProviderRequest(BaseModel):
    """Set provider request body."""
    provider: str
    model: str | None = None
    reset_context: bool = True


class SetModelRequest(BaseModel):
    """Set model request body."""
    model: str
    reset_context: bool = True


class ToolsRequest(BaseModel):
    """Tools configuration request body."""
    enabled: bool


class ToolsConfigRequest(BaseModel):
    """Tools config request body."""
    setting: str
    value: str


class WorkingDirRequest(BaseModel):
    """Set working directory request body."""
    path: str


class AutoInjectRequest(BaseModel):
    """Set auto-inject context request body."""
    enabled: bool


class ConsentRequest(BaseModel):
    """File edit consent response (Phase 1C: v1.11.0)."""
    file_path: str
    response: str  # 'y', 'n', 'always', 'never'


class ShellConsentRequest(BaseModel):
    """Shell command consent response (v1.11.2)."""
    command: str
    working_dir: str = "."
    response: str  # 'y', 'n', 'always', 'never'


class FileReadRequest(BaseModel):
    """Request to read a file.

    cwd_anchor (v1.18.1 Phase D): the working_dir the client thinks
    the relpath is anchored against. If the engine's current cwd
    differs, the route returns 409 with the new cwd in the body so
    the client can refresh and retry. None means "don't check" —
    backward-compatible for callers that haven't been updated yet.
    """
    path: str
    cwd_anchor: str | None = None


class FileSearchRequest(BaseModel):
    """Request to search for files."""
    query: str = ""
    max_results: int = 50


class FileWriteRequest(BaseModel):
    """Request to write a file.

    cwd_anchor: same semantics as FileReadRequest.
    """
    path: str
    content: str
    cwd_anchor: str | None = None


class UsageDisplayModeRequest(BaseModel):
    """Request body for setting usage display mode."""
    mode: str  # "session", "provider", "model", or "off"


class CommandRequest(BaseModel):
    """Request body for command execution.

    ADR 0007 step 2: `client` is optional and additive. One HTTP surface
    serves both web and VSCode, so without it a handler can only gate on
    the `SERVER_CLIENTS` candidate set and over-lists a command gated to
    just one of them (e.g. `/help`). A client that names itself gets the
    exact gate. Omitting it is valid and keeps the pre-step-2 behaviour
    — the same optional-`client` shape `POST /complete` already uses.
    Validated against `KNOWN_CLIENTS` by the route (400 if unknown).
    """
    args: str = ""
    client: str | None = None


class PreviewServeRequest(BaseModel):
    """Request to start a backend process for preview serving."""
    filepath: str = ""
    command: str | None = None
    port: int | None = None
