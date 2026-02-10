"""Digest and article models for tracking sent digests."""

import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.core.database import Base


class Digest(Base):
    """Record of a sent digest email."""

    __tablename__ = "digests"

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
    )
    user_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # AI model info
    ai_provider: Mapped[str] = mapped_column(String(50), nullable=False)
    ai_model: Mapped[str] = mapped_column(String(100), nullable=False)

    # Email tracking
    email_sent_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    email_subject: Mapped[str] = mapped_column(String(255), nullable=False)
    email_id: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
        comment="Email service message ID",
    )

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    # Relationships
    user: Mapped["User"] = relationship("User", back_populates="digests")  # noqa: F821
    articles: Mapped[list["DigestArticle"]] = relationship(
        "DigestArticle",
        back_populates="digest",
        cascade="all, delete-orphan",
    )

    def __repr__(self) -> str:
        return f"<Digest {self.id} sent at {self.email_sent_at}>"


class DigestArticle(Base):
    """Individual article included in a digest."""

    __tablename__ = "digest_articles"

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
    )
    digest_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("digests.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    topic_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("topics.id", ondelete="SET NULL"),
        nullable=True,
    )

    # Article info
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    source_url: Mapped[str] = mapped_column(Text, nullable=False)
    source_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    author: Mapped[str | None] = mapped_column(String(255), nullable=True)
    published_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    # Content
    original_description: Mapped[str | None] = mapped_column(Text, nullable=True)
    ai_summary: Mapped[str] = mapped_column(Text, nullable=False)

    # Optional image
    image_url: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Relationships
    digest: Mapped["Digest"] = relationship("Digest", back_populates="articles")

    def __repr__(self) -> str:
        return f"<DigestArticle {self.title[:50]}>"
