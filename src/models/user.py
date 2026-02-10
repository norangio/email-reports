"""User model for authentication and preferences."""

import uuid
from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.core.config import DigestFrequency
from src.core.database import Base


class User(Base):
    """User account with digest preferences."""

    __tablename__ = "users"

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
    )
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)
    full_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    # Digest preferences
    digest_frequency: Mapped[str] = mapped_column(
        String(20),
        default=DigestFrequency.DAILY.value,
    )
    digest_hour: Mapped[int] = mapped_column(Integer, default=8)
    digest_minute: Mapped[int] = mapped_column(Integer, default=0)
    timezone: Mapped[str] = mapped_column(String(50), default="UTC")
    digest_enabled: Mapped[bool] = mapped_column(Boolean, default=True)

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
    last_digest_sent_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    # Relationships
    topics: Mapped[list["Topic"]] = relationship(  # noqa: F821
        "Topic",
        back_populates="user",
        cascade="all, delete-orphan",
    )
    digests: Mapped[list["Digest"]] = relationship(  # noqa: F821
        "Digest",
        back_populates="user",
        cascade="all, delete-orphan",
    )

    def __repr__(self) -> str:
        return f"<User {self.email}>"
