"""Gist-based article history for cross-day deduplication.

Uses a private GitHub Gist as lightweight persistent storage so the digest
can skip articles already sent and give the AI previous synthesis context.
"""

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

import httpx

from src.core.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

GIST_FILENAME = "sent_articles.json"


@dataclass
class HistoryEntry:
    """A previously sent article."""

    url: str
    title: str
    topic: str
    date_sent: str  # ISO date (YYYY-MM-DD)


@dataclass
class DaySynthesis:
    """A topic's synthesis prose from a previous day."""

    topic: str
    prose: str
    date: str  # ISO date (YYYY-MM-DD)


@dataclass
class ArticleHistory:
    """Full history loaded from the gist."""

    entries: list[HistoryEntry] = field(default_factory=list)
    syntheses: list[DaySynthesis] = field(default_factory=list)

    def sent_urls(self, days: int = 3) -> set[str]:
        """URLs sent in the last N days."""
        cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%d")
        return {e.url for e in self.entries if e.date_sent >= cutoff}

    def recent_syntheses_by_topic(self, days: int = 7) -> dict[str, list[DaySynthesis]]:
        """Group recent syntheses by topic, newest first."""
        cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%d")
        by_topic: dict[str, list[DaySynthesis]] = {}
        for s in self.syntheses:
            if s.date >= cutoff:
                by_topic.setdefault(s.topic, []).append(s)
        # Sort each topic's list newest-first
        for topic_list in by_topic.values():
            topic_list.sort(key=lambda s: s.date, reverse=True)
        return by_topic


class GistHistoryService:
    """Read/write article history from a private GitHub Gist."""

    GIST_API = "https://api.github.com/gists"

    def __init__(self) -> None:
        self.gist_id = settings.gist_id
        self.token = settings.github_token
        self.client = httpx.AsyncClient(
            timeout=30.0,
            headers={
                "Authorization": f"token {self.token}",
                "Accept": "application/vnd.github+json",
            },
        )

    @property
    def enabled(self) -> bool:
        return bool(self.gist_id and self.token)

    async def close(self) -> None:
        await self.client.aclose()

    async def read_history(self) -> ArticleHistory:
        """Load history from the gist. Returns empty history on any failure."""
        if not self.enabled:
            return ArticleHistory()

        try:
            resp = await self.client.get(f"{self.GIST_API}/{self.gist_id}")
            resp.raise_for_status()
            gist_data = resp.json()

            file_content = gist_data.get("files", {}).get(GIST_FILENAME, {}).get("content", "{}")
            data = json.loads(file_content)

            entries = [
                HistoryEntry(
                    url=e["url"],
                    title=e["title"],
                    topic=e["topic"],
                    date_sent=e["date_sent"],
                )
                for e in data.get("articles", [])
            ]
            syntheses = [
                DaySynthesis(
                    topic=s["topic"],
                    prose=s["prose"],
                    date=s["date"],
                )
                for s in data.get("syntheses", [])
            ]

            logger.info(f"Loaded gist history: {len(entries)} articles, {len(syntheses)} syntheses")
            return ArticleHistory(entries=entries, syntheses=syntheses)

        except Exception as e:
            logger.warning(f"Failed to read gist history: {type(e).__name__}: {e}")
            return ArticleHistory()

    async def write_history(
        self,
        new_entries: list[HistoryEntry],
        new_syntheses: list[DaySynthesis],
        existing: ArticleHistory | None = None,
    ) -> bool:
        """Merge new data into the gist, pruning entries older than 7 days."""
        if not self.enabled:
            return False

        # Merge with existing
        all_entries = (existing.entries if existing else []) + new_entries
        all_syntheses = (existing.syntheses if existing else []) + new_syntheses

        # Prune older than 7 days
        cutoff = (datetime.now(timezone.utc) - timedelta(days=7)).strftime("%Y-%m-%d")
        all_entries = [e for e in all_entries if e.date_sent >= cutoff]
        all_syntheses = [s for s in all_syntheses if s.date >= cutoff]

        payload = {
            "last_updated": datetime.now(timezone.utc).isoformat(),
            "articles": [
                {"url": e.url, "title": e.title, "topic": e.topic, "date_sent": e.date_sent}
                for e in all_entries
            ],
            "syntheses": [
                {"topic": s.topic, "prose": s.prose, "date": s.date}
                for s in all_syntheses
            ],
        }

        try:
            resp = await self.client.patch(
                f"{self.GIST_API}/{self.gist_id}",
                json={"files": {GIST_FILENAME: {"content": json.dumps(payload, indent=2)}}},
            )
            resp.raise_for_status()
            logger.info(
                f"Updated gist history: {len(all_entries)} articles, "
                f"{len(all_syntheses)} syntheses"
            )
            return True

        except Exception as e:
            logger.warning(f"Failed to write gist history: {type(e).__name__}: {e}")
            return False
