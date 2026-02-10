"""Topic model for user interests."""

import uuid
from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.core.database import Base


class Topic(Base):
    """User-defined topic of interest for news tracking."""

    __tablename__ = "topics"

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
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Search configuration
    keywords: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        comment="Comma-separated keywords for news search",
    )
    exclude_keywords: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        comment="Comma-separated keywords to exclude",
    )

    # Priority and status
    priority: Mapped[int] = mapped_column(Integer, default=1, comment="1-5, higher is more important")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    # Relationships
    user: Mapped["User"] = relationship("User", back_populates="topics")  # noqa: F821

    def get_keywords_list(self) -> list[str]:
        """Get keywords as a list."""
        return [k.strip() for k in self.keywords.split(",") if k.strip()]

    def get_exclude_keywords_list(self) -> list[str]:
        """Get exclude keywords as a list."""
        if not self.exclude_keywords:
            return []
        return [k.strip() for k in self.exclude_keywords.split(",") if k.strip()]

    def __repr__(self) -> str:
        return f"<Topic {self.name}>"
