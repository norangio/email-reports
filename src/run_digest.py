"""CLI entry point for sending digests.

Run with: python -m src.run_digest

Designed for GitHub Actions cron or manual local runs. Bypasses the
APScheduler time-of-day check since the cron schedule IS the timer.
Seeds the user and topics if the DB is empty (ephemeral CI databases).
"""

import asyncio
import logging
import sys

from sqlalchemy import select

from src.core.config import get_settings
from src.core.database import async_session_maker, init_db
from src.models.topic import Topic
from src.models.user import User
from src.services.digest import DigestService

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
)
logger = logging.getLogger(__name__)

settings = get_settings()

# Default user and topics to seed when DB is empty (e.g. GitHub Actions)
SEED_EMAIL = "norangio@gmail.com"
SEED_NAME = "Nick Orangio"
SEED_TOPICS = [
    {"name": "Biotech & Pharma", "keywords": "cell therapy,CAR-T,gene therapy,cell therapy manufacturing,CGT manufacturing,autologous manufacturing,allogeneic cell therapy,ADC manufacturing,antibody drug conjugate,CDMO,contract manufacturing,FUJIFILM Diosynth,Boehringer Ingelheim,Samsung Biologics,Recipharm"},
    {"name": "AI News", "keywords": "artificial intelligence,machine learning,LLM,OpenAI,Anthropic"},
    {"name": "NBA", "keywords": "NBA,basketball,NBA playoffs,NBA trade"},
    {"name": "Formula 1", "keywords": "Formula 1,F1,Grand Prix,FIA"},
    {"name": "San Diego Local", "keywords": "San Diego,North County San Diego,Encinitas,Carlsbad,Oceanside,Escondido,San Diego news,San Diego county"},
    {"name": "Asia & SE Asia", "keywords": "Southeast Asia biotech,Asia biotech industry,Singapore biotech,expat Asia,expat Southeast Asia,Asia pharma manufacturing,Thailand expat,Vietnam biotech"},
]


async def ensure_user(db) -> User:
    """Return the digest user, creating them if they don't exist."""
    result = await db.execute(select(User).where(User.email == SEED_EMAIL))
    user = result.scalar_one_or_none()

    if user:
        logger.info(f"Found existing user: {user.email}")
        return user

    logger.info(f"Seeding user {SEED_EMAIL} with {len(SEED_TOPICS)} topics")
    user = User(
        email=SEED_EMAIL,
        full_name=SEED_NAME,
        hashed_password="cli-runner-no-login",
        is_active=True,
        digest_enabled=True,
        digest_frequency="daily",
        digest_hour=16,  # 8am PST in UTC
        timezone="America/Los_Angeles",
    )
    db.add(user)
    await db.flush()

    for t in SEED_TOPICS:
        topic = Topic(
            user_id=user.id,
            name=t["name"],
            keywords=t["keywords"],
            is_active=True,
        )
        db.add(topic)

    await db.commit()
    logger.info("User and topics seeded")
    return user


async def main() -> None:
    """Initialize DB, seed user, generate and send digest."""
    logger.info("Initializing database")
    await init_db()

    digest_service = DigestService()

    try:
        async with async_session_maker() as db:
            user = await ensure_user(db)

            logger.info(f"Generating digest for {user.email}")
            digest = await digest_service.generate_and_send_digest(db, user)

            if digest:
                logger.info(f"Digest sent successfully (id={digest.id})")
            else:
                logger.warning("No digest generated (no content or send failed)")
    finally:
        await digest_service.close()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
    except Exception:
        logger.exception("Fatal error in digest runner")
        sys.exit(1)
