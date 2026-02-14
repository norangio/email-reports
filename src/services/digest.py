"""Digest orchestration service."""

import logging
import re
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.core.config import get_settings
from src.models.digest import Digest, DigestArticle
from src.models.topic import Topic
from src.models.user import User
from src.services.email import (
    EmailService,
    RoutineFiling,
    SourceReference,
    TopicBrief,
)
from src.services.news import Article, NewsService
from src.services.scraper import ScraperService
from src.services.sec_filings import SecFilingsService, classify_filings
from src.services.summarizer import SummarizerService, TopicSynthesis

logger = logging.getLogger(__name__)
settings = get_settings()

# CGT topic name — notable SEC filings get woven into this topic's prose
CGT_TOPIC_NAME = "Biotech & Pharma"


def _renumber_and_linkify(
    prose: str,
    local_to_global: dict[int, int],
    sources: list[SourceReference],
) -> str:
    """Replace [N] references with superscript <a> links and wrap paragraphs in <p> tags."""
    # Build lookup from global number to source
    source_by_number = {s.number: s for s in sources}

    def _replace_ref(match: re.Match) -> str:
        local_num = int(match.group(1))
        global_num = local_to_global.get(local_num)
        if global_num is None:
            return match.group(0)  # leave unrecognized refs as-is
        source = source_by_number.get(global_num)
        if source is None:
            return f"<sup>[{global_num}]</sup>"
        return (
            f'<sup><a href="{source.url}" style="color: #0066cc; text-decoration: none;">'
            f"[{global_num}]</a></sup>"
        )

    prose = re.sub(r"\[(\d+)\]", _replace_ref, prose)

    # Wrap paragraphs in styled <p> tags
    paragraphs = [p.strip() for p in prose.split("\n\n") if p.strip()]
    styled_paragraphs = [
        f'<p class="body-text" style="margin: 0 0 12px 0; font-family: Calibri, \'Segoe UI\', Arial, sans-serif; '
        f'font-size: 11pt; color: #333333; line-height: 1.6;">{p}</p>'
        for p in paragraphs
    ]
    return "\n".join(styled_paragraphs)


# Maps form types to concise table descriptions
_FORM_SHORT_DESC: dict[str, str] = {
    "10-K": "Full-year financials & business overview",
    "10-K/A": "Amended annual report",
    "10-Q": "Quarterly financial results",
    "10-Q/A": "Amended quarterly report",
    "S-1": "IPO/offering registration",
    "S-1/A": "Amended registration statement",
}


def _extract_filing_detail(description: str, form_type: str) -> str:
    """Extract a concise, substantive detail string for the filing table."""
    # For 8-K: pull out item descriptions, skip boilerplate codes
    if "8-K" in form_type:
        # Extract "Item X.XX: Description" pairs, keep only the descriptions
        items = re.findall(r"Item \d+\.\d+: ([^;.]+)", description)
        # Filter out noise items
        noise = {"Financial Statements and Exhibits", "Other Events"}
        substantive = [item.strip() for item in items if item.strip() not in noise]
        if substantive:
            return "; ".join(substantive)
        # All items were noise — return generic
        return "Exhibits and other events"

    # For 10-K, 10-Q, S-1 etc. — use short description
    return _FORM_SHORT_DESC.get(form_type, form_type)


class DigestService:
    """
    Orchestrates the digest generation and delivery process.

    Flow: fetch → scrape → classify filings → synthesize → renumber → render → send.
    """

    def __init__(self) -> None:
        self.news_service = NewsService()
        self.summarizer = SummarizerService()
        self.email_service = EmailService()
        self.sec_filings_service = SecFilingsService()
        self.scraper = ScraperService()

    async def close(self) -> None:
        """Clean up resources."""
        await self.news_service.close()
        await self.sec_filings_service.close()
        await self.scraper.close()

    async def generate_and_send_digest(
        self,
        db: AsyncSession,
        user: User,
    ) -> Digest | None:
        """Generate and send a brief-format digest for a single user."""
        # Load user's active topics
        result = await db.execute(
            select(Topic).where(Topic.user_id == user.id, Topic.is_active == True)
        )
        topics = result.scalars().all()

        if not topics:
            logger.info(f"User {user.email} has no active topics, skipping digest")
            return None

        ai_provider, ai_model = self.summarizer.get_model_info()

        # 1. Fetch articles for all topics
        topic_data: dict[str, tuple[Topic, list[Article]]] = {}
        all_articles: list[Article] = []

        for topic in topics:
            try:
                keywords = topic.get_keywords_list()
                exclude = topic.get_exclude_keywords_list()

                articles = await self.news_service.fetch_news_for_topic(
                    keywords=keywords,
                    exclude_keywords=exclude,
                    max_articles=settings.max_articles_per_topic,
                    topic_name=topic.name,
                )

                if articles:
                    topic_data[topic.name] = (topic, articles)
                    all_articles.extend(articles)
                else:
                    logger.info(f"No articles found for topic '{topic.name}'")
            except Exception as e:
                logger.error(f"Error fetching articles for '{topic.name}': {e}")

        if not topic_data:
            logger.warning(f"No articles found for any topic for user {user.email}")
            return None

        # 2. Scrape all articles concurrently
        await self.scraper.scrape_articles(all_articles)

        # 3. Fetch, classify, and scrape SEC filings
        classified = None
        try:
            sec_articles = await self.sec_filings_service.fetch_recent_filings()
            if sec_articles:
                classified = classify_filings(sec_articles)
                logger.info(
                    f"SEC filings: {len(classified.notable)} notable, "
                    f"{len(classified.routine)} routine"
                )
                # Scrape filing content for AI summarization
                all_filings = classified.notable + classified.routine
                await self.sec_filings_service.scrape_filing_content(all_filings)
        except Exception as e:
            logger.error(f"Error fetching SEC filings: {e}")

        # 4. Synthesize each topic (one AI call per topic)
        syntheses: list[TopicSynthesis] = []
        # Map: topic_name → list of (articles + notable_filings) used for that topic
        topic_sources: dict[str, list[Article]] = {}

        for topic_name, (topic, articles) in topic_data.items():
            notable_for_topic = None
            if topic_name == CGT_TOPIC_NAME and classified and classified.notable:
                notable_for_topic = classified.notable

            synthesis = await self.summarizer.synthesize_topic(
                topic_name=topic_name,
                articles=articles,
                notable_filings=notable_for_topic,
            )
            syntheses.append(synthesis)

            # Track sources in order for renumbering
            source_list = list(articles)
            if notable_for_topic:
                source_list.extend(notable_for_topic)
            topic_sources[topic_name] = source_list

        if not syntheses:
            logger.warning(f"No syntheses generated for user {user.email}")
            return None

        # 5. Build global source numbering
        all_sources: list[SourceReference] = []
        # For each topic, map local [N] → global [N]
        topic_local_to_global: dict[str, dict[int, int]] = {}
        global_idx = 1

        for synthesis in syntheses:
            local_map: dict[int, int] = {}
            for local_idx, article in enumerate(topic_sources[synthesis.topic_name], start=1):
                local_map[local_idx] = global_idx
                all_sources.append(
                    SourceReference(
                        number=global_idx,
                        title=article.title,
                        source_name=article.source_name or "Unknown",
                        url=article.url,
                    )
                )
                global_idx += 1
            topic_local_to_global[synthesis.topic_name] = local_map

        # 6. Renumber references and linkify prose
        topic_briefs: list[TopicBrief] = []
        for synthesis in syntheses:
            local_map = topic_local_to_global[synthesis.topic_name]
            prose_html = _renumber_and_linkify(synthesis.prose, local_map, all_sources)
            topic_briefs.append(TopicBrief(name=synthesis.topic_name, prose_html=prose_html))

        # 7. Generate overview from syntheses
        overview = await self.summarizer.generate_overview(syntheses)

        # 8. Build routine filings list with AI summaries
        routine_filings: list[RoutineFiling] = []
        if classified and classified.routine:
            # AI-summarize each filing for substantive detail
            for filing in classified.routine:
                if filing.body_text:
                    ai_detail = await self.summarizer.summarize_filing(filing)
                else:
                    ai_detail = ""

                parts = filing.title.split(" — ", 1)
                company = parts[0] if parts else "Unknown"
                form_info = parts[1].split(":")[0] if len(parts) > 1 else "Unknown"
                date_str = ""
                if filing.published_at:
                    date_str = filing.published_at.strftime("%b %d")
                # Use AI summary if available, fall back to metadata extraction
                detail = ai_detail or _extract_filing_detail(
                    filing.description or "", form_info.strip()
                )
                routine_filings.append(
                    RoutineFiling(
                        company=company,
                        form_type=form_info,
                        date=date_str,
                        url=filing.url,
                        description=detail,
                    )
                )

        # 9. Render email
        email_content = self.email_service.render_brief_email(
            user_name=user.full_name,
            topics=topic_briefs,
            sources=all_sources,
            ai_provider=ai_provider,
            ai_model=ai_model,
            overview=overview,
            routine_filings=routine_filings,
        )

        # 10. Send email
        email_id = await self.email_service.send_digest(
            to_email=user.email,
            email_content=email_content,
        )

        if not email_id:
            logger.error(f"Failed to send digest to {user.email}")
            return None

        # 11. Record in DB
        digest = Digest(
            user_id=user.id,
            ai_provider=ai_provider,
            ai_model=ai_model,
            email_sent_at=datetime.now(timezone.utc),
            email_subject=email_content.subject,
            email_id=email_id,
        )
        db.add(digest)
        await db.flush()

        # Store digest articles — ai_summary holds the full topic synthesis for all articles
        all_digest_articles: list[DigestArticle] = []
        synthesis_by_topic = {s.topic_name: s for s in syntheses}
        for topic_name, (topic, articles) in topic_data.items():
            synthesis_text = synthesis_by_topic.get(topic_name)
            summary_text = synthesis_text.prose if synthesis_text else ""
            for article in articles:
                da = DigestArticle(
                    digest_id=digest.id,
                    topic_id=topic.id,
                    title=article.title,
                    source_url=article.url,
                    source_name=article.source_name,
                    author=article.author,
                    published_at=article.published_at,
                    original_description=article.description,
                    ai_summary=summary_text,
                    image_url=article.image_url,
                )
                db.add(da)
                all_digest_articles.append(da)

        user.last_digest_sent_at = datetime.now(timezone.utc)
        db.add(user)

        await db.commit()

        logger.info(
            f"Digest sent to {user.email}: {len(all_digest_articles)} articles, "
            f"{len(syntheses)} topics synthesized, {len(all_sources)} sources"
        )

        return digest

    async def process_pending_digests(self, db: AsyncSession) -> int:
        """Process all users who are due for a digest."""
        result = await db.execute(
            select(User)
            .options(selectinload(User.topics))
            .where(
                User.is_active == True,
                User.digest_enabled == True,
            )
        )
        users = result.scalars().all()

        digests_sent = 0
        for user in users:
            if self._should_send_digest(user):
                try:
                    digest = await self.generate_and_send_digest(db, user)
                    if digest:
                        digests_sent += 1
                except Exception as e:
                    logger.error(f"Failed to generate digest for {user.email}: {e}")

        return digests_sent

    def _should_send_digest(self, user: User) -> bool:
        """Check if a user should receive a digest now."""
        now = datetime.now(timezone.utc)

        if now.hour != user.digest_hour:
            return False

        if user.last_digest_sent_at:
            last_sent = user.last_digest_sent_at
            days_since = (now - last_sent).days

            if user.digest_frequency == "daily" and days_since < 1:
                return False
            elif user.digest_frequency == "twice_weekly" and days_since < 3:
                return False
            elif user.digest_frequency == "weekly" and days_since < 7:
                return False
            elif user.digest_frequency == "monthly" and days_since < 30:
                return False

        return True
