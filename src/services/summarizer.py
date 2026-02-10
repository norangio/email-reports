"""AI-powered news summarization service."""

import logging
from dataclasses import dataclass

import anthropic
import openai

from src.core.config import AIProvider, get_settings
from src.services.news import Article

logger = logging.getLogger(__name__)
settings = get_settings()


@dataclass
class SummaryResult:
    """Result of AI summarization."""

    summary: str
    provider: str
    model: str


def _build_prompt(article: Article, topic_context: str) -> str:
    """Build the summarization prompt."""
    content_parts = [
        f"Title: {article.title}",
        f"Source: {article.source_name or 'Unknown'}",
    ]

    if article.description:
        content_parts.append(f"Description: {article.description}")

    if article.published_at:
        content_parts.append(f"Published: {article.published_at.strftime('%Y-%m-%d')}")

    content = "\n".join(content_parts)

    return f"""Please summarize this news article in 1-2 detailed paragraphs.
The reader is interested in: {topic_context}

Article:
{content}

Provide a thorough, factual summary that covers the key points, context, and why it matters. Write in a clear, journalistic tone."""


class AnthropicClient:
    """Anthropic Claude client for summarization."""

    def __init__(self) -> None:
        self.client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)
        self.model = settings.anthropic_model

    def get_model_info(self) -> tuple[str, str]:
        return ("Anthropic", self.model)

    async def summarize(self, article: Article, topic_context: str) -> SummaryResult:
        """Summarize an article using Claude."""
        prompt = _build_prompt(article, topic_context)

        try:
            response = await self.client.messages.create(
                model=self.model,
                max_tokens=settings.summary_max_length * 2,
                messages=[{"role": "user", "content": prompt}],
                system=(
                    "You are a professional news summarizer. Create concise, informative "
                    "summaries that capture the key points. Focus on facts and avoid "
                    "sensationalism. Write in a neutral, journalistic tone."
                ),
            )

            summary = response.content[0].text.strip()

            return SummaryResult(
                summary=summary,
                provider="Anthropic",
                model=self.model,
            )

        except anthropic.APIError as e:
            logger.error(f"Anthropic API error: {e}")
            raise


class OpenAIClient:
    """OpenAI GPT client for summarization."""

    def __init__(self) -> None:
        self.client = openai.AsyncOpenAI(api_key=settings.openai_api_key)
        self.model = settings.openai_model

    def get_model_info(self) -> tuple[str, str]:
        return ("OpenAI", self.model)

    async def summarize(self, article: Article, topic_context: str) -> SummaryResult:
        """Summarize an article using GPT."""
        prompt = _build_prompt(article, topic_context)

        try:
            response = await self.client.chat.completions.create(
                model=self.model,
                max_tokens=settings.summary_max_length * 2,
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "You are a professional news summarizer. Create concise, informative "
                            "summaries that capture the key points. Focus on facts and avoid "
                            "sensationalism. Write in a neutral, journalistic tone."
                        ),
                    },
                    {"role": "user", "content": prompt},
                ],
            )

            summary = response.choices[0].message.content or ""
            summary = summary.strip()

            return SummaryResult(
                summary=summary,
                provider="OpenAI",
                model=self.model,
            )

        except openai.APIError as e:
            logger.error(f"OpenAI API error: {e}")
            raise


class SummarizerService:
    """
    Service for summarizing news articles using AI.

    Supports multiple AI providers (Anthropic Claude, OpenAI GPT).
    """

    def __init__(self, provider: AIProvider | None = None) -> None:
        """
        Initialize the summarizer with the specified provider.

        Args:
            provider: AI provider to use. Defaults to settings.ai_provider.
        """
        self.provider = provider or settings.ai_provider
        self.client = self._create_client()

    def _create_client(self) -> AnthropicClient | OpenAIClient:
        """Create the appropriate AI client."""
        if self.provider == AIProvider.ANTHROPIC:
            if not settings.anthropic_api_key:
                raise ValueError("ANTHROPIC_API_KEY is required for Anthropic provider")
            return AnthropicClient()
        elif self.provider == AIProvider.OPENAI:
            if not settings.openai_api_key:
                raise ValueError("OPENAI_API_KEY is required for OpenAI provider")
            return OpenAIClient()
        else:
            raise ValueError(f"Unsupported AI provider: {self.provider}")

    def get_model_info(self) -> tuple[str, str]:
        """Get the current provider and model being used."""
        return self.client.get_model_info()

    async def summarize_article(
        self,
        article: Article,
        topic_name: str,
        topic_keywords: list[str],
    ) -> SummaryResult:
        """
        Summarize a single article.

        Args:
            article: The article to summarize.
            topic_name: Name of the topic this article relates to.
            topic_keywords: Keywords for the topic for context.

        Returns:
            SummaryResult with the summary and model info.
        """
        topic_context = f"{topic_name} ({', '.join(topic_keywords[:5])})"
        return await self.client.summarize(article, topic_context)

    async def summarize_articles(
        self,
        articles: list[Article],
        topic_name: str,
        topic_keywords: list[str],
    ) -> list[SummaryResult]:
        """
        Summarize multiple articles.

        Args:
            articles: List of articles to summarize.
            topic_name: Name of the topic.
            topic_keywords: Keywords for context.

        Returns:
            List of SummaryResult objects.
        """
        results = []
        for article in articles:
            try:
                result = await self.summarize_article(article, topic_name, topic_keywords)
                results.append(result)
            except Exception as e:
                logger.error(f"Failed to summarize article '{article.title}': {e}")
                # Create a fallback summary
                results.append(
                    SummaryResult(
                        summary=article.description or article.title,
                        provider="Fallback",
                        model="none",
                    )
                )
        return results
