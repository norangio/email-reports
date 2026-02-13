"""Digest orchestration service."""

import logging
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.core.config import get_settings
from src.models.digest import Digest, DigestArticle
from src.models.topic import Topic
from src.models.user import User
from src.services.email import EmailService, TopicArticles
from src.services.news import NewsService
from src.services.sec_filings import SecFilingsService
from src.services.summarizer import SummarizerService

logger = logging.getLogger(__name__)
settings = get_settings()


class DigestService:
    """
    Orchestrates the digest generation and delivery process.

    This service:
    1. Fetches news for each user's topics
    2. Summarizes articles using AI
    3. Composes and sends the digest email
    4. Records the digest in the database
    """

    def __init__(self) -> None:
        self.news_service = NewsService()
        self.summarizer = SummarizerService()
        self.email_service = EmailService()
        self.sec_filings_service = SecFilingsService()

    async def close(self) -> None:
        """Clean up resources."""
        await self.news_service.close()
        await self.sec_filings_service.close()

    async def generate_and_send_digest(
        self,
        db: AsyncSession,
        user: User,
    ) -> Digest | None:
        """
        Generate and send a digest for a single user.

        Args:
            db: Database session.
            user: User to generate digest for.

        Returns:
            Digest record if successful, None otherwise.
        """
        # Load user's active topics
        result = await db.execute(
            select(Topic).where(Topic.user_id == user.id, Topic.is_active == True)
        )
        topics = result.scalars().all()

        if not topics:
            logger.info(f"User {user.email} has no active topics, skipping digest")
            return None

        # Get AI model info
        ai_provider, ai_model = self.summarizer.get_model_info()

        # Process each topic
        topic_articles_list: list[TopicArticles] = []
        all_digest_articles: list[tuple[Topic, DigestArticle]] = []

        for topic in topics:
            try:
                # Fetch news for topic
                keywords = topic.get_keywords_list()
                exclude = topic.get_exclude_keywords_list()

                articles = await self.news_service.fetch_news_for_topic(
                    keywords=keywords,
                    exclude_keywords=exclude,
                    max_articles=settings.max_articles_per_topic,
                    topic_name=topic.name,
                )

                if not articles:
                    logger.info(f"No articles found for topic '{topic.name}'")
                    continue

                # Summarize articles
                summaries = await self.summarizer.summarize_articles(
                    articles=articles,
                    topic_name=topic.name,
                    topic_keywords=keywords,
                )

                # Build pairs for email and DB records
                pairs: list[tuple] = []
                for article, summary in zip(articles, summaries):
                    pairs.append((article, summary))

                    digest_article = DigestArticle(
                        topic_id=topic.id,
                        title=article.title,
                        source_url=article.url,
                        source_name=article.source_name,
                        author=article.author,
                        published_at=article.published_at,
                        original_description=article.description,
                        ai_summary=summary.summary,
                        image_url=article.image_url,
                    )
                    all_digest_articles.append((topic, digest_article))

                if pairs:
                    topic_articles_list.append(
                        TopicArticles(name=topic.name, items=pairs)
                    )

            except Exception as e:
                logger.error(f"Error processing topic '{topic.name}': {e}")
                continue

        # Fetch SEC filings as a separate section
        try:
            sec_articles = await self.sec_filings_service.fetch_recent_filings()
            if sec_articles:
                sec_summaries = await self.summarizer.summarize_articles(
                    articles=sec_articles,
                    topic_name="SEC Filings",
                    topic_keywords=["SEC", "filing", "8-K", "10-Q", "10-K", "S-1"],
                )
                sec_pairs: list[tuple] = []
                for article, summary in zip(sec_articles, sec_summaries):
                    sec_pairs.append((article, summary))
                if sec_pairs:
                    topic_articles_list.append(
                        TopicArticles(name="SEC Filings", items=sec_pairs)
                    )
                    logger.info(f"Added {len(sec_pairs)} SEC filings to digest")
        except Exception as e:
            logger.error(f"Error fetching SEC filings: {e}")

        if not topic_articles_list:
            logger.warning(f"No content generated for user {user.email}")
            return None

        # Generate witty overview from headlines
        topic_headlines = [
            (ta.name, [a.title for a, _ in ta.items])
            for ta in topic_articles_list
        ]
        overview = await self.summarizer.generate_overview(topic_headlines)

        # Render and send email
        email_content = self.email_service.render_digest_email(
            user_name=user.full_name,
            topics=topic_articles_list,
            ai_provider=ai_provider,
            ai_model=ai_model,
            overview=overview,
        )

        email_id = await self.email_service.send_digest(
            to_email=user.email,
            email_content=email_content,
        )

        if not email_id:
            logger.error(f"Failed to send digest to {user.email}")
            return None

        # Create digest record
        digest = Digest(
            user_id=user.id,
            ai_provider=ai_provider,
            ai_model=ai_model,
            email_sent_at=datetime.now(timezone.utc),
            email_subject=email_content.subject,
            email_id=email_id,
        )
        db.add(digest)
        await db.flush()  # Get the digest ID

        # Associate articles with digest
        for _, article in all_digest_articles:
            article.digest_id = digest.id
            db.add(article)

        # Update user's last digest time
        user.last_digest_sent_at = datetime.now(timezone.utc)
        db.add(user)

        await db.commit()

        logger.info(
            f"Digest sent to {user.email}: {len(all_digest_articles)} articles, "
            f"{len(topic_articles_list)} topics"
        )

        return digest

    async def process_pending_digests(self, db: AsyncSession) -> int:
        """
        Process all users who are due for a digest.

        This should be called by the scheduler.

        Args:
            db: Database session.

        Returns:
            Number of digests sent.
        """
        # Find users who need digests
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

        # Check if it's the right time
        if now.hour != user.digest_hour:
            return False

        # Check frequency
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
