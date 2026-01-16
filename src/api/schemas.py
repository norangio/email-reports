"""Pydantic schemas for API requests and responses."""

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, EmailStr, Field


# Enums
class DigestFrequency(str, Enum):
    DAILY = "daily"
    WEEKLY = "weekly"
    TWICE_WEEKLY = "twice_weekly"
    MONTHLY = "monthly"


# Auth schemas
class UserCreate(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=100)
    full_name: str | None = Field(None, max_length=255)


class UserLogin(BaseModel):
    email: EmailStr
    password: str


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"


class UserResponse(BaseModel):
    id: str
    email: str
    full_name: str | None
    is_active: bool
    is_verified: bool
    digest_frequency: str
    digest_hour: int
    digest_minute: int
    timezone: str
    digest_enabled: bool
    created_at: datetime

    class Config:
        from_attributes = True


class UserUpdate(BaseModel):
    full_name: str | None = None
    digest_frequency: DigestFrequency | None = None
    digest_hour: int | None = Field(None, ge=0, le=23)
    digest_minute: int | None = Field(None, ge=0, le=59)
    timezone: str | None = None
    digest_enabled: bool | None = None


# Topic schemas
class TopicCreate(BaseModel):
    name: str = Field(max_length=100)
    description: str | None = None
    keywords: list[str] = Field(min_length=1, max_length=10)
    exclude_keywords: list[str] | None = None
    priority: int = Field(default=1, ge=1, le=5)


class TopicUpdate(BaseModel):
    name: str | None = Field(None, max_length=100)
    description: str | None = None
    keywords: list[str] | None = None
    exclude_keywords: list[str] | None = None
    priority: int | None = Field(None, ge=1, le=5)
    is_active: bool | None = None


class TopicResponse(BaseModel):
    id: str
    name: str
    description: str | None
    keywords: list[str]
    exclude_keywords: list[str]
    priority: int
    is_active: bool
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True

    @classmethod
    def from_orm_with_keywords(cls, topic: "Topic") -> "TopicResponse":  # noqa: F821
        return cls(
            id=topic.id,
            name=topic.name,
            description=topic.description,
            keywords=topic.get_keywords_list(),
            exclude_keywords=topic.get_exclude_keywords_list(),
            priority=topic.priority,
            is_active=topic.is_active,
            created_at=topic.created_at,
            updated_at=topic.updated_at,
        )


# Digest schemas
class DigestArticleResponse(BaseModel):
    id: str
    title: str
    source_url: str
    source_name: str | None
    ai_summary: str
    image_url: str | None
    published_at: datetime | None

    class Config:
        from_attributes = True


class DigestResponse(BaseModel):
    id: str
    ai_provider: str
    ai_model: str
    email_sent_at: datetime
    email_subject: str
    articles: list[DigestArticleResponse]

    class Config:
        from_attributes = True


# Preview schema
class PreviewRequest(BaseModel):
    topic_ids: list[str] | None = None


class PreviewArticle(BaseModel):
    title: str
    url: str
    source_name: str | None
    summary: str
    image_url: str | None


class PreviewTopic(BaseModel):
    name: str
    articles: list[PreviewArticle]


class PreviewResponse(BaseModel):
    topics: list[PreviewTopic]
    ai_provider: str
    ai_model: str
