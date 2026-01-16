"""API routes."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.api.auth import (
    create_access_token,
    get_current_user,
    hash_password,
    verify_password,
)
from src.api.schemas import (
    DigestResponse,
    PreviewArticle,
    PreviewRequest,
    PreviewResponse,
    PreviewTopic,
    Token,
    TopicCreate,
    TopicResponse,
    TopicUpdate,
    UserCreate,
    UserLogin,
    UserResponse,
    UserUpdate,
)
from src.core.config import get_settings
from src.core.database import get_db
from src.models.digest import Digest
from src.models.topic import Topic
from src.models.user import User
from src.services.digest import DigestService
from src.services.email import EmailService

settings = get_settings()

router = APIRouter()


# ============================================================================
# Auth Routes
# ============================================================================


@router.post("/auth/register", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
async def register(
    user_data: UserCreate,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> User:
    """Register a new user."""
    # Check if email exists
    result = await db.execute(select(User).where(User.email == user_data.email))
    if result.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Email already registered",
        )

    # Create user
    user = User(
        email=user_data.email,
        hashed_password=hash_password(user_data.password),
        full_name=user_data.full_name,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)

    # Send welcome email (fire and forget)
    try:
        email_service = EmailService()
        await email_service.send_welcome_email(user.email, user.full_name)
    except Exception:
        pass  # Don't fail registration if email fails

    return user


@router.post("/auth/login", response_model=Token)
async def login(
    credentials: UserLogin,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> dict:
    """Login and get access token."""
    result = await db.execute(select(User).where(User.email == credentials.email))
    user = result.scalar_one_or_none()

    if not user or not verify_password(credentials.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
        )

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Account is disabled",
        )

    token = create_access_token(user.id)
    return {"access_token": token, "token_type": "bearer"}


# ============================================================================
# User Routes
# ============================================================================


@router.get("/users/me", response_model=UserResponse)
async def get_me(
    current_user: Annotated[User, Depends(get_current_user)],
) -> User:
    """Get current user profile."""
    return current_user


@router.patch("/users/me", response_model=UserResponse)
async def update_me(
    updates: UserUpdate,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> User:
    """Update current user preferences."""
    update_data = updates.model_dump(exclude_unset=True)

    for field, value in update_data.items():
        if value is not None:
            setattr(current_user, field, value)

    db.add(current_user)
    await db.commit()
    await db.refresh(current_user)

    return current_user


# ============================================================================
# Topic Routes
# ============================================================================


@router.get("/topics", response_model=list[TopicResponse])
async def list_topics(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> list[TopicResponse]:
    """List all topics for current user."""
    result = await db.execute(
        select(Topic).where(Topic.user_id == current_user.id).order_by(Topic.priority.desc())
    )
    topics = result.scalars().all()
    return [TopicResponse.from_orm_with_keywords(t) for t in topics]


@router.post("/topics", response_model=TopicResponse, status_code=status.HTTP_201_CREATED)
async def create_topic(
    topic_data: TopicCreate,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> TopicResponse:
    """Create a new topic."""
    # Check topic limit
    result = await db.execute(
        select(Topic).where(Topic.user_id == current_user.id)
    )
    existing_count = len(result.scalars().all())

    if existing_count >= settings.max_topics_per_user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Maximum {settings.max_topics_per_user} topics allowed",
        )

    topic = Topic(
        user_id=current_user.id,
        name=topic_data.name,
        description=topic_data.description,
        keywords=",".join(topic_data.keywords),
        exclude_keywords=",".join(topic_data.exclude_keywords) if topic_data.exclude_keywords else None,
        priority=topic_data.priority,
    )
    db.add(topic)
    await db.commit()
    await db.refresh(topic)

    return TopicResponse.from_orm_with_keywords(topic)


@router.get("/topics/{topic_id}", response_model=TopicResponse)
async def get_topic(
    topic_id: str,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> TopicResponse:
    """Get a specific topic."""
    result = await db.execute(
        select(Topic).where(Topic.id == topic_id, Topic.user_id == current_user.id)
    )
    topic = result.scalar_one_or_none()

    if not topic:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Topic not found",
        )

    return TopicResponse.from_orm_with_keywords(topic)


@router.patch("/topics/{topic_id}", response_model=TopicResponse)
async def update_topic(
    topic_id: str,
    updates: TopicUpdate,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> TopicResponse:
    """Update a topic."""
    result = await db.execute(
        select(Topic).where(Topic.id == topic_id, Topic.user_id == current_user.id)
    )
    topic = result.scalar_one_or_none()

    if not topic:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Topic not found",
        )

    update_data = updates.model_dump(exclude_unset=True)

    # Handle keywords conversion
    if "keywords" in update_data and update_data["keywords"]:
        topic.keywords = ",".join(update_data["keywords"])
        del update_data["keywords"]

    if "exclude_keywords" in update_data:
        if update_data["exclude_keywords"]:
            topic.exclude_keywords = ",".join(update_data["exclude_keywords"])
        else:
            topic.exclude_keywords = None
        del update_data["exclude_keywords"]

    for field, value in update_data.items():
        if value is not None:
            setattr(topic, field, value)

    db.add(topic)
    await db.commit()
    await db.refresh(topic)

    return TopicResponse.from_orm_with_keywords(topic)


@router.delete("/topics/{topic_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_topic(
    topic_id: str,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> None:
    """Delete a topic."""
    result = await db.execute(
        select(Topic).where(Topic.id == topic_id, Topic.user_id == current_user.id)
    )
    topic = result.scalar_one_or_none()

    if not topic:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Topic not found",
        )

    await db.delete(topic)
    await db.commit()


# ============================================================================
# Digest Routes
# ============================================================================


@router.get("/digests", response_model=list[DigestResponse])
async def list_digests(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    limit: int = 10,
) -> list[Digest]:
    """List recent digests for current user."""
    result = await db.execute(
        select(Digest)
        .options(selectinload(Digest.articles))
        .where(Digest.user_id == current_user.id)
        .order_by(Digest.email_sent_at.desc())
        .limit(limit)
    )
    return list(result.scalars().all())


@router.post("/digests/preview", response_model=PreviewResponse)
async def preview_digest(
    request: PreviewRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> PreviewResponse:
    """
    Preview what the next digest would look like.

    This fetches real news and generates summaries but doesn't send an email.
    """
    # Get topics
    query = select(Topic).where(Topic.user_id == current_user.id, Topic.is_active == True)
    if request.topic_ids:
        query = query.where(Topic.id.in_(request.topic_ids))

    result = await db.execute(query)
    topics = result.scalars().all()

    if not topics:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No active topics found",
        )

    digest_service = DigestService()
    try:
        preview_topics: list[PreviewTopic] = []

        for topic in topics:
            keywords = topic.get_keywords_list()
            exclude = topic.get_exclude_keywords_list()

            articles = await digest_service.news_service.fetch_news_for_topic(
                keywords=keywords,
                exclude_keywords=exclude,
                max_articles=5,  # Limit for preview
            )

            if not articles:
                continue

            summaries = await digest_service.summarizer.summarize_articles(
                articles=articles,
                topic_name=topic.name,
                topic_keywords=keywords,
            )

            preview_articles = [
                PreviewArticle(
                    title=article.title,
                    url=article.url,
                    source_name=article.source_name,
                    summary=summary.summary,
                    image_url=article.image_url,
                )
                for article, summary in zip(articles, summaries)
            ]

            preview_topics.append(PreviewTopic(name=topic.name, articles=preview_articles))

        ai_provider, ai_model = digest_service.summarizer.get_model_info()

        return PreviewResponse(
            topics=preview_topics,
            ai_provider=ai_provider,
            ai_model=ai_model,
        )

    finally:
        await digest_service.close()


@router.post("/digests/send", response_model=DigestResponse)
async def send_digest_now(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> Digest:
    """
    Send a digest immediately (on-demand).

    This ignores the scheduled frequency and sends a digest right now.
    """
    digest_service = DigestService()
    try:
        digest = await digest_service.generate_and_send_digest(db, current_user)

        if not digest:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Could not generate digest. Make sure you have active topics.",
            )

        # Reload with articles
        result = await db.execute(
            select(Digest)
            .options(selectinload(Digest.articles))
            .where(Digest.id == digest.id)
        )
        return result.scalar_one()

    finally:
        await digest_service.close()


# ============================================================================
# Health Check
# ============================================================================


@router.get("/health")
async def health_check() -> dict:
    """Health check endpoint."""
    return {
        "status": "healthy",
        "version": settings.app_version,
        "ai_provider": settings.ai_provider.value,
    }
