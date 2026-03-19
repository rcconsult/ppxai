"""
Web tools: web_search, fetch_url, get_weather.

These tools are provider-aware - providers with native web capabilities
(like Perplexity) won't have these registered.
"""

import os
import re
import ssl
import urllib.request
import urllib.parse
import urllib.error
from ...types import ToolManagerProtocol


def _create_ssl_context() -> ssl.SSLContext:
    """Create SSL context respecting SSL_VERIFY and SSL_CERT_FILE env vars.

    Consistent with BaseProvider (base.py) pattern for corporate proxy support.
    """
    ssl_verify = os.getenv("SSL_VERIFY", "true").lower()
    ssl_cert_file = os.getenv("SSL_CERT_FILE", "")

    if ssl_verify == "false":
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        return ctx
    elif ssl_cert_file and os.path.exists(ssl_cert_file):
        return ssl.create_default_context(cafile=ssl_cert_file)
    else:
        return ssl.create_default_context()


def _get_web_timeout(tool_name: str, default: int = 15) -> int:
    """Get timeout for a web tool from config.

    Reads from tools.<tool_name>.timeout in ppxai-config.json.
    """
    try:
        from ppxai.config import get_tool_config
        config = get_tool_config(tool_name)
        return config.get("timeout", default)
    except Exception:
        return default


def get_weather(location: str, format: str = "short") -> str:
    """Get weather forecast for a location using wttr.in.

    Args:
        location: City name, optionally with country
        format: 'short', 'detailed', or 'forecast'

    Returns:
        Weather information
    """
    timeout = _get_web_timeout("get_weather", default=15)

    if format == "short":
        path = f"{urllib.parse.quote(location)}?format=4"
    elif format == "detailed":
        path = f"{urllib.parse.quote(location)}?0&m"
    else:
        path = f"{urllib.parse.quote(location)}?2&m"

    # Try HTTPS first, fall back to HTTP (wttr.in supports both).
    # Corporate proxies with SSL inspection can stall HTTPS handshakes.
    last_error = None
    for scheme in ("https", "http"):
        try:
            url = f"{scheme}://wttr.in/{path}"
            ctx = _create_ssl_context() if scheme == "https" else None
            req = urllib.request.Request(
                url,
                headers={"User-Agent": "curl/7.68.0"}
            )

            with urllib.request.urlopen(req, timeout=timeout, context=ctx) as response:
                result = response.read().decode('utf-8')

            # Clean up ANSI codes
            result = re.sub(r'\x1b\[[0-9;]*m', '', result)
            return f"Weather for {location}:\n{result}"

        except urllib.error.HTTPError as e:
            if e.code == 404:
                return f"Error: Location '{location}' not found. Try a different city name or format like 'Geneva,Switzerland'"
            last_error = f"Error fetching weather: HTTP {e.code}"
            break  # HTTP errors won't be fixed by switching scheme
        except (urllib.error.URLError, ssl.SSLError, OSError) as e:
            last_error = f"Error: Could not connect to weather service. {str(getattr(e, 'reason', e))}"
            if scheme == "https":
                continue  # Fall back to HTTP
        except Exception as e:
            last_error = f"Error getting weather: {str(e)}"
            break

    return last_error or "Error getting weather: unknown error"


# Try to import ddgs package (optional dependency, v1.12.4+)
# Supports both 'ddgs' (newer) and 'duckduckgo-search' (older) packages
_ddg_available = False
try:
    from ddgs import DDGS
    _ddg_available = True
except ImportError:
    try:
        from duckduckgo_search import DDGS
        _ddg_available = True
    except ImportError:
        pass


def _web_search_ddg_package(query: str, num_results: int = 5) -> str:
    """Search using duckduckgo-search package (more reliable)."""
    try:
        with DDGS() as ddgs:
            results = list(ddgs.text(query, max_results=min(num_results, 10)))

        if not results:
            return f"[via duckduckgo]\n\nNo results found for '{query}'"

        formatted = []
        for i, r in enumerate(results, 1):
            title = r.get('title', 'No title')
            url = r.get('href', r.get('link', ''))
            snippet = r.get('body', '')[:200]
            formatted.append(f"{i}. {title}\n   URL: {url}\n   {snippet}\n")

        return f"[via duckduckgo]\n\nSearch results for '{query}':\n\n" + "\n".join(formatted)

    except Exception as e:
        # Fall back to HTML scraping on any error
        return _web_search_html_fallback(query, num_results)


def _web_search_html_fallback(query: str, num_results: int = 5) -> str:
    """Fallback: Search using DuckDuckGo HTML interface (no package needed)."""
    ssl_context = _create_ssl_context()
    timeout = _get_web_timeout("web_search", default=15)

    try:
        encoded_query = urllib.parse.quote_plus(query)
        url = f"https://html.duckduckgo.com/html/?q={encoded_query}"

        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
            }
        )

        with urllib.request.urlopen(req, timeout=timeout, context=ssl_context) as response:
            html = response.read().decode('utf-8')

        results = []
        result_pattern = r'<a[^>]*class="result__a"[^>]*href="([^"]*)"[^>]*>([^<]*)</a>'
        snippet_pattern = r'<a[^>]*class="result__snippet"[^>]*>([^<]*(?:<[^>]*>[^<]*)*)</a>'

        links = re.findall(result_pattern, html)
        snippets = re.findall(snippet_pattern, html)

        for i, (link, title) in enumerate(links[:num_results]):
            if 'uddg=' in link:
                match = re.search(r'uddg=([^&]*)', link)
                if match:
                    link = urllib.parse.unquote(match.group(1))

            snippet = ""
            if i < len(snippets):
                snippet = re.sub(r'<[^>]*>', '', snippets[i])
                snippet = snippet.strip()[:200]

            results.append(f"{i+1}. {title}\n   URL: {link}\n   {snippet}\n")

        if not results:
            return f"[via duckduckgo]\n\nNo results found for '{query}'"

        return f"[via duckduckgo]\n\nSearch results for '{query}':\n\n" + "\n".join(results)

    except urllib.error.URLError as e:
        return f"Error: Could not connect to search service. {str(e.reason)}"
    except Exception as e:
        return f"Error searching: {str(e)}"


def web_search(query: str, num_results: int = 5) -> str:
    """Search the web using DuckDuckGo.

    Uses duckduckgo-search package if available (more reliable),
    falls back to HTML scraping otherwise.

    Args:
        query: Search query
        num_results: Number of results (default: 5, max: 10)

    Returns:
        Search results
    """
    if _ddg_available:
        return _web_search_ddg_package(query, num_results)
    else:
        return _web_search_html_fallback(query, num_results)


def fetch_url(url: str, max_length: int = 5000) -> str:
    """Fetch and extract text content from a URL.

    Args:
        url: URL to fetch
        max_length: Maximum characters (default: 5000)

    Returns:
        Page content
    """
    ssl_context = _create_ssl_context()
    timeout = _get_web_timeout("fetch_url", default=15)

    try:
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
            }
        )

        with urllib.request.urlopen(req, timeout=timeout, context=ssl_context) as response:
            content_type = response.headers.get('Content-Type', '')
            if 'text/html' not in content_type and 'text/plain' not in content_type:
                return f"Error: URL returns non-text content ({content_type})"

            html = response.read().decode('utf-8', errors='ignore')

        # Extract title
        title_match = re.search(r'<title[^>]*>([^<]*)</title>', html, re.IGNORECASE)
        title = title_match.group(1).strip() if title_match else "No title"

        # Remove script and style elements
        html = re.sub(r'<script[^>]*>.*?</script>', '', html, flags=re.DOTALL | re.IGNORECASE)
        html = re.sub(r'<style[^>]*>.*?</style>', '', html, flags=re.DOTALL | re.IGNORECASE)
        html = re.sub(r'<nav[^>]*>.*?</nav>', '', html, flags=re.DOTALL | re.IGNORECASE)
        html = re.sub(r'<footer[^>]*>.*?</footer>', '', html, flags=re.DOTALL | re.IGNORECASE)

        # Remove HTML tags
        text = re.sub(r'<[^>]+>', ' ', html)

        # Clean up whitespace
        text = re.sub(r'\s+', ' ', text).strip()

        # Truncate if too long
        if len(text) > max_length:
            text = text[:max_length] + "... [truncated]"

        return f"Title: {title}\nURL: {url}\n\nContent:\n{text}"

    except urllib.error.HTTPError as e:
        return f"Error: HTTP {e.code} - {e.reason}"
    except urllib.error.URLError as e:
        return f"Error: Could not connect to URL. {str(e.reason)}"
    except Exception as e:
        return f"Error fetching URL: {str(e)}"


def register_tools(manager: ToolManagerProtocol, provider: str = None):
    """Register web tools with the manager.

    These tools are excluded for providers with native capabilities.

    Args:
        manager: ToolManager instance
        provider: Current provider name
    """
    # Providers with native web capabilities don't need these tools
    # - perplexity: Native web search with citations
    # NOTE: Gemini removed from exclusion list (v1.15.2) because grounding is
    # disabled when native tool calling is active. Gemini needs web_search/get_weather
    # tools in agent mode to get web info via wttr.in or separate grounding API call.
    providers_with_web_search = ["perplexity"]
    providers_with_weather = ["perplexity"]

    manager.register_function(
        name="get_weather",
        description="Get current weather and forecast for a location. Uses wttr.in service (no API key needed)",
        parameters={
            "type": "object",
            "properties": {
                "location": {
                    "type": "string",
                    "description": "City name, optionally with country (e.g., 'Geneva', 'Geneva,Switzerland', 'New York', 'Tokyo')"
                },
                "format": {
                    "type": "string",
                    "description": "Output format: 'short' (one line), 'detailed' (current only), 'forecast' (2-day forecast)",
                    "enum": ["short", "detailed", "forecast"]
                }
            },
            "required": ["location"]
        },
        handler=get_weather,
        provider_excluded=providers_with_weather
    )

    manager.register_function(
        name="web_search",
        description="Search the web using DuckDuckGo. Returns titles, URLs, and snippets of top results",
        parameters={
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Search query (e.g., 'Python tutorials', 'weather API documentation')"
                },
                "num_results": {
                    "type": "integer",
                    "description": "Number of results to return (default: 5, max: 10)"
                }
            },
            "required": ["query"]
        },
        handler=web_search,
        provider_excluded=providers_with_web_search
    )

    manager.register_function(
        name="fetch_url",
        description="Fetch and read the text content of a web page URL",
        parameters={
            "type": "object",
            "properties": {
                "url": {
                    "type": "string",
                    "description": "Full URL to fetch (e.g., 'https://example.com/page')"
                },
                "max_length": {
                    "type": "integer",
                    "description": "Maximum characters to return (default: 5000)"
                }
            },
            "required": ["url"]
        },
        handler=fetch_url,
        provider_excluded=providers_with_web_search  # Perplexity can fetch URLs via search
    )
