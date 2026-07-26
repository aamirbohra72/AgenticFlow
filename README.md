# Agentic Order Flow (v2)

Multi-agent customer service system with a Django orchestrator, Flask specialist agents, RabbitMQ message transport, Neon Postgres, and Upstash Redis.

## Architecture

```
Client / Dashboard
       │  API_KEY + X-Request-ID
       ▼
Django Orchestrator ──publish task + correlation_id──► RabbitMQ
       │                                                    │
       │◄──────── results (+ DLQ on poison) ────────────────┤
       ▼                                                    ▼
 Neon Postgres / Redis                              Flask Agents
```

**Interview talking point:** Agents never call each other over HTTP. RabbitMQ is the A2A transport. Django publishes tasks; agents publish results; Django synthesizes the answer. v2 adds API-key auth, correlation IDs, DLQs, idempotent result handling, and metrics.

## Prerequisites

- Python 3.11+
- Node.js 18+ (for TurboRepo local dev)
- Docker Desktop (RabbitMQ, or full stack)

## Quick start (host development)

### 1. Configure environment

```bash
cp .env.example .env
# Edit .env with Neon, Upstash, Mistral, and API_KEY
```

### 2. Start RabbitMQ only

```bash
docker compose up -d rabbitmq
```

Management UI: http://localhost:15672 (guest / guest)

### 3. Install dependencies

```bash
python -m venv .venv
.venv\Scripts\activate        # Windows
# source .venv/bin/activate   # macOS/Linux

pip install -r apps/orchestrator/requirements.txt
pip install -r agents/order_agent/requirements.txt
pip install -r agents/inventory_agent/requirements.txt
pip install -r agents/refund_agent/requirements.txt
pip install -r agents/escalation_agent/requirements.txt
npm install
```

### 4. Migrate + seed

```bash
npm run migrate
npm run seed
```

### 5. Run all app processes

```bash
npm run dev
```

Uses `runserver --noreload` so only **one** orchestrator result consumer attaches to RabbitMQ.

- Dashboard: http://localhost:8000/dashboard/
- Orchestrator: http://localhost:8000
- Agents: 5001–5004

## Production-like local run (Docker Compose)

Brings up RabbitMQ + Django orchestrator + all 4 agents:

```bash
cp .env.example .env   # fill credentials; keep API_KEY
docker compose up --build
```

Then:

- API / dashboard: http://localhost:8000
- RabbitMQ UI: http://localhost:15672
- Agents: http://localhost:5001 … 5004

Stop host `npm run dev` first so ports do not conflict.

## Auth headers

Protected routes (`/api/query/`, `/api/conversations/`, `/api/metrics/`, reprocess) require:

```bash
# Preferred
-H "X-API-Key: dev-api-key-change-me"

# Or
-H "Authorization: Api-Key dev-api-key-change-me"
```

`GET /api/health/` stays **public** (no key). Rate limit defaults to 30 req/min per key (`RATE_LIMIT_PER_MINUTE`).

Dashboard embeds the server `API_KEY` for local demo; change `API_KEY` in `.env` for anything beyond local use.

## Example API requests

### Order status

```bash
curl -X POST http://localhost:8000/api/query/ \
  -H "Content-Type: application/json" \
  -H "X-API-Key: dev-api-key-change-me" \
  -d "{\"query\": \"Where is my order #1234?\"}"
```

### Escalation trigger (#3333)

```bash
curl -X POST http://localhost:8000/api/query/ \
  -H "Content-Type: application/json" \
  -H "X-API-Key: dev-api-key-change-me" \
  -d "{\"query\": \"I need a refund for order #3333, shoes are defective\"}"
```

### Metrics / health

```bash
curl http://localhost:8000/api/health/
curl -H "X-API-Key: dev-api-key-change-me" http://localhost:8000/api/metrics/
```

Without an API key, `/api/query/` returns **401**.

## Messaging v2 reliability

| Feature | Behavior |
|---|---|
| `correlation_id` | Set on every task; echoed on results |
| Schema | `schema_version`, `correlation_id`, `attempt` |
| DLQ | `*.tasks.dlq` and `orchestrator.results.dlq` after max attempts |
| Idempotency | Redis `processed:{correlation_id}` skips duplicate result updates |
| Failed status | Timeouts/errors set `ConversationLog.status=failed` + `error_message` |

## Inspect DLQs / recreate queues after upgrade

In RabbitMQ UI → Queues, look for `order.tasks.v2.dlq`, `inventory.tasks.v2.dlq`, `refund.tasks.v2.dlq`, `escalation.tasks.v2.dlq`, `orchestrator.results.v2.dlq`. Or:

```bash
docker exec agentic-rabbitmq rabbitmqctl list_queues name messages consumers
```

Expect **1 consumer** per live task/results queue under Compose (one replica per service).

**Windows tip:** if queries fail with `PRECONDITION_FAILED` / timeouts after many restarts, leftover `python app.py` / `runserver` processes may still be attached. Stop `npm run dev`, then in PowerShell:

```powershell
Get-CimInstance Win32_Process -Filter "name='python.exe'" |
  Where-Object { $_.CommandLine -match 'manage\.py runserver|app\.py' } |
  ForEach-Object { Stop-Process -Id $_.ProcessId -Force }
npm run dev
```

If you see `PRECONDITION_FAILED` for queue args, consumers recreate queues with the
named DLX `agentic.dlx`. Restart services after a broker wipe:

```bash
docker compose down -v && docker compose up -d rabbitmq
npm run dev
```

## Tests

```bash
npm test
# or
cd apps/orchestrator && python -m pytest
cd agents/refund_agent && python -m pytest tests -q
```

## Validation checklist

- [ ] `GET /api/health/` → 200 without API key
- [ ] `POST /api/query/` without key → 401
- [ ] Order #1234 with key → `order_agent`, tracking present
- [ ] Escalate #3333 with key → `was_escalated: true`, agents include escalation
- [ ] Dashboard shows `request_id` / latency; metrics button loads counters
- [ ] `npm test` / pytest passes
- [ ] `docker compose up --build` starts full stack; RabbitMQ shows 1 consumer per queue

## API surface

| Method | Path | Auth | Purpose |
|---|---|---|---|
| `GET` | `/api/health/` | public | Postgres + RabbitMQ + Redis + result consumer |
| `GET` | `/api/metrics/` | API key | Intent/escalation/timeout counters + latency |
| `POST` | `/api/query/` | API key | Run orchestration pipeline |
| `GET` | `/api/conversations/` | API key | Recent conversations |
| `GET` | `/api/conversations/{id}/` | API key | Detail + Redis trace |
| `POST` | `/api/conversations/{id}/reprocess/` | API key | Replay pipeline |

## Project structure

```
AgenticOrderFlow/
├── docker-compose.yml          # RabbitMQ + orchestrator + 4 agents
├── apps/orchestrator/          # Django + DRF
└── agents/
    ├── common/                 # messaging + env
    ├── order_agent/
    ├── inventory_agent/
    ├── refund_agent/
    └── escalation_agent/
```

## Escalation rules

1. Refund `confidence_score < 0.6`, OR
2. Replacement proposed but inventory out of stock

## Demo data

- Orders: #1234 shipped, #5678 delivered (refund-eligible), #3333 escalation (OOS shoes)
- Seed: `npm run seed`
- Admin: http://localhost:8000/admin/

## Environment variables

See [`.env.example`](.env.example). Never commit `.env`.

Key v2 vars: `API_KEY`, `RATE_LIMIT_PER_MINUTE`, `LOG_LEVEL`, `MESSAGE_MAX_ATTEMPTS`.
