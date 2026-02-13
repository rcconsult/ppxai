# ppxai v1.13.5 Release Notes

**Release Date**: January 8, 2026

## Critical Bug Fix: Session Isolation

This release fixes a critical bug where VSCode extension and Desktop Web App shared the same server session, causing working directory changes in one client to affect the other.

### The Problem

When both VSCode and the Desktop Web App connected to the same ppxai-server:
- Working directory set by VSCode would affect the web app
- Conversation history was shared between clients
- Tool consent state leaked between sessions
- LLM context was confused by mixed workspace information

### The Solution

Each client now gets an isolated session via `X-Session-Id` HTTP header:

| Client | Session ID Format | Storage |
|--------|-------------------|---------|
| VSCode Extension | `vscode-{uuid}` | Per extension instance |
| Desktop Web App | `webapp-{uuid}` | Browser sessionStorage (per tab) |
| Legacy clients | `default` | Shared (backward compatible) |

### Per-Session Isolation

Each session maintains its own:
- Conversation history
- Working directory
- Provider and model selection
- Tool consent state (file edit, shell command)
- Usage statistics

### Session Lifecycle

- Sessions expire after 1 hour of inactivity
- Usage data is saved before session cleanup
- Server shutdown saves all session usage to persistent storage

## New Features

### Session Monitoring Endpoint

New endpoint for debugging active sessions:

```bash
curl http://127.0.0.1:54320/sessions/list
```

Returns:
```json
{
  "sessions": [
    {
      "session_id": "vscode-abc123",
      "created_at": 1736300000,
      "last_used": 1736303600,
      "provider": "perplexity",
      "model": "sonar-pro",
      "message_count": 5,
      "working_dir": "/path/to/project"
    }
  ],
  "count": 1,
  "default_engine_active": true
}
```

## Technical Details

### Server Changes (`ppxai/server/http.py`)

- Added `sessions` dict to manage per-session EngineClient instances
- Added `get_or_create_session()` function for session routing
- Consent requests keyed by `(session_id, file_path)` tuple
- Each session has its own `asyncio.Lock` for request serialization
- Session cleanup runs before listing active sessions

### VSCode Extension (`vscode-extension/src/httpClient.ts`)

- Added `_sessionId` property with UUID generation
- Added `getHeaders()` method that includes `X-Session-Id`
- All fetch calls now include session headers

### Desktop Web App (`ppxai/web/app.js`)

- Session ID stored in `sessionStorage` (per browser tab)
- Added `getSessionHeaders()` method
- All 40+ fetch calls updated to include session headers

## Upgrade Notes

- No configuration changes required
- Existing clients without session ID continue to work (use shared default engine)
- Clear browser sessionStorage to get a new session ID if needed

## Files Changed

- `ppxai/server/http.py` - Session management logic
- `vscode-extension/src/httpClient.ts` - Session ID generation and headers
- `ppxai/web/app.js` - Session ID for web app
- `ppxai/web/shared/api-client.js` - Session ID for shared API client
