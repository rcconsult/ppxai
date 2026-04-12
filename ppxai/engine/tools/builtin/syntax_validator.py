"""
Post-write syntax validator for file-editing tools (R13, v1.17.5).

Every file-mutating tool (`apply_patch`, `replace_block`, `insert_text`,
`delete_lines`, `write_file`) runs the candidate content through a
cheap language-specific syntax check **before** committing the write
to disk. If the validator rejects the content, the tool reverts to
the pre-edit state and returns an error instead of reporting success.

### Why

The failure mode we're guarding against is a **silent success on
corruption**. Discovered live during v1.17.4 release testing with
gemini-3.1-pro-preview: the model's `apply_patch` call had hunks
that targeted the right module but the **wrong function** — the
context-match heuristic landed on a same-indentation sibling and
inserted unreachable code referencing an out-of-scope variable. The
tool reported `"✓ Successfully applied patch (91 lines modified)"`
and walked away. The file was broken (`ast.parse` rejects it), but
the model had no signal and moved on to the next step.

Small/fast models (gemini-3.x, gpt-4-mini, vLLM-hosted) misalign
context with higher-than-rare frequency because their structured-output
quality drifts. Language-level validation is a cheap defense.

### Philosophy

- **Cheap validators only.** `ast.parse` for `.py`, `json.loads`
  for `.json`, etc. No linters, no type checkers, no imports — pure
  parser-level syntax.
- **Best effort.** If we don't have a validator for the extension
  (e.g. `.txt`, `.md`, `.sql`), we skip validation and apply. Never
  block writes we can't meaningfully check.
- **Fail closed.** When validation RUNS and fails, we revert. No
  "warning only" mode — a corrupted file that silently ships to prod
  is worse than a failed tool call that the model can retry with
  better context.
- **Error must be actionable.** The error message names the file,
  the detected language, and a suggestion ("re-read the file and
  include more context lines in your diff").

### Extension → validator

| Extension | Validator | Notes |
|-----------|-----------|-------|
| `.py`     | `ast.parse` | stdlib |
| `.json`   | `json.loads` | stdlib |
| `.yaml`, `.yml` | `yaml.safe_load` | pyyaml is a core dep |
| `.toml`   | `tomllib.loads` | stdlib in 3.11+ |
| `.js`, `.ts`, `.jsx`, `.tsx`, `.mjs`, `.cjs` | `node --check` via subprocess | best-effort, skipped if node not on PATH |
| anything else | — | skipped |
"""

from __future__ import annotations

import ast
import json
import logging
import os
import shutil
import subprocess
from pathlib import Path
from typing import Optional, Tuple

logger = logging.getLogger(__name__)


# Map extension → (language_name, validator_key). Normalised to lowercase
# without the leading dot so lookup is a straight `Path(...).suffix[1:].lower()`.
_EXT_LANG = {
    "py":    "python",
    "json":  "json",
    "yaml":  "yaml",
    "yml":   "yaml",
    "toml":  "toml",
    "js":    "javascript",
    "mjs":   "javascript",
    "cjs":   "javascript",
    "ts":    "typescript",
    "jsx":   "javascript",
    "tsx":   "typescript",
}


def _check_python(content: str) -> Optional[str]:
    """Return None if `content` parses; error string otherwise."""
    try:
        ast.parse(content)
        return None
    except SyntaxError as e:
        return f"line {e.lineno}: {e.msg}"
    except Exception as e:
        # Very rarely ast.parse raises non-SyntaxError (e.g., ValueError
        # on null bytes). Treat as a failure too — corrupted content
        # is not valid Python regardless of the exception type.
        return f"{type(e).__name__}: {e}"


def _check_json(content: str) -> Optional[str]:
    try:
        json.loads(content)
        return None
    except json.JSONDecodeError as e:
        return f"line {e.lineno} col {e.colno}: {e.msg}"
    except Exception as e:
        return f"{type(e).__name__}: {e}"


def _check_yaml(content: str) -> Optional[str]:
    try:
        import yaml  # deferred — pyyaml is a core dep but keep import tight
        yaml.safe_load(content)
        return None
    except ImportError:
        # Should never happen (pyyaml is declared), but if it does we
        # gracefully skip rather than breaking the write path.
        logger.debug("syntax_validator: pyyaml unavailable, skipping yaml check")
        return None
    except Exception as e:
        mark = getattr(e, "problem_mark", None)
        if mark is not None:
            return f"line {mark.line + 1} col {mark.column + 1}: {e}"
        return str(e)


def _check_toml(content: str) -> Optional[str]:
    try:
        import tomllib  # stdlib in 3.11+
        tomllib.loads(content)
        return None
    except Exception as e:
        return f"{type(e).__name__}: {e}"


def _check_js_like(content: str, kind: str) -> Optional[str]:
    """Best-effort syntax check via `node --check`.

    If `node` isn't on PATH we skip — we never want file editing to
    become unavailable in environments without a Node.js runtime. The
    cost of that skip is one occasional silent corruption on a
    JS/TS file; the cost of gating writes on `node` presence is
    breaking every fresh pyenv machine.

    `kind` is "javascript" or "typescript" — currently both use the
    same node check (node understands .js/.mjs/.cjs; for .ts/.tsx
    node doesn't natively parse without tsc, so we route both to a
    temp-file + `node --check` and accept that TS will false-positive
    on valid TS. Users who want strict TS validation can install
    `tsc` and we'll prefer it in a follow-up.
    """
    if shutil.which("node") is None:
        logger.debug("syntax_validator: node not on PATH, skipping %s check", kind)
        return None

    # For TypeScript we'd rather use tsc if available. Not wired yet —
    # see docstring. node --check on .ts will reject valid TS syntax
    # (interface, generics), so we only gate .js-family for now.
    if kind == "typescript":
        logger.debug(
            "syntax_validator: skipping typescript check (tsc integration TBD, "
            "node --check would false-positive on valid TS syntax)"
        )
        return None

    # Write the candidate to a tmp file and run `node --check`. node
    # doesn't accept stdin for --check, so a tmp file is the contract.
    import tempfile
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".js", delete=False, encoding="utf-8"
    ) as tmp:
        tmp.write(content)
        tmp_path = tmp.name
    try:
        result = subprocess.run(
            ["node", "--check", tmp_path],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0:
            return None
        # node --check writes errors to stderr with the tmp path in
        # them. Strip the tmp path so the model sees a clean message.
        stderr = (result.stderr or "").replace(tmp_path, "<file>").strip()
        # First non-empty line usually carries the message.
        first_line = next((ln for ln in stderr.splitlines() if ln.strip()), stderr)
        return first_line or "node --check failed without output"
    except subprocess.TimeoutExpired:
        logger.warning("syntax_validator: node --check timed out on %s", tmp_path)
        return None  # timeout is not a validation failure — skip
    except Exception as e:
        logger.debug("syntax_validator: node --check invocation failed: %s", e)
        return None
    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass


_VALIDATORS = {
    "python":     _check_python,
    "json":       _check_json,
    "yaml":       _check_yaml,
    "toml":       _check_toml,
    "javascript": lambda c: _check_js_like(c, "javascript"),
    "typescript": lambda c: _check_js_like(c, "typescript"),
}


def validate_candidate_content(
    file_path: str | Path,
    content: str,
) -> Tuple[bool, Optional[str], Optional[str]]:
    """Run a cheap syntax check on `content` keyed by `file_path`'s extension.

    Returns a triple of (ok, language, error_message):
      * `ok` is True if validation passed OR the extension isn't one
        we validate. Callers should proceed with the write in both
        cases — "unsupported extension" is a pass, not a fail.
      * `language` is the detected language name (`"python"`, ...),
        or None if the extension isn't recognised. Useful for error
        messages and logging.
      * `error_message` is None on success; on failure it's a short
        human/LLM-readable description ("line 42: expected ':'").

    Example:
        >>> ok, lang, err = validate_candidate_content("x.py", "def f(\\n")
        >>> ok, lang, bool(err)
        (False, 'python', True)
    """
    ext = Path(file_path).suffix.lstrip(".").lower()
    language = _EXT_LANG.get(ext)
    if language is None:
        return True, None, None

    validator = _VALIDATORS.get(language)
    if validator is None:
        # Extension mapped but no validator wired — treat as skip.
        return True, language, None

    try:
        err = validator(content)
    except Exception as e:
        # A bug in the validator itself must never block writes. Log
        # and treat as pass so the tool behaviour never regresses
        # because of our defense.
        logger.warning(
            "syntax_validator: unexpected %s in %s validator: %s",
            type(e).__name__, language, e,
        )
        return True, language, None

    if err is None:
        return True, language, None
    return False, language, err


def format_validation_error(
    file_path: str,
    language: str,
    error: str,
    tool_name: str,
) -> str:
    """Build a consistent error string for tool responses.

    All four file-editing tools emit the same phrasing when syntax
    validation rejects a write, so the model learns one retry
    strategy (re-read the file with more context, then re-emit the
    edit) regardless of which tool it chose.
    """
    return (
        f"Error: {tool_name} produced invalid {language} in {file_path} "
        f"({error}). File NOT modified. "
        f"This usually means the edit landed on the wrong lines — "
        f"re-read the file, include more surrounding context in the "
        f"diff/search block, and retry."
    )
