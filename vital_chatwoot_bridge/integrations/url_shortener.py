"""
URL shortener client for replacing URLs in outbound SMS messages.

Supports Short.io as the provider. Follows the same pattern as MailgunClient
and other integration clients.
"""

import logging
import re
from typing import Dict, Optional

import httpx

from vital_chatwoot_bridge.core.config import URLShortenerConfig

logger = logging.getLogger(__name__)

# Regex to find URLs in text — matches http(s) URLs
_URL_PATTERN = re.compile(
    r'https?://[^\s<>\"\')]+',
    re.IGNORECASE,
)


class URLShortenerError(Exception):
    """Exception raised for URL shortener API errors."""

    def __init__(self, message: str, status_code: Optional[int] = None):
        super().__init__(message)
        self.status_code = status_code


class URLShortenerClient:
    """Client for URL shortening services."""

    def __init__(self, config: URLShortenerConfig):
        self.config = config
        self.client = httpx.AsyncClient(timeout=10.0)

    async def close(self):
        await self.client.aclose()

    async def shorten(self, long_url: str) -> str:
        """Shorten a single URL via the configured provider.

        Returns the short URL on success, or the original URL on failure
        (graceful degradation).
        """
        if not self.config.enabled:
            return long_url

        # Skip if already shortened with our domain
        if self.config.domain in long_url:
            return long_url

        try:
            if self.config.provider == "short_io":
                return await self._shorten_short_io(long_url)
            else:
                logger.warning(f"🔗 URL_SHORTENER: Unknown provider '{self.config.provider}', skipping")
                return long_url
        except Exception as e:
            logger.error(f"🔗 URL_SHORTENER: Failed to shorten {long_url}: {e}")
            return long_url

    async def _shorten_short_io(self, long_url: str) -> str:
        """Shorten a URL via Short.io API."""
        response = await self.client.post(
            "https://api.short.io/links",
            json={"domain": self.config.domain, "originalURL": long_url},
            headers={
                "Authorization": self.config.api_key,
                "Content-Type": "application/json",
            },
        )
        if response.status_code != 200:
            body = response.text[:200]
            raise URLShortenerError(
                f"Short.io API error: HTTP {response.status_code}: {body}",
                status_code=response.status_code,
            )
        data = response.json()
        short_url = data.get("shortURL")
        if not short_url:
            raise URLShortenerError(f"Short.io response missing shortURL: {data}")
        logger.info(f"🔗 URL_SHORTENER: {long_url} → {short_url}")
        return short_url

    async def shorten_urls_in_text(self, text: str) -> str:
        """Find all URLs in text and replace with shortened versions.

        Deduplicates URLs so each unique URL is shortened only once.
        Returns the text with all URLs replaced.
        """
        if not self.config.enabled:
            return text

        urls = _URL_PATTERN.findall(text)
        if not urls:
            return text

        # Deduplicate while preserving order
        unique_urls = list(dict.fromkeys(urls))

        # Shorten each unique URL
        url_map: Dict[str, str] = {}
        for url in unique_urls:
            short = await self.shorten(url)
            if short != url:
                url_map[url] = short

        if not url_map:
            return text

        # Replace all occurrences (longest URLs first to avoid partial matches)
        result = text
        for long_url in sorted(url_map.keys(), key=len, reverse=True):
            result = result.replace(long_url, url_map[long_url])

        logger.info(
            f"🔗 URL_SHORTENER: Replaced {len(url_map)} URL(s) in message "
            f"({len(text)} → {len(result)} chars)"
        )
        return result


# ---------------------------------------------------------------------------
# Module-level singleton accessor
# ---------------------------------------------------------------------------

_client: Optional[URLShortenerClient] = None


def get_shortener() -> Optional[URLShortenerClient]:
    """Get or create the module-level URL shortener client.

    Returns None if URL shortening is not configured.
    """
    global _client
    if _client is not None:
        return _client

    from vital_chatwoot_bridge.core.config import get_settings
    settings = get_settings()
    if not settings.url_shortener:
        return None

    _client = URLShortenerClient(settings.url_shortener)
    return _client
