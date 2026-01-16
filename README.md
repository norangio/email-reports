# AI News Digest

An AI-powered personalized news digest application that delivers curated news summaries directly to your inbox.

## Features

- **Customizable Topics**: Define 3-5 topics of interest with keywords
- **AI-Powered Summaries**: Uses Claude (Anthropic) or GPT (OpenAI) to generate concise summaries
- **Flexible Scheduling**: Daily, twice-weekly, weekly, or monthly digests
- **Clean Email Format**: Simple Calibri 11pt formatting with embedded images
- **Source Attribution**: Every summary includes links to original sources
- **Model Transparency**: Each digest shows which AI model generated the summaries

## Architecture

```
src/
├── api/            # REST API (FastAPI)
│   ├── routes.py   # API endpoints
│   ├── schemas.py  # Pydantic models
│   └── auth.py     # JWT authentication
├── core/           # Configuration & database
│   ├── config.py   # Settings from environment
│   └── database.py # SQLAlchemy async setup
├── models/         # Database models
│   ├── user.py     # User accounts & preferences
│   ├── topic.py    # Topic definitions
│   └── digest.py   # Sent digest records
├── services/       # Business logic
│   ├── news.py     # NewsAPI + RSS fetching
│   ├── summarizer.py # AI summarization
│   ├── email.py    # Resend email sending
│   └── digest.py   # Orchestration
├── templates/      # Email templates (Jinja2)
├── scheduler.py    # APScheduler background jobs
└── main.py         # FastAPI application entry
```

## Quick Start

### Prerequisites

- Python 3.10+
- API keys for:
  - [NewsAPI](https://newsapi.org/) (free tier available)
  - [Anthropic](https://console.anthropic.com/) or [OpenAI](https://platform.openai.com/)
  - [Resend](https://resend.com/) (free tier: 3000 emails/month)

### Installation

1. Clone and install dependencies:

```bash
git clone <repository-url>
cd email-reports
pip install -e .
```

2. Configure environment:

```bash
cp .env.example .env
# Edit .env with your API keys
```

3. Run the application:

```bash
uvicorn src.main:app --reload
```

4. Access the API docs at `http://localhost:8000/docs`

## API Endpoints

### Authentication

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/v1/auth/register` | Create account |
| POST | `/api/v1/auth/login` | Get access token |

### User Preferences

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/v1/users/me` | Get profile |
| PATCH | `/api/v1/users/me` | Update preferences |

### Topics

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/v1/topics` | List topics |
| POST | `/api/v1/topics` | Create topic |
| GET | `/api/v1/topics/{id}` | Get topic |
| PATCH | `/api/v1/topics/{id}` | Update topic |
| DELETE | `/api/v1/topics/{id}` | Delete topic |

### Digests

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/v1/digests` | List past digests |
| POST | `/api/v1/digests/preview` | Preview next digest |
| POST | `/api/v1/digests/send` | Send digest now |

## Configuration

### Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `AI_PROVIDER` | `anthropic` or `openai` | `anthropic` |
| `ANTHROPIC_API_KEY` | Anthropic API key | - |
| `ANTHROPIC_MODEL` | Claude model | `claude-sonnet-4-20250514` |
| `OPENAI_API_KEY` | OpenAI API key | - |
| `OPENAI_MODEL` | GPT model | `gpt-4o` |
| `NEWSAPI_KEY` | NewsAPI key | - |
| `RESEND_API_KEY` | Resend API key | - |
| `EMAIL_FROM_ADDRESS` | Sender email | `digest@yourdomain.com` |
| `DATABASE_URL` | Database connection | SQLite |
| `MAX_TOPICS_PER_USER` | Topic limit | `5` |

## Deployment Options

### Railway

1. Connect your GitHub repository
2. Add environment variables in Railway dashboard
3. Deploy (auto-detects Python + Dockerfile)

### Render

1. Create new Web Service from repository
2. Set build command: `pip install .`
3. Set start command: `uvicorn src.main:app --host 0.0.0.0 --port $PORT`
4. Add environment variables

### Docker

```bash
docker-compose up -d
```

### Fly.io

```bash
fly launch
fly secrets set ANTHROPIC_API_KEY=... NEWSAPI_KEY=... RESEND_API_KEY=...
fly deploy
```

## Email Template

Emails are rendered with:
- Clean Calibri 11pt font (fallback to Arial/sans-serif)
- Embedded article images when available
- Source links for every article
- AI model attribution footer
- Both HTML and plain text versions

## Example Usage

### Create a Topic

```bash
curl -X POST http://localhost:8000/api/v1/topics \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "AI & Machine Learning",
    "keywords": ["artificial intelligence", "machine learning", "LLM", "neural networks"],
    "exclude_keywords": ["crypto", "NFT"],
    "priority": 5
  }'
```

### Update Digest Preferences

```bash
curl -X PATCH http://localhost:8000/api/v1/users/me \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "digest_frequency": "daily",
    "digest_hour": 7,
    "timezone": "America/New_York"
  }'
```

### Send Digest On-Demand

```bash
curl -X POST http://localhost:8000/api/v1/digests/send \
  -H "Authorization: Bearer $TOKEN"
```

## Development

```bash
# Install dev dependencies
pip install -e ".[dev]"

# Run tests
pytest

# Format code
black src tests
ruff check src tests

# Type checking
mypy src
```

## License

MIT
