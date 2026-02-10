# Bugfix: Web Tools Failing in Corporate Proxy Environments

**Date:** 2026-02-10
**Status:** Planned (not yet implemented)
**Severity:** Medium — tools time out silently, fallback to `web_search` (Perplexity) works
**Affects:** `get_weather`, `fetch_url`, `_web_search_html_fallback` in `ppxai/engine/tools/builtin/web.py`
**Session:**  "C:\Users\radovan.chytracek\.ppxai\sessions\session_20260210_140416.json"
**Debug log:** "C:\Users\radovan.chytracek\.ppxai\logs\tui-debug.log"

---

## Problem

The three urllib-based web tools in `web.py` fail behind corporate firewalls (tested with Fortinet SSL inspection). Observed during a live session on 2026-02-10 with GPT-OSS 120B:

| Attempt | Result |
|---------|--------|
| `get_weather("Lausanne")` | "The read operation timed out" (10s) |
| `curl -s "http://wttr.in/Lausanne"` | **Worked** — plain HTTP passes through proxy |
| `curl -k -s "https://wttr.in/..."` | Timeout (120s) — HTTPS handshake stalls |
| `curl --cacert Fortinet_CA_SSL.cer ...` | Exit 60 — cert doesn't cover wttr.in chain |
| `web_search` (Perplexity) | **Worked** — uses httpx with `SSL_VERIFY` support |

The LLM successfully fell back to `web_search` (Perplexity API) and retrieved the weather, but the native `get_weather` tool is unusable.

## Root Causes

### 1. HTTPS-only with 10-second timeout

```python
# web.py:47 — hardcoded HTTPS, 10s timeout
url = f"https://wttr.in/{urllib.parse.quote(location)}?format=4"
with urllib.request.urlopen(req, timeout=10, context=ssl_context) as response:
```

Corporate proxies performing deep SSL inspection add significant latency to TLS handshakes. A 10-second timeout is insufficient. Plain HTTP (which bypasses TLS inspection) works fine.

### 2. SSL env vars ignored

```python
# web.py:29-32 — always disables verification, ignores SSL_CERT_FILE
ssl_context = ssl.create_default_context()
ssl_context.check_hostname = False
ssl_context.verify_mode = ssl.CERT_NONE
```

Compared to `BaseProvider` (base.py:54-78) which correctly reads `SSL_VERIFY` and `SSL_CERT_FILE`:

```python
# base.py — the correct pattern
ssl_verify_env = os.getenv("SSL_VERIFY", "true").lower()
ssl_cert_file = os.getenv("SSL_CERT_FILE", "")
if ssl_verify_env == "false":
    http_client = httpx.Client(verify=False)
elif ssl_cert_file:
    http_client = httpx.Client(verify=ssl_cert_file)
```

### 3. No HTTP fallback

`wttr.in` supports both HTTP and HTTPS, but the code only tries HTTPS. When the proxy blocks/stalls HTTPS, there's no recovery path.

### 4. No configurable timeout

Unlike `tools.shell.timeout` (default 30s) and `tools.container.timeout` (default 60s), the web tools have hardcoded timeouts with no config override.

## SSL Handling Inconsistency Across Codebase

| Component | HTTP Library | SSL_VERIFY | SSL_CERT_FILE | Timeout |
|-----------|-------------|------------|---------------|---------|
| **BaseProvider** | httpx | Yes | Yes | N/A |
| **web_premium.py** | httpx | Yes (bool only) | No | 30s |
| **web.py (free tools)** | urllib | **No** | **No** | **10-15s hardcoded** |
| **context.py (_fetch_url)** | httpx | No | No | 30s |

---

## Proposed Fix

### Change 1: Shared SSL context helper

Add `_create_ssl_context()` to `web.py` mirroring the `BaseProvider` pattern:

```python
import os

def _create_ssl_context() -> ssl.SSLContext:
    """Create SSL context respecting SSL_VERIFY and SSL_CERT_FILE env vars.

    Consistent with BaseProvider (base.py:54-78) pattern.
    """
    ssl_verify = os.getenv("SSL_VERIFY", "true").lower()
    ssl_cert_file = os.getenv("SSL_CERT_FILE", "")

    if ssl_verify == "false":
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        return ctx
    elif ssl_cert_file and os.path.exists(ssl_cert_file):
        ctx = ssl.create_default_context(cafile=ssl_cert_file)
        return ctx
    else:
        return ssl.create_default_context()
```

Replace all 3 hardcoded `ssl.CERT_NONE` blocks in `get_weather()`, `_web_search_html_fallback()`, and `fetch_url()`.

### Change 2: HTTP fallback for `get_weather`

Try HTTPS first, fall back to HTTP on timeout/SSL failure. Only for `get_weather` (wttr.in supports both protocols). `fetch_url` and `web_search` keep HTTPS-only since we don't control the target URLs.

```python
for scheme in ("https", "http"):
    try:
        url = f"{scheme}://wttr.in/{urllib.parse.quote(location)}?format=4"
        ctx = _create_ssl_context() if scheme == "https" else None
        req = urllib.request.Request(url, headers={"User-Agent": "curl/7.68.0"})
        with urllib.request.urlopen(req, timeout=timeout, context=ctx) as response:
            result = response.read().decode('utf-8')
        # ... clean and return
    except (urllib.error.URLError, ssl.SSLError, OSError):
        if scheme == "https":
            continue  # Fall back to HTTP
        raise
```

### Change 3: Configurable timeout via existing config system

Use `get_tool_config()` (already exists in `ppxai/config/__init__.py`):

```python
from ppxai.config import get_tool_config

def _get_web_timeout(tool_name: str, default: int = 15) -> int:
    """Get timeout for a web tool from config."""
    config = get_tool_config(tool_name)
    return config.get("timeout", default)
```

Applied timeouts:

| Function | Current | New Default | Config Key |
|----------|---------|-------------|------------|
| `get_weather` | 10s | 15s | `tools.get_weather.timeout` |
| `fetch_url` | 15s | 15s | `tools.fetch_url.timeout` |
| `_web_search_html_fallback` | 15s | 15s | `tools.web_search.timeout` |

### Change 4: Update example config

Add to `ppxai-config.example.json` under `tools`:

```json
"get_weather": {
    "timeout": 15
},
"fetch_url": {
    "timeout": 15
}
```

### Change 5: Tests

New file `tests/test_web_tools_ssl.py` (~7 tests):

- `_create_ssl_context()` with `SSL_VERIFY=false` returns `CERT_NONE`
- `_create_ssl_context()` with `SSL_CERT_FILE` set loads custom CA
- `_create_ssl_context()` with defaults uses system certs
- `_create_ssl_context()` with non-existent `SSL_CERT_FILE` falls back to system certs
- `get_weather` HTTP fallback when HTTPS times out (mock urllib)
- `_get_web_timeout()` reads from config
- `_get_web_timeout()` returns default when no config

---

## Files to Modify

| File | Change |
|------|--------|
| `ppxai/engine/tools/builtin/web.py` | Add helpers, HTTP fallback, replace hardcoded SSL |
| `ppxai-config.example.json` | Add timeout config examples |
| `tests/test_web_tools_ssl.py` | New test file |

## Verification

1. **Unit tests:** `.uv\uv run pytest tests/test_web_tools_ssl.py -v`
2. **Full regression:** `.uv\uv run pytest tests/ -v`
3. **Manual behind proxy:** Run ppxai → `get_weather` tool → confirm HTTP fallback works
4. **Manual with cert:** Set `SSL_VERIFY=true` + `SSL_CERT_FILE=<path>` → confirm cert is loaded

## Notes

- `web_premium.py` is **not** affected — it already uses httpx with `SSL_VERIFY` support
- `fetch_url` and `web_search` do **not** get HTTP fallback — we don't control their target URLs
- The `context.py:_fetch_url()` has a similar gap (no `SSL_VERIFY` support) but is out of scope for this fix
