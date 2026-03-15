"""
Pydantic request/response models for the ppxai HTTP server.
"""

from typing import Optional

from pydantic import BaseModel


class ChatRequest(BaseModel):
    """Chat request body."""
    message: str
    provider: Optional[str] = None
    model: Optional[str] = None


class CodingTaskRequest(BaseModel):
    """Coding task request body."""
    message: str
    task_type: str = "generate"  # generate, debug, explain, test, docs, implement
    provider: Optional[str] = None
    model: Optional[str] = None


class SetProviderRequest(BaseModel):
    """Set provider request body."""
    provider: str
    model: Optional[str] = None
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
    """Request to read a file."""
    path: str


class FileSearchRequest(BaseModel):
    """Request to search for files."""
    query: str = ""
    max_results: int = 50


class FileWriteRequest(BaseModel):
    """Request to write a file."""
    path: str
    content: str


class UsageDisplayModeRequest(BaseModel):
    """Request body for setting usage display mode."""
    mode: str  # "session", "provider", "model", or "off"


class CommandRequest(BaseModel):
    """Request body for command execution."""
    args: str = ""
