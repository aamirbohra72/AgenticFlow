# Agentic Order Flow

Multi-agent customer service system with a Django orchestrator, Flask specialist agents, RabbitMQ message transport, Neon Postgres, and Upstash Redis.

## Architecture

```
Customer → Django (POST /api/query/)
              ↓ publish task
         RabbitMQ queue (order|inventory|refund|escalation).tasks
              ↓ consume
         Flask Agent (CrewAI or AutoGen)
              ↓ query Postgres / reason
              ↓ publish result
         RabbitMQ orchestrator.results
              ↓ consume (background thread)
         Django → update Postgres + Redis trace → return response
```

**Key interview talking point:** Agents never call each other over HTTP. RabbitMQ is the A2A (agent-to-agent) transport. Django publishes tasks; agents publish results; Django synthesizes the final answer.

## Prerequisites

- Python 3.11+
- Node.js 18+ (for TurboRepo)
- Docker Desktop (for RabbitMQ)

## Quick start

### 1. Clone and configure environment

```bash
cp .env.example .env
# Edit .env with your Neon, Upstash, and Mistral credentials
```

### 2. Start RabbitMQ

```bash
docker compose up -d
```

RabbitMQ management UI: http://localhost:15672 (guest / guest)

### 3. Install Python dependencies

Create a virtualenv at the repo root (recommended):

```bash
python -m venv .venv
.venv\Scripts\activate        # Windows
# source .venv/bin/activate   # macOS/Linux

pip install -r apps/orchestrator/requirements.txt
pip install -r agents/order_agent/requirements.txt
pip install -r agents/inventory_agent/requirements.txt
pip install -r agents/refund_agent/requirements.txt
pip install -r agents/escalation_agent/requirements.txt
```

### 4. Database setup

```bash
cd apps/orchestrator
python manage.py migrate
python manage.py seed_demo_data
cd ../..
```

### 5. Run all services (one command)

```bash
npm install
npm run dev
```

This starts via TurboRepo:
- Django orchestrator on http://localhost:8000
- Order agent on http://localhost:5001
- Inventory agent on http://localhost:5002
- Refund agent on http://localhost:5003
- Escalation agent on http://localhost:5004

### 6. Or run services individually

```bash
# Terminal 1 — RabbitMQ (if not already running)
docker compose up

# Terminal 2 — Django
cd apps/orchestrator && python manage.py runserver

# Terminal 3 — Order agent
cd agents/order_agent && python app.py

# Terminal 4 — Inventory agent
cd agents/inventory_agent && python app.py

# Terminal 5 — Refund agent
cd agents/refund_agent && python app.py

# Terminal 6 — Escalation agent
cd agents/escalation_agent && python app.py
```

## Example API requests

### Order status (no escalation)

```bash
curl -X POST http://localhost:8000/api/query/ \
  -H "Content-Type: application/json" \
  -d "{\"query\": \"Where is my order #1234?\"}"
```

### Inventory check

```bash
curl -X POST http://localhost:8000/api/query/ \
  -H "Content-Type: application/json" \
  -d "{\"query\": \"Are Wireless Headphones in stock?\"}"
```

### Refund request (may escalate if low confidence)

```bash
curl -X POST http://localhost:8000/api/query/ \
  -H "Content-Type: application/json" \
  -d "{\"query\": \"I want a refund for order #5678, item was defective\"}"
```

### Escalation trigger example

Order #3333 (Running Shoes) is outside the 14-day apparel refund window. The refund agent proposes a replacement, but Running Shoes are out of stock — triggering escalation:

```bash
curl -X POST http://localhost:8000/api/query/ \
  -H "Content-Type: application/json" \
  -d "{\"query\": \"I need a refund for order #3333, shoes are defective\"}"
```

## Project structure

```
AgenticOrderFlow/
├── docker-compose.yml          # RabbitMQ
├── apps/orchestrator/          # Django + DRF orchestrator
│   └── core/
│       ├── models.py           # Order, InventoryItem, RefundPolicy, ConversationLog
│       ├── rabbitmq_client.py  # A2A publish / result consumer
│       ├── redis_client.py     # Live trace in Upstash
│       ├── intent.py           # Keyword intent classification
│       ├── escalation.py       # Escalation rules
│       └── views.py            # POST /api/query/
└── agents/
    ├── common/                 # Shared messaging + env helpers
    ├── order_agent/            # CrewAI — Order Status Specialist
    ├── inventory_agent/        # CrewAI — Inventory Specialist
    ├── refund_agent/           # CrewAI — Refund Policy Specialist
    └── escalation_agent/       # AutoGen — conflict resolution
```

## RabbitMQ queues

| Queue | Direction |
|---|---|
| `order.tasks` | Django → Order Agent |
| `inventory.tasks` | Django → Inventory Agent |
| `refund.tasks` | Django → Refund Agent |
| `escalation.tasks` | Django → Escalation Agent |
| `orchestrator.results` | All agents → Django |

## Escalation rules

Django routes to the Escalation Agent when:
1. Refund agent `confidence_score < 0.6`, OR
2. Refund agent proposes a replacement but inventory is out of stock

The Escalation Agent runs a 2–3 turn AutoGen conversation between `CustomerIntent` and `PolicyResolver` to produce a final answer.

## Admin & demo data

- Django admin: http://localhost:8000/admin/
- Seed demo data: `python manage.py seed_demo_data`
- Demo orders: #1234 (shipped), #5678 (delivered), #9012 (placed), #3333 (escalation scenario)
- Running Shoes are out of stock (triggers escalation scenarios)

## Environment variables

See [`.env.example`](.env.example) for the full list. Never commit `.env` to version control.

## Health checks

```bash
curl http://localhost:5001/health   # order agent
curl http://localhost:5002/health   # inventory agent
curl http://localhost:5003/health   # refund agent
curl http://localhost:5004/health   # escalation agent
```
