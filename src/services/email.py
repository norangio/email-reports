"""Email service using Resend."""

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import resend
from jinja2 import Environment, FileSystemLoader, select_autoescape

from src.core.config import get_settings
from src.services.news import Article
from src.services.summarizer import SummaryResult

logger = logging.getLogger(__name__)
settings = get_settings()

# Setup Jinja2 template environment
TEMPLATE_DIR = Path(__file__).parent.parent / "templates"
jinja_env = Environment(
    loader=FileSystemLoader(TEMPLATE_DIR),
    autoescape=select_autoescape(["html", "xml"]),
)


@dataclass
class TopicArticles:
    """A topic name paired with its articles and summaries for rendering."""

    name: str
    items: list[tuple[Article, SummaryResult]]


@dataclass
class TopicBrief:
    """A topic with synthesized prose for the brief format."""

    name: str
    prose_html: str  # paragraphs with superscript <a> links


@dataclass
class SourceReference:
    """A numbered source in the reference list."""

    number: int
    title: str
    source_name: str
    url: str


@dataclass
class RoutineFiling:
    """A routine SEC filing for the compact table."""

    company: str
    form_type: str
    date: str
    url: str
    description: str


@dataclass
class EmailContent:
    """Complete email content."""

    subject: str
    html_body: str
    text_body: str


class EmailService:
    """Service for sending digest emails via Resend."""

    def __init__(self) -> None:
        resend.api_key = settings.resend_api_key
        self.from_email = settings.email_from_address
        self.from_name = settings.email_from_name

    def render_digest_email(
        self,
        user_name: str | None,
        topics: list[TopicArticles],
        ai_provider: str,
        ai_model: str,
        digest_date: datetime | None = None,
        overview: str | None = None,
    ) -> EmailContent:
        """
        Render the digest email using the HTML template.

        Args:
            user_name: User's name for greeting.
            topics: List of TopicArticles with article/summary pairs.
            ai_provider: Name of the AI provider used.
            ai_model: Name of the AI model used.
            digest_date: Date of the digest (defaults to now).

        Returns:
            EmailContent with subject and rendered bodies.
        """
        if digest_date is None:
            digest_date = datetime.now(timezone.utc)

        # Build template-friendly structure
        template_topics = []
        total_articles = 0
        for topic in topics:
            articles = [
                {
                    "title": article.title,
                    "url": article.url,
                    "source_name": article.source_name or "Unknown",
                    "summary": summary.summary,
                    "image_url": article.image_url,
                    "published_at": article.published_at,
                }
                for article, summary in topic.items
            ]
            total_articles += len(articles)
            template_topics.append({"name": topic.name, "articles": articles})

        template_vars = {
            "user_name": user_name or "there",
            "topics": template_topics,
            "ai_provider": ai_provider,
            "ai_model": ai_model,
            "digest_date": digest_date,
            "total_articles": total_articles,
            "app_name": settings.app_name,
            "overview": overview,
        }

        # Render HTML template
        template = jinja_env.get_template("digest_email.html")
        html_body = template.render(**template_vars)

        # Render plain text template
        text_template = jinja_env.get_template("digest_email.txt")
        text_body = text_template.render(**template_vars)

        # Create subject
        subject = f"Morning Brief — {digest_date.strftime('%b %d, %Y')}"

        return EmailContent(
            subject=subject,
            html_body=html_body,
            text_body=text_body,
        )

    def render_brief_email(
        self,
        user_name: str | None,
        topics: list[TopicBrief],
        sources: list[SourceReference],
        ai_provider: str,
        ai_model: str,
        digest_date: datetime | None = None,
        overview: str | None = None,
        routine_filings: list[RoutineFiling] | None = None,
    ) -> EmailContent:
        """Render the brief-format digest email."""
        if digest_date is None:
            digest_date = datetime.now(timezone.utc)

        template_vars = {
            "user_name": user_name or "there",
            "topics": topics,
            "sources": sources,
            "routine_filings": routine_filings or [],
            "ai_provider": ai_provider,
            "ai_model": ai_model,
            "digest_date": digest_date,
            "overview": overview,
            "app_name": settings.app_name,
        }

        html_template = jinja_env.get_template("brief_email.html")
        html_body = html_template.render(**template_vars)

        text_template = jinja_env.get_template("brief_email.txt")
        text_body = text_template.render(**template_vars)

        subject = f"Morning Brief — {digest_date.strftime('%b %d, %Y')}"

        return EmailContent(subject=subject, html_body=html_body, text_body=text_body)

    async def send_digest(
        self,
        to_email: str,
        email_content: EmailContent,
    ) -> str | None:
        """
        Send the digest email.

        Args:
            to_email: Recipient email address.
            email_content: Rendered email content.

        Returns:
            Email ID if successful, None otherwise.
        """
        try:
            response = resend.Emails.send(
                {
                    "from": f"{self.from_name} <{self.from_email}>",
                    "to": [to_email],
                    "subject": email_content.subject,
                    "html": email_content.html_body,
                    "text": email_content.text_body,
                }
            )

            email_id = response.get("id")
            logger.info(f"Digest email sent to {to_email}, ID: {email_id}")
            return email_id

        except Exception as e:
            logger.error(f"Failed to send email to {to_email}: {e}")
            return None

    async def send_welcome_email(self, to_email: str, user_name: str | None) -> str | None:
        """Send a welcome email to new users."""
        try:
            template = jinja_env.get_template("welcome_email.html")
            html_body = template.render(
                user_name=user_name or "there",
                app_name=settings.app_name,
            )

            response = resend.Emails.send(
                {
                    "from": f"{self.from_name} <{self.from_email}>",
                    "to": [to_email],
                    "subject": f"Welcome to {settings.app_name}!",
                    "html": html_body,
                }
            )

            return response.get("id")

        except Exception as e:
            logger.error(f"Failed to send welcome email to {to_email}: {e}")
            return None
