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
| NLP Engine | Meta FastText + Hugging Face Hub | Supervised ML toxicity classification & subword n-grams |
| Rate Limiter | Redis Sorted Sets | Sliding window violation tracking |
| Containerization | Docker & Docker Compose | Full environment parity |
| Testing Suite | Pytest + pytest-asyncio + aiosqlite | Automated async unit, integration & stress testing |

---

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

---

## Testing & Quality Assurance

StreamGuard comes with an automated test suite covering unit tests, integration tests, schema validations, and high-concurrency load testing.

### Test Architecture

- **Pytest + pytest-asyncio**: Async test execution with `asyncio_mode = auto`.
- **Database Isolation**: In-memory SQLite (`sqlite+aiosqlite:///:memory:`) using `StaticPool` for fast, isolated test execution without requiring a live PostgreSQL instance.
- **Mock Redis Pipeline**: Clean atomic pipeline simulation verifying sorted set scoring (`ZADD`, `ZREMRANGEBYSCORE`, `ZCARD`), expiry (`EXPIRE`), and key-value operations.
- **FastAPI Dependency Injection**: Overriding `get_db` and testing via `httpx.AsyncClient` with `ASGITransport`.

### Running Tests

Run the complete test suite:

```bash
pytest
```

Run with verbose per-test results:

```bash
pytest -v
```

Run a specific test category or file:

```bash
# NLP Content Moderation Engine
pytest tests/test_nlp.py -v

# Authentication & JWT Security
pytest tests/test_auth.py -v

# Sliding Window Rate Limiter
pytest tests/test_rate_limiter.py -v

# REST API Endpoints
pytest tests/test_api_routes.py -v

# WebSocket Gateway & ConnectionManager
pytest tests/test_gateway.py -v

# Background Stream Consumers & Workers
pytest tests/test_worker.py -v

# Pydantic Schemas & Constraints
pytest tests/test_schemas.py -v
```

### Test Suite Coverage

| Test Module | Focus Area | Key Scenarios Tested |
|-------------|------------|----------------------|
| `tests/test_nlp.py` | NLP Moderation | Clean messages, 5 threat/hate/profanity/harassment/spam categories, unicode NFKC normalization, weighted scoring, threshold actions (`allowed`, `flagged`, `blocked`), custom pattern injections. |
| `tests/test_auth.py` | Auth & Security | Bcrypt password hashing & verification, JWT access token generation, claims decoding (`sub`, `username`), expired token rejection, tampered signatures, missing claims. |
| `tests/test_rate_limiter.py` | Rate Limiting | Redis ZSET sliding window, violation recording, automatic TTL pruning, threshold breach triggers (`blacklisted: True`), violation clear, independent user isolation. |
| `tests/test_api_routes.py` | REST API | `GET /` service info, `GET /health` system status, user registration (`201` created, `409` conflict duplicate, `422` validation), user login (`200` token, `401` bad credentials, `403` banned user), room stats and top violators analytics. |
| `tests/test_gateway.py` | WebSocket Gateway | `ConnectionManager` client connection/disconnection, multi-client room mapping, broadcast message dissemination, sender exclusion, stale/broken socket auto-pruning. |
| `tests/test_worker.py` | Worker Pipeline | `StreamConsumer` payload parsing (direct dicts, nested JSON strings, fallback fields), batch moderation processing, DB log collection, Redis `XACK` acknowledgment, rate limit dispatch, `WorkerManager` health status inspection. |
| `tests/test_schemas.py` | Validation Schemas | Pydantic v2 validation rules: username length (3-64), password length (min 8), message limit (2000 chars), toxicity score bounds (0.0-1.0), analytics time intervals. |

### Concurrency & Load Testing

To simulate high-volume real-time chat traffic through the WebSocket gateway and into Redis Streams:

1. Ensure the server is running (`uvicorn app.main:app`).
2. Run the load testing script:

```bash
python testing/load_testing.py
```

Configuration in [testing/load_testing.py](file:///d:/certificate/AI%20projects/StreamGuard/testing/load_testing.py):
- `TOTAL_MESSAGES`: Total message payload count (default `1000`).
- `CONCURRENT_CLIENTS`: Parallel concurrent WebSocket connections (default `10`).
- Simulates realistic user behaviors: benign traffic, spam bursts, threat payloads, and rate limit triggers.

---

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

---

## WebSocket Protocol

```
1. Connect to ws://localhost:8000/ws/chat/{room_id}
2. Send JWT token as first message (plain text)
3. Receive: {"type": "system", "message": "Connected to room..."}
4. Send/receive chat messages (plain text, max 2000 chars)
5. Receive: {"type": "message", "username": "...", "content": "..."}
```

---

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

---

## Rate Limiting (Phase 5)

- **Sliding window**: Configurable (default: 10 seconds)
- **Threshold**: 3 violations within window → automatic blacklist
- **Blacklist TTL**: 1 hour (configurable)
- **Implementation**: Redis Sorted Sets with timestamp scores

---

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
│   │   ├── content_analyzer.py  # FastText ML classifier + Hugging Face Hub integration
│   │   ├── training_data.py     # Supervised multi-label training data
│   │   └── models/              # Pre-trained FastText binary model cache
│   ├── routes/
│   │   ├── __init__.py
│   │   ├── auth_routes.py    # POST /register, /login
│   │   └── analytics_routes.py  # GET trends, violators, room stats
│   └── worker/
│       ├── __init__.py
│       ├── stream_consumer.py   # Redis Stream XREADGROUP consumer
│       └── worker_manager.py    # Worker pool lifecycle + auto-restart
├── tests/                   # Automated Pytest Suite (57 tests)
│   ├── __init__.py
│   ├── conftest.py          # Isolated fixtures, SQLite in-memory, mock Redis
│   ├── test_nlp.py          # FastText ML toxicity classification & HF Hub integration tests
│   ├── test_auth.py         # JWT tokens & bcrypt authentication tests
│   ├── test_rate_limiter.py # Sliding window & blacklist tests
│   ├── test_schemas.py      # Pydantic v2 validation schema tests
│   ├── test_api_routes.py   # REST API route integration tests
│   ├── test_gateway.py      # WebSocket Gateway & ConnectionManager tests
│   └── test_worker.py       # StreamConsumer & WorkerManager tests
├── testing/
│   └── load_testing.py      # High-concurrency WebSocket load tester
├── alembic/
│   ├── env.py                # Async Alembic environment
│   ├── script.py.mako
│   └── versions/
│       └── 001_initial_schema.py
├── docker-compose.yml
├── Dockerfile
├── requirements.txt
├── alembic.ini
├── pytest.ini
├── .env.example
├── .dockerignore
└── .gitignore
```

---

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

<<<<<<< HEAD
---

## License
=======
>>>>>>> 27e716cb0f065125f0e3b2ae8548c996f678e693

