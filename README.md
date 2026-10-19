# StreamGuard 🛡️

**Enterprise-grade, high-throughput content moderation data pipeline.**

Real-time WebSocket ingestion → Redis Stream brokering → NLP analysis workers → PostgreSQL audit logging.

---

## Architecture Overview

```
┌─────────────┐     ┌──────────────────┐     ┌──────────────┐     ┌──────────────┐
│   Clients   │────▶│  FastAPI Gateway  │────▶│ Redis Streams │────▶│   Workers    │
│  WebSocket  │◀────│   /ws/chat/{id}   │     │  (Broker)     │     │  (NLP + DB)  │
└─────────────┘     └──────────────────┘     └──────────────┘     └──────────────┘
                           │                                            │
                    ┌──────┴──────┐                              ┌──────┴──────┐
                    │  Rate Limit  │                              │ PostgreSQL  │
                    │  (Redis ZSET)│                              │ (Audit Log) │
                    └─────────────┘                              └─────────────┘
```

## Tech Stack

| Component | Technology | Purpose |
|-----------|-----------|---------|
| API Gateway | FastAPI (ASGI) | Async WebSocket + REST endpoints |
| Message Broker | Redis Streams | Decoupled message queue with consumer groups |
| Relational Store | PostgreSQL 15 + SQLAlchemy Async | ACID audit logs with compound indexes |
| Caching Layer | Redis Key-Value | Blacklist tracking, analytics cache (<2ms) |
| NLP Engine | Regex pattern matching | Toxicity scoring across 5 categories |
| Rate Limiter | Redis Sorted Sets | Sliding window violation tracking |
| Containerization | Docker & Docker Compose | Full environment parity |

## Quick Start

### 1. Clone & Setup Environment

```bash
cp .env.example .env
```

### 2. Start Infrastructure (Docker)

```bash
docker-compose up -d
```

This spins up:
- **PostgreSQL 15** on port `5432`
- **Redis 7** on port `6379`
- **StreamGuard App** on port `8000`

### 3. Local Development (without Docker)

```bash
# Create virtual environment
python -m venv venv
source venv/bin/activate  # Linux/Mac
.\venv\Scripts\Activate    # Windows

# Install dependencies
pip install -r requirements.txt

# Run database migrations
alembic upgrade head

# Start the server
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

## API Endpoints

### Authentication
| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/auth/register` | Register a new user |
| POST | `/api/auth/login` | Login and get JWT token |

### WebSocket
| Protocol | Endpoint | Description |
|----------|----------|-------------|
| WS | `/ws/chat/{room_id}` | Real-time chat (send JWT first) |

### Analytics (Phase 6)
| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/analytics/toxicity-trends` | Time-series toxicity data |
| GET | `/api/analytics/top-violators` | Top users by violations |
| GET | `/api/analytics/room-stats/{room_id}` | Per-room statistics |

### System
| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/health` | System health check |
| GET | `/docs` | Swagger UI (auto-generated) |

## WebSocket Protocol

```
1. Connect to ws://localhost:8000/ws/chat/{room_id}
2. Send JWT token as first message (plain text)
3. Receive: {"type": "system", "message": "Connected to room..."}
4. Send/receive chat messages (plain text, max 2000 chars)
5. Receive: {"type": "message", "username": "...", "content": "..."}
```

## Content Moderation Pipeline

Messages flow through a 5-category NLP analysis engine:

| Category | Weight | Examples |
|----------|--------|----------|
| Threats | 0.95 | Death threats, violence incitement |
| Hate Speech | 0.90 | Slurs, discriminatory language |
| Profanity | 0.70 | Obscenities, vulgarities |
| Harassment | 0.60 | Targeted insults, doxxing threats |
| Spam | 0.40 | Repeated chars, ALL CAPS, phishing |

**Action thresholds:**
- Score < 0.3 → `allowed`
- Score 0.3–0.7 → `flagged`
- Score > 0.7 → `blocked`

## Rate Limiting (Phase 5)

- **Sliding window**: Configurable (default: 10 seconds)
- **Threshold**: 3 violations within window → automatic blacklist
- **Blacklist TTL**: 1 hour (configurable)
- **Implementation**: Redis Sorted Sets with timestamp scores

## Project Structure

```
StreamGuard/
├── app/
│   ├── __init__.py
│   ├── main.py              # FastAPI app factory + lifespan
│   ├── config.py             # Pydantic Settings (env vars)
│   ├── database.py           # Async SQLAlchemy engine + sessions
│   ├── redis_client.py       # Redis connection manager (3 pools)
│   ├── auth.py               # JWT + bcrypt utilities
│   ├── schemas.py            # Pydantic v2 request/response schemas
│   ├── gateway.py            # WebSocket gateway + ConnectionManager
│   ├── rate_limiter.py       # Redis sliding window rate limiter
│   ├── models/
│   │   ├── __init__.py
│   │   ├── user.py           # User model (SQLAlchemy 2.0)
│   │   └── moderation_log.py # ModerationLog + compound indexes
│   ├── nlp/
│   │   ├── __init__.py
│   │   └── content_analyzer.py  # 26 regex patterns, 5 categories
│   ├── routes/
│   │   ├── __init__.py
│   │   ├── auth_routes.py    # POST /register, /login
│   │   └── analytics_routes.py  # GET trends, violators, room stats
│   └── worker/
│       ├── __init__.py
│       ├── stream_consumer.py   # Redis Stream XREADGROUP consumer
│       └── worker_manager.py    # Worker pool lifecycle + auto-restart
├── alembic/
│   ├── env.py                # Async Alembic environment
│   ├── script.py.mako
│   └── versions/
│       └── 001_initial_schema.py
├── docker-compose.yml
├── Dockerfile
├── requirements.txt
├── alembic.ini
├── .env.example
├── .dockerignore
└── .gitignore
```

## Configuration

All settings use the `STREAMGUARD_` environment variable prefix:

| Variable | Default | Description |
|----------|---------|-------------|
| `STREAMGUARD_DATABASE_URL` | `postgresql+asyncpg://...` | PostgreSQL connection |
| `STREAMGUARD_REDIS_URL` | `redis://localhost:6379` | Redis connection |
| `STREAMGUARD_JWT_SECRET` | `streamguard-dev-secret...` | JWT signing key |
| `STREAMGUARD_RATE_LIMIT_MAX_VIOLATIONS` | `3` | Violations before blacklist |
| `STREAMGUARD_RATE_LIMIT_WINDOW_SECONDS` | `10` | Sliding window duration |
| `STREAMGUARD_WORKER_BATCH_SIZE` | `50` | Messages per worker batch |
| `STREAMGUARD_CACHE_TTL_SECONDS` | `300` | Analytics cache TTL |


