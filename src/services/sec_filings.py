"""SEC EDGAR filings service for tracking biotech/CDMO company filings."""

import logging
from datetime import datetime, timedelta, timezone

import httpx

from src.services.news import Article

logger = logging.getLogger(__name__)

# SEC requires a User-Agent with contact info
SEC_USER_AGENT = "NicksMorningBrief/1.0 (norangio@gmail.com)"

# Hardcoded CIK map — avoids runtime lookups against EDGAR search
TICKER_TO_CIK: dict[str, tuple[int, str]] = {
    "VRTX": (875320, "Vertex Pharmaceuticals"),
    "LEGN": (1801198, "Legend Biotech"),
    "ACLX": (1786205, "Arcellx"),
    "CRSP": (1674416, "CRISPR Therapeutics"),
    "SGMO": (1001233, "Sangamo Therapeutics"),
    "BEAM": (1745999, "Beam Therapeutics"),
    "BLUE": (1597264, "bluebird bio"),
    "MRNA": (1682852, "Moderna"),
    "SRPT": (873303, "Sarepta Therapeutics"),
    "NTLA": (1652130, "Intellia Therapeutics"),
    "EDIT": (1650664, "Editas Medicine"),
    "ALLO": (1737287, "Allogene Therapeutics"),
    "LZAGY": (1311370, "Lonza Group"),
    "CTLT": (1596783, "Catalent"),
    "TMO": (97745, "Thermo Fisher Scientific"),
    "DHR": (313616, "Danaher"),
    "NBIX": (914475, "Neurocrine Biosciences"),
}

# Form types to track
TRACKED_FORMS = {"8-K", "8-K/A", "10-Q", "10-Q/A", "10-K", "10-K/A", "S-1", "S-1/A"}


class SecFilingsService:
    """Fetches recent SEC filings for a watchlist of biotech/CDMO companies."""

    SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik}.json"

    def __init__(self) -> None:
        self.client = httpx.AsyncClient(
            timeout=30.0,
            headers={
                "User-Agent": SEC_USER_AGENT,
                "Accept-Encoding": "gzip, deflate",
            },
        )

    async def close(self) -> None:
        await self.client.aclose()

    async def fetch_recent_filings(
        self, days_back: int = 7, max_filings: int = 10
    ) -> list[Article]:
        """Fetch recent filings for all watched companies."""
        cutoff = datetime.now(timezone.utc) - timedelta(days=days_back)
        articles: list[Article] = []

        for ticker, (cik, company_name) in TICKER_TO_CIK.items():
            try:
                company_articles = await self._fetch_company_filings(
                    ticker, cik, company_name, cutoff
                )
                articles.extend(company_articles)
            except Exception as e:
                logger.warning(f"Failed to fetch filings for {ticker}: {e}")

        articles.sort(key=lambda a: a.published_at or datetime.min, reverse=True)
        return articles[:max_filings]

    async def _fetch_company_filings(
        self,
        ticker: str,
        cik: int,
        company_name: str,
        cutoff: datetime,
    ) -> list[Article]:
        """Fetch and filter filings for a single company."""
        padded_cik = str(cik).zfill(10)
        url = self.SUBMISSIONS_URL.format(cik=padded_cik)

        response = await self.client.get(url)
        response.raise_for_status()
        data = response.json()

        recent = data.get("filings", {}).get("recent", {})
        forms = recent.get("form", [])
        dates = recent.get("filingDate", [])
        accessions = recent.get("accessionNumber", [])
        primary_docs = recent.get("primaryDocument", [])
        descriptions = recent.get("primaryDocDescription", [])

        articles: list[Article] = []
        for i, form_type in enumerate(forms):
            if form_type not in TRACKED_FORMS:
                continue

            filing_date_str = dates[i] if i < len(dates) else None
            if not filing_date_str:
                continue

            filing_date = datetime.strptime(filing_date_str, "%Y-%m-%d").replace(
                tzinfo=timezone.utc
            )
            if filing_date < cutoff:
                break  # filings are reverse-chronological, so stop early

            accession = accessions[i] if i < len(accessions) else ""
            primary_doc = primary_docs[i] if i < len(primary_docs) else ""
            desc = descriptions[i] if i < len(descriptions) else ""

            accession_dashed = accession.replace("-", "")
            filing_url = (
                f"https://www.sec.gov/Archives/edgar/data/{cik}/{accession_dashed}/{primary_doc}"
            )

            title = f"{company_name} ({ticker}) — {form_type}"
            if desc:
                title += f": {desc}"

            articles.append(
                Article(
                    title=title,
                    url=filing_url,
                    description=f"{form_type} filed {filing_date_str} by {company_name}. {desc}",
                    source_name=f"SEC EDGAR — {company_name}",
                    author=None,
                    published_at=filing_date,
                    image_url=None,
                )
            )

        return articles
