"""Article body text scraper using trafilatura."""

import asyncio
import logging

import httpx
import trafilatura

from src.services.news import Article

logger = logging.getLogger(__name__)

MAX_BODY_CHARS = 2000
CONCURRENCY_LIMIT = 10
REQUEST_TIMEOUT = 15.0


class ScraperService:
    """Scrapes article body text for richer AI synthesis."""

    def __init__(self) -> None:
        self.client = httpx.AsyncClient(
            timeout=REQUEST_TIMEOUT,
            follow_redirects=True,
            headers={"User-Agent": "AI-News-Digest/1.0"},
        )
        self._semaphore = asyncio.Semaphore(CONCURRENCY_LIMIT)

    async def close(self) -> None:
        await self.client.aclose()

    async def scrape_articles(self, articles: list[Article]) -> None:
        """Scrape body text for all articles in place. Failures are silent."""
        tasks = [self._scrape_one(article) for article in articles]
        await asyncio.gather(*tasks, return_exceptions=True)
        scraped = sum(1 for a in articles if a.body_text)
        logger.info(f"Scraped {scraped}/{len(articles)} articles successfully")

    async def _scrape_one(self, article: Article) -> None:
        """Scrape a single article. Sets article.body_text on success."""
        if not article.url:
            return

        # Skip SEC EDGAR URLs — structured data, not articles
        if "sec.gov" in article.url:
            return

        async with self._semaphore:
            try:
                response = await self.client.get(article.url)
                response.raise_for_status()
                html = response.text

                text = trafilatura.extract(html)
                if text:
                    article.body_text = text[:MAX_BODY_CHARS]
            except Exception as e:
                logger.debug(f"Scrape failed for {article.url}: {type(e).__name__}: {e}")
