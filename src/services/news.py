"""News fetching service using NewsAPI and RSS feeds."""

import asyncio
import logging
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import feedparser
import httpx
from bs4 import BeautifulSoup

from src.core.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()


@dataclass
class Article:
    """Represents a news article."""

    title: str
    url: str
    description: str | None
    source_name: str | None
    author: str | None
    published_at: datetime | None
    image_url: str | None
    body_text: str | None = None  # scraped article content

    def __hash__(self) -> int:
        return hash(self.url)

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Article):
            return False
        return self.url == other.url


class NewsService:
    """Service for fetching news from multiple sources."""

    NEWSAPI_BASE_URL = "https://newsapi.org/v2"

    # Generic RSS feeds as fallback for topics without specific feeds
    RSS_FEEDS = [
        "https://feeds.arstechnica.com/arstechnica/technology-lab",
        "https://www.wired.com/feed/rss",
        "https://rss.nytimes.com/services/xml/rss/nyt/Technology.xml",
        "https://www.sciencedaily.com/rss/all.xml",
        "https://rss.nytimes.com/services/xml/rss/nyt/Science.xml",
        "https://feeds.bloomberg.com/markets/news.rss",
        "https://rss.nytimes.com/services/xml/rss/nyt/Business.xml",
        "https://rss.nytimes.com/services/xml/rss/nyt/Health.xml",
        "https://rss.nytimes.com/services/xml/rss/nyt/HomePage.xml",
        "https://feeds.bbci.co.uk/news/rss.xml",
    ]

    # Topic-specific RSS feeds — used instead of generic feeds when available.
    # Articles from these feeds skip keyword filtering (the feeds ARE the curation).
    TOPIC_RSS_FEEDS: dict[str, list[str]] = {
        "Biotech & Pharma": [
            "https://www.fiercebiotech.com/rss/xml",
            "https://www.fiercepharma.com/rss/xml",
            "https://www.statnews.com/feed/",
            "https://www.genengnews.com/feed/",
        ],
    }

    def __init__(self) -> None:
        self.api_key = settings.newsapi_key
        self.client = httpx.AsyncClient(
            timeout=30.0,
            follow_redirects=True,
            headers={"User-Agent": "AI-News-Digest/1.0"},
        )

    async def close(self) -> None:
        """Close the HTTP client."""
        await self.client.aclose()

    async def fetch_news_for_topic(
        self,
        keywords: list[str],
        exclude_keywords: list[str] | None = None,
        max_articles: int = 10,
        days_back: int = 7,
        topic_name: str | None = None,
    ) -> list[Article]:
        """
        Fetch news articles for given keywords.

        When topic_name has dedicated RSS feeds, those are the primary source
        and NewsAPI supplements. Otherwise NewsAPI is primary with generic RSS
        as fallback.
        """
        articles: list[Article] = []
        has_dedicated_feeds = topic_name and topic_name in self.TOPIC_RSS_FEEDS

        if has_dedicated_feeds:
            # Topic-specific RSS feeds are the primary source
            rss_articles = await self._fetch_from_rss(keywords, max_articles, topic_name)
            articles.extend(rss_articles)

            # Supplement with NewsAPI only if we still need more
            if len(articles) < max_articles and self.api_key:
                remaining = max_articles - len(articles)
                newsapi_articles = await self._fetch_from_newsapi(
                    keywords, exclude_keywords, remaining, days_back
                )
                articles.extend(newsapi_articles)
        else:
            # Generic topics: NewsAPI first, generic RSS as fallback
            if self.api_key:
                newsapi_articles = await self._fetch_from_newsapi(
                    keywords, exclude_keywords, max_articles, days_back
                )
                articles.extend(newsapi_articles)

            if len(articles) < max_articles:
                remaining = max_articles - len(articles)
                rss_articles = await self._fetch_from_rss(keywords, remaining, topic_name)
                articles.extend(rss_articles)

        # Deduplicate by URL
        seen_urls: set[str] = set()
        unique_articles: list[Article] = []
        for article in articles:
            if article.url not in seen_urls:
                seen_urls.add(article.url)
                unique_articles.append(article)

        return unique_articles[:max_articles]

    async def _fetch_from_newsapi(
        self,
        keywords: list[str],
        exclude_keywords: list[str] | None,
        max_articles: int,
        days_back: int,
    ) -> list[Article]:
        """Fetch articles from NewsAPI, then post-filter by keywords."""
        articles: list[Article] = []

        # Quote multi-word keywords so NewsAPI treats them as phrases
        quoted = []
        for kw in keywords:
            if " " in kw:
                quoted.append(f'"{kw}"')
            else:
                quoted.append(kw)
        query = " OR ".join(quoted)
        if exclude_keywords:
            exclude_query = " ".join(f"-{kw}" for kw in exclude_keywords)
            query = f"({query}) {exclude_query}"

        from_date = (datetime.now(timezone.utc) - timedelta(days=days_back)).strftime("%Y-%m-%d")

        # Request more than needed since we'll post-filter
        fetch_size = min(max_articles * 3, 50)

        try:
            response = await self.client.get(
                f"{self.NEWSAPI_BASE_URL}/everything",
                params={
                    "q": query,
                    "from": from_date,
                    "sortBy": "relevancy",
                    "pageSize": fetch_size,
                    "language": "en",
                    "apiKey": self.api_key,
                },
            )
            response.raise_for_status()
            data = response.json()

            for item in data.get("articles", []):
                published_at = None
                if item.get("publishedAt"):
                    try:
                        published_at = datetime.fromisoformat(
                            item["publishedAt"].replace("Z", "+00:00")
                        )
                    except ValueError:
                        pass

                articles.append(
                    Article(
                        title=item.get("title", "Untitled"),
                        url=item.get("url", ""),
                        description=item.get("description"),
                        source_name=item.get("source", {}).get("name"),
                        author=item.get("author"),
                        published_at=published_at,
                        image_url=item.get("urlToImage"),
                    )
                )

        except httpx.HTTPError as e:
            logger.warning(f"NewsAPI request failed: {e}")
        except Exception as e:
            logger.error(f"Error fetching from NewsAPI: {e}")

        # Post-filter: require at least one keyword match (word-boundary)
        return self._filter_by_keywords(articles, keywords)[:max_articles]

    async def _fetch_from_rss(
        self,
        keywords: list[str],
        max_articles: int,
        topic_name: str | None = None,
    ) -> list[Article]:
        """Fetch articles from RSS feeds."""
        articles: list[Article] = []
        is_topic_specific = topic_name and topic_name in self.TOPIC_RSS_FEEDS

        # Use topic-specific feeds if available, otherwise generic
        feeds = self.TOPIC_RSS_FEEDS.get(topic_name, self.RSS_FEEDS[:5]) if topic_name else self.RSS_FEEDS[:5]
        tasks = [self._parse_rss_feed(url) for url in feeds]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        for result in results:
            if isinstance(result, list):
                articles.extend(result)

        if is_topic_specific:
            # Topic-specific feeds are already curated — skip keyword filtering
            return articles[:max_articles]

        # Generic feeds: filter by keywords using word-boundary matching
        return self._filter_by_keywords(articles, keywords)[:max_articles]

    def _filter_by_keywords(
        self, articles: list[Article], keywords: list[str]
    ) -> list[Article]:
        """Filter articles requiring at least one keyword match (word-boundary)."""
        keyword_patterns = [
            re.compile(r"\b" + re.escape(kw.lower()) + r"\b")
            for kw in keywords
        ]
        filtered = []
        for article in articles:
            text = f"{article.title} {article.description or ''}".lower()
            if any(pat.search(text) for pat in keyword_patterns):
                filtered.append(article)
        return filtered

    async def _parse_rss_feed(self, feed_url: str) -> list[Article]:
        """Parse an RSS feed and return articles."""
        articles: list[Article] = []

        try:
            response = await self.client.get(feed_url)
            response.raise_for_status()

            feed = feedparser.parse(response.text)

            for entry in feed.entries[:10]:
                published_at = None
                if hasattr(entry, "published_parsed") and entry.published_parsed:
                    try:
                        published_at = datetime(*entry.published_parsed[:6])
                    except (TypeError, ValueError):
                        pass

                # Extract image from media content or enclosure
                image_url = None
                if hasattr(entry, "media_content"):
                    for media in entry.media_content:
                        if media.get("type", "").startswith("image"):
                            image_url = media.get("url")
                            break
                elif hasattr(entry, "enclosures"):
                    for enc in entry.enclosures:
                        if enc.get("type", "").startswith("image"):
                            image_url = enc.get("href")
                            break

                articles.append(
                    Article(
                        title=self._clean_html(entry.get("title", "Untitled")),
                        url=entry.get("link", ""),
                        description=self._clean_html(entry.get("summary", "")),
                        source_name=feed.feed.get("title"),
                        author=entry.get("author"),
                        published_at=published_at,
                        image_url=image_url,
                    )
                )

        except Exception as e:
            logger.warning(f"Failed to parse RSS feed {feed_url}: {e}")

        return articles

    def _clean_html(self, html: str) -> str:
        """Remove HTML tags from text."""
        if not html:
            return ""
        soup = BeautifulSoup(html, "html.parser")
        return soup.get_text(separator=" ", strip=True)

