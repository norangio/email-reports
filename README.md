# Nick's Morning Brief

A personalized daily news digest delivered to your inbox at 8am, powered by AI summarization. Articles are fetched from NewsAPI and RSS feeds, summarized by Claude (Anthropic), and sent via Resend — all orchestrated by a GitHub Actions cron job.

## How It Works

1. **Fetch** — NewsAPI + RSS feeds pull articles for each topic based on keywords
2. **Summarize** — Claude Sonnet 4.5 generates concise summaries for each article
3. **Overview** — A witty, sarcastic overview paragraph is generated from all headlines
4. **Send** — The digest email is composed and delivered via Resend

## Current Topics

| Topic | Keywords |
|---|---|
| Cell & Gene Therapy | CAR-T, gene therapy, CGT manufacturing, ADC manufacturing |
| AI News | artificial intelligence, LLM, OpenAI, Anthropic |
| NBA | NBA, basketball, playoffs, trades |
| Formula 1 | F1, Grand Prix, FIA |
| San Diego Local | San Diego, North County, Encinitas, Carlsbad, Oceanside |
| Asia & SE Asia | Southeast Asia biotech, expat news, Singapore, pharma manufacturing |

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
├── run_digest.py    # CLI entry point (GitHub Actions calls this)
├── main.py          # FastAPI web app
├── scheduler.py     # APScheduler (local server mode only)
├── core/
│   ├── config.py    # Pydantic settings from .env
│   └── database.py  # Async SQLAlchemy + SQLite
├── models/          # User, Topic, Digest ORM models
├── services/
│   ├── news.py      # NewsAPI + RSS feed fetching
│   ├── summarizer.py # AI summarization + overview generation
│   ├── email.py     # Resend email delivery
│   └── digest.py    # Orchestration (fetch → summarize → send)
└── templates/       # Jinja2 email templates (HTML + plaintext)
```

## Known Limitations & Next Steps

- **NewsAPI free tier** only returns articles 24h+ old and may miss niche topics — consider upgrading or adding specialized RSS feeds
- **San Diego Local** topic relevance is loose — NewsAPI doesn't have great local news coverage
- **Resend test address** (`onboarding@resend.dev`) can only send to the account owner — verify a custom domain for wider delivery
- **Summary quality** can be further tuned via prompt engineering in `summarizer.py`

## Configuration

All settings are in `.env`. Key variables:

| Variable | Description | Default |
|---|---|---|
| `AI_PROVIDER` | `anthropic` or `openai` | `anthropic` |
| `ANTHROPIC_MODEL` | Claude model | `claude-sonnet-4-5-20250929` |
| `MAX_ARTICLES_PER_TOPIC` | Articles per topic | `5` |
| `SUMMARY_MAX_LENGTH` | Max summary tokens | `1000` |
| `EMAIL_FROM_NAME` | Sender display name | `Nick's Morning Brief` |

## License

MIT
