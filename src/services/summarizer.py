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


@dataclass
class TopicSynthesis:
    """Synthesized prose for a topic with inline [N] references."""

    topic_name: str
    prose: str  # paragraphs with [N] source references
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

    return f"""You are writing summaries for a daily email news digest. The reader is interested in: {topic_context}

Summarize the following article in one or two short paragraphs based on whatever information is provided (title, description, source). Focus on the key facts and takeaways. Write in a clear, direct tone as if briefing someone over coffee. Never refuse to summarize — always produce a summary from the available information. Do not comment on the quality of the article, mention missing information, or add any meta-commentary.

Article:
{content}"""


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
                    "You summarize news articles for a daily email digest. "
                    "Be direct and factual. Never comment on the article itself or mention missing details."
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

    async def complete(self, system: str, prompt: str, max_tokens: int) -> str:
        """Raw completion call."""
        response = await self.client.messages.create(
            model=self.model,
            max_tokens=max_tokens,
            messages=[{"role": "user", "content": prompt}],
            system=system,
        )
        return response.content[0].text.strip()


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

    async def complete(self, system: str, prompt: str, max_tokens: int) -> str:
        """Raw completion call."""
        response = await self.client.chat.completions.create(
            model=self.model,
            max_tokens=max_tokens,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": prompt},
            ],
        )
        return (response.choices[0].message.content or "").strip()


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
            if not article.description:
                logger.info(f"Skipping AI for '{article.title}' — no description available")
                results.append(
                    SummaryResult(
                        summary=article.title,
                        provider="Fallback",
                        model="none",
                    )
                )
                continue
            try:
                result = await self.summarize_article(article, topic_name, topic_keywords)
                logger.info(
                    f"AI summary for '{article.title}': {len(result.summary)} chars "
                    f"(provider={result.provider})"
                )
                results.append(result)
            except Exception as e:
                logger.error(
                    f"Failed to summarize article '{article.title}': "
                    f"{type(e).__name__}: {e}"
                )
                fallback_text = article.description or article.title
                logger.warning(
                    f"Using fallback summary for '{article.title}' "
                    f"({len(fallback_text)} chars)"
                )
                results.append(
                    SummaryResult(
                        summary=fallback_text,
                        provider="Fallback",
                        model="none",
                    )
                )
        return results

    async def synthesize_topic(
        self,
        topic_name: str,
        articles: list[Article],
        notable_filings: list[Article] | None = None,
    ) -> TopicSynthesis:
        """
        Synthesize a topic into flowing prose with [N] source references.

        Args:
            topic_name: Name of the topic.
            articles: Articles for this topic (with optional body_text).
            notable_filings: Notable SEC filings to weave into the prose.

        Returns:
            TopicSynthesis with prose containing [N] references.
        """
        provider, model = self.client.get_model_info()

        # Build numbered source list
        source_lines = []
        idx = 1
        for article in articles:
            content = article.body_text or article.description or article.title
            source_lines.append(
                f"[{idx}] {article.title}\n"
                f"    Source: {article.source_name or 'Unknown'}\n"
                f"    Content: {content}"
            )
            idx += 1

        if notable_filings:
            for filing in notable_filings:
                content = filing.description or filing.title
                source_lines.append(
                    f"[{idx}] {filing.title}\n"
                    f"    Source: {filing.source_name or 'SEC EDGAR'}\n"
                    f"    Content: {content}"
                )
                idx += 1

        sources_text = "\n\n".join(source_lines)

        prompt = f"""Here are the sources for the "{topic_name}" section of a daily news brief:

{sources_text}

Write 3-5 paragraphs synthesizing the key developments and news from these sources. Rules:
- Reference sources inline as [1], [2], etc.
- Do NOT summarize each source individually — connect the dots, find themes, and tell a coherent story
- Every factual claim must cite at least one source
- Write in a clear, direct, informative tone — like a well-written newsletter
- If SEC filings are included, weave the notable ones into the narrative naturally
- Do not start with "This week" or "In this week's" — vary your openings"""

        system = (
            "You write sections for a daily news digest email. "
            "Your writing is clear, direct, and informative. "
            "You synthesize multiple sources into coherent narrative prose."
        )

        try:
            prose = await self.client.complete(system, prompt, max_tokens=2000)
            logger.info(
                f"Synthesized topic '{topic_name}': {len(prose)} chars, "
                f"{idx - 1} sources"
            )
            return TopicSynthesis(
                topic_name=topic_name,
                prose=prose,
                provider=provider,
                model=model,
            )
        except Exception as e:
            logger.error(
                f"Failed to synthesize topic '{topic_name}': "
                f"{type(e).__name__}: {e}"
            )
            # Fallback: concatenate titles
            fallback_lines = [f"- {a.title}" for a in articles]
            if notable_filings:
                fallback_lines.extend(f"- {f.title}" for f in notable_filings)
            return TopicSynthesis(
                topic_name=topic_name,
                prose="\n".join(fallback_lines),
                provider="Fallback",
                model="none",
            )

    async def generate_overview(
        self,
        topic_syntheses: list[TopicSynthesis],
    ) -> str | None:
        """
        Generate a witty overview paragraph from topic syntheses.

        Args:
            topic_syntheses: List of TopicSynthesis objects.

        Returns:
            Overview text or None if generation fails.
        """
        summary_parts = []
        for synthesis in topic_syntheses:
            # Use first 500 chars of each synthesis for context
            snippet = synthesis.prose[:500]
            summary_parts.append(f"{synthesis.topic_name}:\n{snippet}")

        context_text = "\n\n".join(summary_parts)

        prompt = f"""Here are summaries of today's news topics:

{context_text}

Write a short, punchy overview paragraph (3-5 sentences) highlighting the most interesting or important stories across all topics. Be witty, dry, and occasionally sarcastic — like a smart friend giving you the morning briefing. Don't use bullet points, just flowing prose. Don't start with "Well" or "So" or "Alright"."""

        system = (
            "You write the opening paragraph for a daily news digest email. "
            "Your tone is humorous, dry, and slightly sarcastic — but always informative. "
            "Keep it concise."
        )

        try:
            overview = await self.client.complete(system, prompt, max_tokens=500)
            logger.info(f"Generated overview: {len(overview)} chars")
            return overview
        except Exception as e:
            logger.error(f"Failed to generate overview: {type(e).__name__}: {e}")
            return None
