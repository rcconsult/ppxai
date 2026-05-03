# Pattern: Transactional State Management

**Added:** v1.15.0
**Status:** **CRITICAL — Apply to all multi-step state operations**

## Problem

AI agents perform multi-step operations that must succeed atomically or fail completely. Partial state updates create inconsistent UI, broken sessions, and user confusion.

## Solution: GitOps-Style Transactions

```python
with status_bar.transaction() as txn:
    txn.add("tokens", "Tokens", "1234")
    txn.update("provider", "ollama")
    txn.remove("cost")
    success, error = txn.commit()
    if not success:
        # All changes rolled back automatically
        notify_user(f"Update failed: {error}")
```

## Components

1. **Checkpoint** — automatic backup of current state on transaction enter
2. **Stage operations** — chainable operations queued for validation
3. **Validate** — all operations checked before any are applied
4. **Commit** — atomic application (all succeed or none do)
5. **Rollback** — restore checkpoint on failure or exception

## Where to Apply

REQUIRED for:
- Provider/model switching with related config updates
- Context injection with multiple files
- Session state updates (messages + tokens + cost)
- Multi-step tool execution
- UI state synchronization across multiple widgets

## Example: Provider Switch

```python
async def switch_provider(new_provider: str, new_model: str):
    with status_bar.transaction() as txn:
        txn.update("provider", new_provider)
        txn.update("model", new_model)
        if new_provider == "perplexity":
            txn.add("web", "Web", "ON")
            txn.remove("thinking")
        success, error = txn.commit()
        if not success:
            notify(f"UI update failed: {error}")
            return False

    try:
        await engine_client.set_provider(new_provider)
        await engine_client.set_model(new_model)
        return True
    except Exception as e:
        with status_bar.transaction() as txn:
            txn.update("provider", old_provider)
            txn.update("model", old_model)
            txn.commit()
        notify(f"Engine error: {e}")
        return False
```

## Implementation Status

- StatusBar badge management (`ppxai/tui/widgets/status_bar.py`)
- Provider/model switching (badge updates in `_restore_session`, `handle_load`)
- Session state management (`EngineClient.restore_session()` — atomic restore)
- Context injection — planned

**Rule:** Any operation that modifies multiple related pieces of state MUST use this pattern.
