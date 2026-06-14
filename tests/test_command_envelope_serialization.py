"""Envelope serialization guard (debt item 32 / v1.18.8 Phase B).

`ConfirmationResult.details` is free-form and some commands populate it
with engine objects. The worst offender is `/load`
(`commands/session.py`), which stores raw `Message` dataclasses in
`details["messages"]` so the *in-process* Textual renderer can repaint the
transcript. Those objects are fine in-process but must never reach the HTTP
envelope (`POST /command/{name}` → `result.to_dict()` → JSON) as raw
dataclasses.

These tests pin the contract: `ConfirmationResult.to_dict()` output is
always `json.dumps`-able, and the in-process raw-object path is untouched.
"""

from __future__ import annotations

import json

from ppxai.commands.results import (
    ConfirmationResult,
    ResultStatus,
    _jsonsafe,
)
from ppxai.engine.types import Message


# ---------------------------------------------------------------------------
# The /load regression: Message objects in details must serialize cleanly.
# ---------------------------------------------------------------------------

def _load_result_with_messages() -> ConfirmationResult:
    """Mirror the shape `commands/session.py::handle_load` builds."""
    messages = [
        Message(role="user", content="hello"),
        Message(role="assistant", content="hi there"),
    ]
    return ConfirmationResult(
        status=ResultStatus.SUCCESS,
        message="Session loaded: demo",
        details={
            "session_name": "demo",
            "message_count": len(messages),
            "messages": messages,
            "action": "load_session",
            "tools_enabled": True,
        },
    )


def test_load_result_to_dict_is_json_serializable():
    """The exact /load envelope must round-trip through json.dumps."""
    d = _load_result_with_messages().to_dict()
    # Would raise TypeError if a raw Message dataclass leaked through.
    json.dumps(d)


def test_load_result_messages_become_dicts_with_role():
    """Raw Message objects are converted to plain dicts carrying role/content."""
    d = _load_result_with_messages().to_dict()
    msgs = d["details"]["messages"]
    assert isinstance(msgs, list) and len(msgs) == 2
    for m in msgs:
        assert isinstance(m, dict)
        assert m["role"] in ("user", "assistant")
    assert d["details"]["message_count"] == 2  # scalar passes through


def test_in_process_details_keep_raw_messages():
    """The fix must NOT mutate the live object: in-process consumers (Textual
    renderer) still read raw Message instances from result.details."""
    result = _load_result_with_messages()
    # to_dict() must not have rewritten the source details in place
    result.to_dict()
    assert all(isinstance(m, Message) for m in result.details["messages"])


# ---------------------------------------------------------------------------
# _jsonsafe unit coverage — the sanitizer behind the contract.
# ---------------------------------------------------------------------------

def test_jsonsafe_passes_primitives_and_containers():
    payload = {"a": 1, "b": [1, "x", True, None], "c": {"d": 2.5}}
    assert _jsonsafe(payload) == payload


def test_jsonsafe_converts_dataclass_recursively():
    out = _jsonsafe(Message(role="user", content="hi"))
    assert isinstance(out, dict)
    assert out["role"] == "user"
    json.dumps(out)


def test_jsonsafe_handles_bytes_and_unknown_objects():
    assert _jsonsafe(b"\x00\x01\x02") == "<3 bytes>"

    class Opaque:
        def __repr__(self):
            return "OPAQUE"

    assert _jsonsafe(Opaque()) == "OPAQUE"


def test_jsonsafe_prefers_to_dict_when_present():
    class HasToDict:
        def to_dict(self):
            return {"k": "v"}

    assert _jsonsafe(HasToDict()) == {"k": "v"}
