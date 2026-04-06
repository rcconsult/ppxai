"""
Session operations — restore, export, history, usage, status, context.

Extracted from engine/client.py (v1.17.1) to reduce EngineClient size.
All functions take an engine reference as first parameter.
"""

import os
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..common.logger import get_logger
from ..config import get_default_model, get_model_context_limit, EXPORTS_DIR

logger = get_logger("engine")


def restore_session(engine, name: str) -> dict:
    """Load session file and restore all engine state.

    Reloads config, loads session, restores provider/model/tools/working_dir.

    Returns:
        dict with keys: success, provider, model, tools_enabled, working_dir,
        message_count, error
    """
    engine.reload_config()

    if not engine.session.load(name):
        return {"success": False, "error": f"Session not found: {name}"}

    engine.state.update(session_id=name, session_name=name)

    stored_provider = engine.session.metadata.get("provider")
    if stored_provider:
        try:
            engine.set_provider(stored_provider)
        except Exception as e:
            logger.warning(f"Failed to restore provider '{stored_provider}': {e}")

    stored_model = engine.session.metadata.get("model")
    if stored_model:
        if not engine.set_model(stored_model, strict=True, reset_context=False):
            provider_name = engine.provider_name if engine.provider else stored_provider
            default = get_default_model(provider_name) if provider_name else None
            if default:
                engine.set_model(default, reset_context=False)

    if engine.session.tools_enabled:
        engine.enable_tools()
    else:
        engine.disable_tools()

    wd = engine.session.working_dir
    if wd and os.path.isdir(wd):
        engine.set_working_dir(wd)

    return {
        "success": True,
        "provider": engine.provider_name,
        "model": engine.model,
        "tools_enabled": engine.tools_enabled,
        "working_dir": engine.get_working_dir(),
        "message_count": len(engine.session.messages),
    }


def get_history(engine) -> List[Dict[str, str]]:
    """Get conversation history as dicts."""
    return engine.session.get_messages_as_dicts()


def export_conversation(engine, filename: Optional[str] = None) -> Path:
    """Export conversation to markdown."""
    return engine.session.export(filename)


def export_answer(engine, filename: Optional[str] = None) -> Path:
    """Export last assistant answer to markdown.

    Raises:
        ValueError: If no assistant message found
    """
    last_assistant_msg = None
    for msg in reversed(engine.session.messages):
        if msg.role == 'assistant':
            last_assistant_msg = msg.text_content()
            break

    if not last_assistant_msg:
        raise ValueError("No assistant response to export yet")

    if not filename:
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        filename = f"answer_{timestamp}.md"

    if not filename.endswith('.md'):
        filename += '.md'

    filepath = EXPORTS_DIR / filename

    with open(filepath, 'w', encoding='utf-8') as f:
        f.write(last_assistant_msg)

    return filepath


def get_usage(engine) -> Dict[str, Any]:
    """Get usage statistics."""
    return engine.session.get_usage()


def get_status(engine) -> Dict[str, Any]:
    """Get current engine status."""
    return {
        "provider": engine.provider_name,
        "model": engine.model,
        "tools_enabled": engine.tools_enabled,
        "tool_count": len(engine.tool_manager.list_tools()) if engine.tools_enabled else 0,
        "auto_inject_context": engine.auto_inject_context,
        "has_api_key": engine.provider is not None,
        "message_count": len(engine.session.messages)
    }


def get_context_info(engine) -> Dict[str, Any]:
    """Get context usage information for /context command."""
    total_chars = sum(len(m.text_content()) for m in engine.session.messages)
    estimated_tokens = total_chars // 4
    context_limit = get_model_context_limit(engine.provider_name, engine.model)
    usage_percent = (estimated_tokens / context_limit) * 100 if context_limit > 0 else 0

    injected_size = sum(ctx.get('size', 0) for ctx in engine._injected_contexts)
    injected_tokens = injected_size // 4

    return {
        "estimated_tokens": estimated_tokens,
        "context_limit": context_limit,
        "usage_percent": usage_percent,
        "injected_contexts": engine._injected_contexts.copy(),
        "injected_tokens": injected_tokens,
        "message_count": len(engine.session.messages),
        "total_chars": total_chars,
        "provider": engine.provider_name,
        "model": engine.model
    }


def clear_injected_contexts(engine) -> int:
    """Clear tracked injected contexts and remove from message history.

    Returns:
        Number of injections removed
    """
    removed_count = len(engine._injected_contexts)

    if removed_count == 0:
        return 0

    injection_pattern = re.compile(
        r'\n---\n\*\*`@[^`]+`\*\*[^\n]*:\n```[^\n]*\n.*?```\n',
        re.DOTALL
    )

    for msg in engine.session.messages:
        if msg.role != "user":
            continue
        # For string content, apply the regex directly. For multimodal list
        # content, apply the regex only to text parts — image/file parts are
        # left untouched. Injected context blocks only ever appear in text.
        if isinstance(msg.content, str):
            msg.content = injection_pattern.sub('', msg.content)
        elif isinstance(msg.content, list):
            for block in msg.content:
                if isinstance(block, dict) and block.get("type") == "text":
                    block["text"] = injection_pattern.sub('', block.get("text", ""))

    engine._injected_contexts.clear()

    return removed_count
