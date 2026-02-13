# Nick's Morning Brief

A personalized daily news digest delivered to your inbox at 8am, powered by AI synthesis. Articles are fetched from NewsAPI and curated RSS feeds, scraped for full content, synthesized into flowing prose by Claude, and sent via Resend — all orchestrated by a GitHub Actions cron job.

## How It Works

1. **Fetch** — NewsAPI + topic-specific RSS feeds pull articles for each topic based on keywords
2. **Scrape** — Article body text is extracted via trafilatura for richer AI context
3. **Classify** — SEC filings are split into notable (woven into prose) vs routine (compact table)
4. **Synthesize** — Claude Sonnet 4.5 generates 3-5 paragraphs of flowing prose per topic with inline `[N]` source citations (~7 AI calls total)
5. **Overview** — A witty 3-4 item highlight reel is generated from the syntheses
6. **Send** — The digest email is composed and delivered via Resend

## Current Topics

| Topic | Source Strategy | Keywords |
|---|---|---|
| Biotech & Pharma | Dedicated RSS (FierceBiotech, FiercePharma, STAT, GEN) | CAR-T, gene therapy, CGT manufacturing, ADC, CDMO |
| AI News | NewsAPI + generic RSS | artificial intelligence, LLM, OpenAI, Anthropic |
| NBA | NewsAPI + generic RSS | NBA, basketball, playoffs, trades |
| Formula 1 | NewsAPI + generic RSS | F1, Grand Prix, FIA |
| Asia & SE Asia | Cross-filtered RSS (regional + global biotech) | Samsung Biologics, Celltrion, WuXi, Singapore, NMPA |
| San Diego Local | NewsAPI + generic RSS | San Diego, North County, Encinitas, Carlsbad |

## Setup

### Prerequisites

- Python 3.10+
- [Anthropic API key](https://console.anthropic.com/) (~$0.05-0.10/day)
- [NewsAPI key](https://newsapi.org/) (free tier — articles 24h+ old)
- [Resend API key](https://resend.com/) (free tier: 100 emails/day)

### Local Development

```bash
cd email-reports
python -m venv .venv
source .venv/bin/activate
pip install -e .
pip install "pydantic[email]" "bcrypt==4.1.3"

cp .env.example .env
# Edit .env with your API keys
```

### Send a digest manually

```bash
python -m src.run_digest
```

This initializes the DB, seeds the user/topics if empty, and sends the digest immediately.

### Run the web server (optional)

```bash
uvicorn src.main:app --reload
# API docs at http://localhost:8000/docs
```

The web server provides a REST API for managing users, topics, and digests. It's not required for the daily email — that's handled by the CLI runner.

## Deployment — GitHub Actions

The daily digest runs via GitHub Actions cron. No server needed.

**Workflow**: `.github/workflows/daily-digest.yml`
**Schedule**: 8:00 AM PST daily (16:00 UTC), plus manual trigger

### Required Secrets

Add these in repo **Settings > Secrets and variables > Actions > Repository secrets**:

| Secret | Description |
|---|---|
| `ANTHROPIC_API_KEY` | Anthropic API key (must have credits) |
| `NEWSAPI_KEY` | NewsAPI key |
| `RESEND_API_KEY` | Resend API key |
| `SECRET_KEY` | Any random string (app config, not used by digest) |

### Manual Trigger

Go to **Actions > Daily Digest > Run workflow** to send a digest on demand.

## Architecture

```
src/
├── run_digest.py      # CLI entry point (GitHub Actions calls this)
├── main.py            # FastAPI web app
├── scheduler.py       # APScheduler (local server mode only)
├── core/
│   ├── config.py      # Pydantic settings from .env
│   └── database.py    # Async SQLAlchemy + SQLite
├── models/            # User, Topic, Digest ORM models
├── services/
│   ├── news.py        # NewsAPI + RSS feed fetching (topic-specific + cross-filtered)
│   ├── scraper.py     # Article body text extraction via trafilatura
│   ├── sec_filings.py # EDGAR filings: fetch, classify, scrape content
│   ├── summarizer.py  # AI synthesis (per-topic prose + overview + filing summaries)
│   ├── email.py       # Resend email delivery + template rendering
│   └── digest.py      # Orchestration: fetch → scrape → classify → synthesize → render → send
└── templates/
    ├── brief_email.html  # Morning Brief HTML template (600px table, Calibri)
    └── brief_email.txt   # Plain text fallback
```

## Email Format

- **Overview**: 3-4 curated highlight bullets (witty/dry tone), prioritizing biotech+AI, SD biotech, Asia opportunities
- **Topic sections**: 3-5 paragraphs of synthesized prose per topic with superscript `[N]` citation links
- **SEC filings**: Notable 8-K filings woven into Biotech & Pharma prose; routine filings in a compact table with AI-generated 1-sentence summaries
- **Sources**: Numbered reference list at bottom with title, source, and link

## Configuration

All settings are in `.env`. Key variables:

| Variable | Description | Default |
|---|---|---|
| `AI_PROVIDER` | `anthropic` or `openai` | `anthropic` |
| `ANTHROPIC_MODEL` | Claude model | `claude-sonnet-4-5-20250929` |
| `MAX_ARTICLES_PER_TOPIC` | Articles per topic | `8` |
| `SUMMARY_MAX_LENGTH` | Max summary tokens | `1000` |
| `EMAIL_FROM_NAME` | Sender display name | `Nick's Morning Brief` |

## Known Limitations

- **NewsAPI free tier** only returns articles 24h+ old and may miss niche topics
- **San Diego Local** topic relevance is loose — NewsAPI doesn't have great local news coverage
- **Resend test address** (`onboarding@resend.dev`) can only send to the account owner — verify a custom domain for wider delivery
- **Asia feeds** depend on a small number of working RSS sources — several tested feeds (BioSpectrum Asia, Korea Herald, FiercePharma Asia) were non-functional as of Feb 2026

## License

MIT
