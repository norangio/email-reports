"""Email service using Resend."""

import logging
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import resend
from jinja2 import Environment, FileSystemLoader, select_autoescape

from src.core.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

# Setup Jinja2 template environment
TEMPLATE_DIR = Path(__file__).parent.parent / "templates"
jinja_env = Environment(
    loader=FileSystemLoader(TEMPLATE_DIR),
    autoescape=select_autoescape(["html", "xml"]),
)


@dataclass
class ArticleSummary:
    """Article data for email template."""

    title: str
    url: str
    source_name: str
    summary: str
    image_url: str | None = None
    published_at: datetime | None = None


@dataclass
class TopicDigest:
    """Topic data for email template."""

    name: str
    articles: list[ArticleSummary]


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
        topics: list[TopicDigest],
        ai_provider: str,
        ai_model: str,
        digest_date: datetime | None = None,
    ) -> EmailContent:
        """
        Render the digest email using the HTML template.

        Args:
            user_name: User's name for greeting.
            topics: List of topics with their article summaries.
            ai_provider: Name of the AI provider used.
            ai_model: Name of the AI model used.
            digest_date: Date of the digest (defaults to now).

        Returns:
            EmailContent with subject and rendered bodies.
        """
        if digest_date is None:
            digest_date = datetime.utcnow()

        # Calculate total articles
        total_articles = sum(len(t.articles) for t in topics)

        # Render HTML template
        template = jinja_env.get_template("digest_email.html")
        html_body = template.render(
            user_name=user_name or "there",
            topics=topics,
            ai_provider=ai_provider,
            ai_model=ai_model,
            digest_date=digest_date,
            total_articles=total_articles,
            app_name=settings.app_name,
        )

        # Render plain text template
        text_template = jinja_env.get_template("digest_email.txt")
        text_body = text_template.render(
            user_name=user_name or "there",
            topics=topics,
            ai_provider=ai_provider,
            ai_model=ai_model,
            digest_date=digest_date,
            total_articles=total_articles,
            app_name=settings.app_name,
        )

        # Create subject
        topic_names = [t.name for t in topics[:3]]
        subject = f"Your News Digest: {', '.join(topic_names)}"
        if len(topics) > 3:
            subject += f" +{len(topics) - 3} more"

        return EmailContent(
            subject=subject,
            html_body=html_body,
            text_body=text_body,
        )

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
