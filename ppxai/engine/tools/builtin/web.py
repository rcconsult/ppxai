"""
Web tools: web_search, fetch_url, get_weather.

These tools are provider-aware - providers with native web capabilities
(like Perplexity) won't have these registered.
"""

import json
import re
import ssl
import urllib.error
import urllib.parse
import urllib.request

from ....config import get_tool_config
from ....config.tls import tls_ssl_context
from ...types import ToolManagerProtocol


def _create_ssl_context() -> ssl.SSLContext:
    """SSL context for the built-in web tools.

    Delegates to the shared resolver so these tools and the provider
    clients cannot disagree about TLS policy (they used to: this site
    checked that SSL_CERT_FILE existed, the provider sites did not).
    """
    return tls_ssl_context()


def _get_web_timeout(tool_name: str, default: int = 15) -> int:
    """Get timeout for a web tool from config.

    Reads from tools.<tool_name>.timeout in ppxai-config.json.
    """
    try:
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

    # HTTPS-only (v1.19.1, ADR 0009 §2 — the Item 52 scheme-poison fix).
    # The old https→plain-http fallback put an always-denied scheme into
    # get_weather's egress superset, making the tool un-allowlistable under
    # the per-run NetworkPolicy (all-or-nothing rule). Reliability fallback
    # is Open-Meteo in the tool chain (get_weather_openmeteo), not a scheme
    # downgrade — a stalled corporate-proxy HTTPS handshake lands there too.
    try:
        url = f"https://wttr.in/{path}"
        ctx = _create_ssl_context()
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
        return f"Error fetching weather: HTTP {e.code}"
    except (urllib.error.URLError, ssl.SSLError, OSError) as e:
        return f"Error: Could not connect to weather service. {str(getattr(e, 'reason', e))}"
    except Exception as e:
        return f"Error getting weather: {str(e)}"


# WMO weather-interpretation codes (Open-Meteo `weather_code`) → (label, emoji).
# Open-Meteo returns a structured numeric code, not human text, so map it here.
_WMO_CODES = {
    0: ("Clear sky", "☀️"),
    1: ("Mainly clear", "🌤️"),
    2: ("Partly cloudy", "⛅"),
    3: ("Overcast", "☁️"),
    45: ("Fog", "🌫️"),
    48: ("Depositing rime fog", "🌫️"),
    51: ("Light drizzle", "🌦️"),
    53: ("Moderate drizzle", "🌦️"),
    55: ("Dense drizzle", "🌦️"),
    56: ("Light freezing drizzle", "🌧️"),
    57: ("Dense freezing drizzle", "🌧️"),
    61: ("Slight rain", "🌧️"),
    63: ("Moderate rain", "🌧️"),
    65: ("Heavy rain", "🌧️"),
    66: ("Light freezing rain", "🌧️"),
    67: ("Heavy freezing rain", "🌧️"),
    71: ("Slight snow", "🌨️"),
    73: ("Moderate snow", "🌨️"),
    75: ("Heavy snow", "❄️"),
    77: ("Snow grains", "🌨️"),
    80: ("Slight rain showers", "🌦️"),
    81: ("Moderate rain showers", "🌦️"),
    82: ("Violent rain showers", "⛈️"),
    85: ("Slight snow showers", "🌨️"),
    86: ("Heavy snow showers", "❄️"),
    95: ("Thunderstorm", "⛈️"),
    96: ("Thunderstorm with slight hail", "⛈️"),
    99: ("Thunderstorm with heavy hail", "⛈️"),
}


def _openmeteo_get(base: str, params: dict, timeout: int) -> dict:
    """GET an Open-Meteo JSON endpoint (respects SSL_VERIFY/SSL_CERT_FILE)."""
    url = base + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"User-Agent": "ppxai-weather/1.0"})
    with urllib.request.urlopen(
        req, timeout=timeout, context=_create_ssl_context()
    ) as response:
        return json.loads(response.read().decode("utf-8"))


def _format_openmeteo(label: str, data: dict, format: str) -> str:
    """Render an Open-Meteo forecast payload into human-readable text."""
    cur = data.get("current", {})
    try:
        code = int(cur.get("weather_code", -1))
    except (TypeError, ValueError):
        code = -1
    cond, emoji = _WMO_CODES.get(code, ("Unknown conditions", ""))
    temp = cur.get("temperature_2m")
    feels = cur.get("apparent_temperature")
    hum = cur.get("relative_humidity_2m")
    wind = cur.get("wind_speed_10m")

    lines = [f"Weather for {label} (via open-meteo):"]
    head = f"{emoji} {cond}".strip()
    if temp is not None:
        head += f", {temp}°C"
        if feels is not None:
            head += f" (feels {feels}°C)"
    lines.append(head)
    detail = []
    if hum is not None:
        detail.append(f"humidity {hum}%")
    if wind is not None:
        detail.append(f"wind {wind} km/h")
    if detail:
        lines.append(", ".join(detail))

    if format == "forecast":
        daily = data.get("daily", {})
        days = daily.get("time", []) or []
        codes = daily.get("weather_code", []) or []
        tmax = daily.get("temperature_2m_max", []) or []
        tmin = daily.get("temperature_2m_min", []) or []
        pops = daily.get("precipitation_probability_max", []) or []
        for i, day in enumerate(days):
            try:
                dcode = int(codes[i])
            except (IndexError, TypeError, ValueError):
                dcode = -1
            dcond, demoji = _WMO_CODES.get(dcode, ("Unknown", ""))
            lo = tmin[i] if i < len(tmin) else None
            hi = tmax[i] if i < len(tmax) else None
            pop = pops[i] if i < len(pops) else None
            pop_s = f", precip {pop}%" if pop is not None else ""
            lines.append(f"  {day}: {demoji} {dcond}, {lo}–{hi}°C{pop_s}".strip())

    return "\n".join(lines)


def get_weather_openmeteo(location: str, format: str = "short") -> str:
    """Weather via Open-Meteo — a reliable, key-free fallback for flaky wttr.in.

    wttr.in is a community single-server service that intermittently goes down;
    Open-Meteo is a professional-grade free API (no key) with accurate data and
    global coverage, so it's the right tier to try before resorting to a general
    web-search backend (which scrapes arbitrary pages and returns unreliable
    temperatures). Two calls: geocode the name → lat/lon, then the forecast API.

    Returns a human-readable string, or an 'Error: ...' string on failure (never
    raises), so callers can chain fallbacks uniformly with `get_weather`.
    """
    timeout = _get_web_timeout("get_weather", default=15)
    try:
        geo = _openmeteo_get(
            "https://geocoding-api.open-meteo.com/v1/search",
            {"name": location, "count": 1, "language": "en", "format": "json"},
            timeout,
        )
        results = geo.get("results") or []
        if not results:
            return (
                f"Error: Location '{location}' not found via open-meteo. "
                f"Try a different city name."
            )
        loc = results[0]
        lat, lon = loc.get("latitude"), loc.get("longitude")
        label = ", ".join(
            x for x in (loc.get("name"), loc.get("admin1"), loc.get("country")) if x
        ) or location

        params = {
            "latitude": lat,
            "longitude": lon,
            "current": (
                "temperature_2m,apparent_temperature,relative_humidity_2m,"
                "weather_code,wind_speed_10m"
            ),
            "wind_speed_unit": "kmh",
            "timezone": "auto",
        }
        if format == "forecast":
            params["daily"] = (
                "weather_code,temperature_2m_max,temperature_2m_min,"
                "precipitation_probability_max"
            )
            params["forecast_days"] = 3
        data = _openmeteo_get(
            "https://api.open-meteo.com/v1/forecast", params, timeout
        )
        return _format_openmeteo(label, data, format)
    except urllib.error.HTTPError as e:
        return f"Error fetching weather (open-meteo): HTTP {e.code}"
    except (urllib.error.URLError, ssl.SSLError, OSError) as e:
        return (
            f"Error: Could not connect to open-meteo. "
            f"{str(getattr(e, 'reason', e))}"
        )
    except Exception as e:
        return f"Error getting weather (open-meteo): {str(e)}"


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

    except Exception:
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
