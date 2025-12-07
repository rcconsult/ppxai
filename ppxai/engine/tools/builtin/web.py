"""
Web tools: web_search, fetch_url, get_weather.

These tools are provider-aware - providers with native web capabilities
(like Perplexity) won't have these registered.
"""

import re
import ssl
import urllib.request
import urllib.parse
import urllib.error
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..manager import ToolManager


def get_weather(location: str, format: str = "short") -> str:
    """Get weather forecast for a location using wttr.in.

    Args:
        location: City name, optionally with country
        format: 'short', 'detailed', or 'forecast'

    Returns:
        Weather information
    """
    # Create SSL context that doesn't verify (for corporate proxies)
    ssl_context = ssl.create_default_context()
    ssl_context.check_hostname = False
    ssl_context.verify_mode = ssl.CERT_NONE

    try:
        if format == "short":
            url = f"https://wttr.in/{urllib.parse.quote(location)}?format=4"
        elif format == "detailed":
            url = f"https://wttr.in/{urllib.parse.quote(location)}?0&m"
        else:
            url = f"https://wttr.in/{urllib.parse.quote(location)}?2&m"

        req = urllib.request.Request(
            url,
            headers={"User-Agent": "curl/7.68.0"}
        )

        with urllib.request.urlopen(req, timeout=10, context=ssl_context) as response:
            result = response.read().decode('utf-8')

        # Clean up ANSI codes
        result = re.sub(r'\x1b\[[0-9;]*m', '', result)
        return f"Weather for {location}:\n{result}"

    except urllib.error.HTTPError as e:
        if e.code == 404:
            return f"Error: Location '{location}' not found. Try a different city name or format like 'Geneva,Switzerland'"
        return f"Error fetching weather: HTTP {e.code}"
    except urllib.error.URLError as e:
        return f"Error: Could not connect to weather service. {str(e.reason)}"
    except Exception as e:
        return f"Error getting weather: {str(e)}"


def web_search(query: str, num_results: int = 5) -> str:
    """Search the web using DuckDuckGo.

    Args:
        query: Search query
        num_results: Number of results (default: 5, max: 10)

    Returns:
        Search results
    """
    ssl_context = ssl.create_default_context()
    ssl_context.check_hostname = False
    ssl_context.verify_mode = ssl.CERT_NONE

    try:
        encoded_query = urllib.parse.quote_plus(query)
        url = f"https://html.duckduckgo.com/html/?q={encoded_query}"

        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
            }
        )

        with urllib.request.urlopen(req, timeout=15, context=ssl_context) as response:
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
            return f"No results found for '{query}'"

        return f"Search results for '{query}':\n\n" + "\n".join(results)

    except urllib.error.URLError as e:
        return f"Error: Could not connect to search service. {str(e.reason)}"
    except Exception as e:
        return f"Error searching: {str(e)}"


def fetch_url(url: str, max_length: int = 5000) -> str:
    """Fetch and extract text content from a URL.

    Args:
        url: URL to fetch
        max_length: Maximum characters (default: 5000)

    Returns:
        Page content
    """
    ssl_context = ssl.create_default_context()
    ssl_context.check_hostname = False
    ssl_context.verify_mode = ssl.CERT_NONE

    try:
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
            }
        )

        with urllib.request.urlopen(req, timeout=15, context=ssl_context) as response:
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


def register_tools(manager: 'ToolManager', provider: str = None):
    """Register web tools with the manager.

    These tools are excluded for providers with native capabilities.

    Args:
        manager: ToolManager instance
        provider: Current provider name
    """
    # Providers with native web capabilities don't need these tools
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
