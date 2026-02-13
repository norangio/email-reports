"""SEC EDGAR filings service for tracking biotech/CDMO company filings."""

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

import httpx

from src.services.news import Article

logger = logging.getLogger(__name__)

# SEC requires a User-Agent with contact info
SEC_USER_AGENT = "NicksMorningBrief/1.0 (norangio@gmail.com)"

# 8-K item code descriptions (most common ones for biotech/pharma)
ITEM_8K_DESCRIPTIONS: dict[str, str] = {
    "1.01": "Entry into a Material Agreement",
    "1.02": "Termination of a Material Agreement",
    "1.03": "Bankruptcy or Receivership",
    "2.01": "Completion of Acquisition or Disposition of Assets",
    "2.02": "Results of Operations and Financial Condition",
    "2.03": "Creation of a Direct Financial Obligation",
    "2.04": "Triggering Events That Accelerate or Increase an Obligation",
    "2.05": "Costs Associated with Exit or Disposal Activities",
    "2.06": "Material Impairments",
    "3.01": "Notice of Delisting or Transfer",
    "3.02": "Unregistered Sales of Equity Securities",
    "3.03": "Material Modification to Rights of Security Holders",
    "4.01": "Changes in Registrant's Certifying Accountant",
    "4.02": "Non-Reliance on Previously Issued Financial Statements",
    "5.01": "Changes in Control of Registrant",
    "5.02": "Departure/Election of Directors or Officers; Appointment of Officers",
    "5.03": "Amendments to Articles of Incorporation or Bylaws",
    "5.05": "Amendments to Code of Ethics",
    "5.07": "Submission of Matters to a Vote of Security Holders",
    "7.01": "Regulation FD Disclosure",
    "8.01": "Other Events",
    "9.01": "Financial Statements and Exhibits",
}

# Human-readable descriptions for annual/quarterly/registration forms
FORM_DESCRIPTIONS: dict[str, str] = {
    "10-K": "Annual report with full-year financials, business overview, and risk factors",
    "10-K/A": "Amendment to annual report",
    "10-Q": "Quarterly financial report",
    "10-Q/A": "Amendment to quarterly report",
    "S-1": "IPO or public offering registration statement",
    "S-1/A": "Amendment to registration statement",
}

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

# 8-K item codes that indicate substantive, newsworthy events
NOTABLE_8K_ITEMS = {
    "1.01", "1.02", "1.03", "2.01", "2.02", "2.03", "2.04", "2.05", "2.06",
    "3.01", "3.02", "3.03", "4.01", "4.02", "5.01", "5.02", "5.03",
}


@dataclass
class ClassifiedFilings:
    """SEC filings split into notable (woven into prose) and routine (compact table)."""

    notable: list[Article] = field(default_factory=list)
    routine: list[Article] = field(default_factory=list)


def classify_filings(filings: list[Article]) -> ClassifiedFilings:
    """Classify filings into notable (8-K with substantive items) and routine."""
    result = ClassifiedFilings()
    for filing in filings:
        source = filing.source_name or ""
        # Check if it's an 8-K by looking at the title
        is_8k = "8-K" in filing.title
        if is_8k:
            # Extract item codes from the description
            desc = filing.description or ""
            item_codes = set()
            for part in desc.split("Item "):
                code = part.split(":")[0].strip().split(" ")[0]
                if code and code[0].isdigit():
                    item_codes.add(code)
            if item_codes & NOTABLE_8K_ITEMS:
                result.notable.append(filing)
            else:
                result.routine.append(filing)
        else:
            # 10-K, 10-Q, S-1 are always routine
            result.routine.append(filing)
    return result


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
        items_list = recent.get("items", [])

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
            raw_items = items_list[i] if i < len(items_list) else ""

            accession_dashed = accession.replace("-", "")
            filing_url = (
                f"https://www.sec.gov/Archives/edgar/data/{cik}/{accession_dashed}/{primary_doc}"
            )

            title, description = self._build_filing_text(
                company_name, ticker, form_type, filing_date_str, raw_items
            )

            articles.append(
                Article(
                    title=title,
                    url=filing_url,
                    description=description,
                    source_name=f"SEC EDGAR — {company_name}",
                    author=None,
                    published_at=filing_date,
                    image_url=None,
                )
            )

        return articles

    def _build_filing_text(
        self,
        company_name: str,
        ticker: str,
        form_type: str,
        filing_date: str,
        raw_items: str,
    ) -> tuple[str, str]:
        """Build title and description for a filing."""
        if form_type.startswith("8-K"):
            # Parse 8-K item codes (e.g. "2.02,9.01")
            item_codes = [s.strip() for s in raw_items.split(",") if s.strip()]
            item_descriptions = []
            for code in item_codes:
                desc = ITEM_8K_DESCRIPTIONS.get(code)
                if desc:
                    item_descriptions.append(f"Item {code}: {desc}")
                elif code:
                    item_descriptions.append(f"Item {code}")

            if item_descriptions:
                # Use the most informative item (skip 9.01 "Exhibits" if others exist)
                substantive = [d for d in item_descriptions if "9.01" not in d]
                headline_items = substantive or item_descriptions
                title = f"{company_name} ({ticker}) — {form_type}: {headline_items[0].split(': ', 1)[-1]}"
                description = (
                    f"{company_name} filed {form_type} on {filing_date}. "
                    + "; ".join(item_descriptions)
                    + "."
                )
            else:
                title = f"{company_name} ({ticker}) — {form_type}"
                description = f"{company_name} filed {form_type} on {filing_date}."
        else:
            # 10-K, 10-Q, S-1 — use the form description
            form_desc = FORM_DESCRIPTIONS.get(form_type, form_type)
            title = f"{company_name} ({ticker}) — {form_type}: {form_desc}"
            description = f"{company_name} filed {form_type} on {filing_date}. {form_desc}."

        return title, description
