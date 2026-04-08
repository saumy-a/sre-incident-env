---
title: SRE Incident Response Environment
emoji: 🚨
colorFrom: red
colorTo: yellow
sdk: docker
app_port: 7860
pinned: false
tags:
  - openenv
  - reinforcement-learning
  - sre
  - incident-response
---

# 🚨 SRE Incident Response Environment

An [OpenEnv](https://github.com/meta-pytorch/OpenEnv)-compliant reinforcement learning environment where an AI agent acts as a Site Reliability Engineer (SRE) responding to real production incidents.

The agent must investigate alerts, identify root causes, apply correct remediations, communicate status, and resolve incidents — exactly as a human SRE would.

---

## Environment Description

Production incidents are one of the most high-stakes, time-pressured tasks in software engineering. This environment simulates the full SRE incident response loop:

1. **Observe** — read alerts, dashboards, deployment history
2. **Investigate** — query metrics, correlate signals, find root cause
3. **Remediate** — apply the correct fix (rollback, scale, toggle flag)
4. **Communicate** — page the right team, post a status update
5. **Resolve** — close the incident once fixed

The environment rewards efficient, correct decision-making and penalizes wrong actions, wasted steps, and premature resolution.

---

## Action Space

Actions are `SreIncidentAction` Pydantic objects with 3 fields:

| Field | Type | Description |
|---|---|---|
| `action_type` | `ActionType` (enum) | What to do (see table below) |
| `target` | `str` | Target of the action |
| `reasoning` | `str` | Agent's reasoning (optional, earns small bonus) |

### Action Types

| Action | Target | Description |
|---|---|---|
| `list_alerts` | empty or filter keyword | List all currently firing alerts |
| `check_dashboard` | dashboard name | Pull a named dashboard snapshot |
| `run_query` | metric/log query string | Execute a metrics or log query |
| `get_deployment` | service name | Fetch recent deployment info |
| `rollback` | service name | Roll back a service to previous version |
| `scale_service` | `service:replicas` e.g. `pgbouncer:6` | Scale a service up or down |
| `restart_service` | service name | Restart pods/instances |
| `toggle_feature` | `flag_name:on\|off` | Enable or disable a feature flag |
| `page_team` | team name e.g. `db-team` | Page the on-call team |
| `post_update` | status update message | Post a comms update to stakeholders |
| `resolve` | resolution summary | Mark incident as resolved |
| `escalate` | escalation reason | Escalate severity or team |
| `wait` | — | Do nothing (penalized) |

---

## Observation Space

Observations are `SreIncidentObservation` Pydantic objects:

| Field | Type | Description |
|---|---|---|
| `incident_id` | `str` | Unique incident identifier |
| `title` | `str` | Short incident title |
| `severity` | `str` | P1 / P2 / P3 / P4 |
| `description` | `str` | Full incident description |
| `action_result` | `str` | Output of the last action taken |
| `system_status` | `dict` | Current service health map |
| `active_alerts` | `list[str]` | Currently firing alert names |
| `timeline` | `list[str]` | Chronological action log |
| `step` | `int` | Current step number |
| `done` | `bool` | Whether the episode is over |
| `reward` | `float` | Reward for the last step |
| `resolved` | `bool` | Whether incident was correctly resolved |
| `hint` | `str` | Progressive hint (appears after step 5/10) |

---

## Tasks

Three tasks of increasing difficulty, each simulating a real production incident:

### Task 1 — Easy: Payment API 500s after Deploy
- **Scenario:** Payment API error rate spikes to 18% immediately after a deployment
- **Root cause:** Bad code in new deployment (NullPointerException in DiscountEngine)
- **Correct fix:** `rollback` → `payment-api`
- **Max steps:** 15
- **Expected score:** ~0.90

### Task 2 — Medium: Database Connection Pool Exhaustion
- **Scenario:** Three services (order, inventory, notification) all returning 503s
- **Root cause:** PgBouncer connection pool saturated (98%), shared by all services
- **Correct fix:** `scale_service` → `pgbouncer:6` + page `db-team`
- **Max steps:** 20
- **Expected score:** ~0.85–1.00

### Task 3 — Hard: CDN Misconfiguration with Noisy Alerts
- **Scenario:** Global P99 latency 8x above baseline, 23 alerts firing — most are symptoms
- **Root cause:** CDN routing rule update bypasses cache (4% hit rate vs 85% baseline)
- **Correct fix:** `toggle_feature` → `cdn_new_routing:off` + page `cdn-team`
- **Max steps:** 25
- **Expected score:** ~0.75–1.00

---

## Reward Function

Rewards are given per step, providing partial progress signals throughout the episode:

| Signal | Reward |
|---|---|
| Root cause identified | +0.20 |
| Correct remediation applied | +0.35 |
| Status update posted | +0.10 |
| Correct team paged (if required) | +0.10 |
| Incident resolved correctly | +0.15 |
| Efficiency bonus (0 wrong actions) | +0.10 |
| Non-empty reasoning provided | +0.02 per step |
| Wrong/wasteful action | −0.05 each |
| Timeout (max steps reached) | −0.20 |
| Resolve called before fix applied | −0.15 |

**Score range:** 0.0 – 1.0. Pass threshold: ≥ 0.60.

---

## Baseline Scores

Model: `llama-3.1-8b-instant` via Groq

| Task | Score | Steps | Wrong Actions | Pass |
|---|---|---|---|---|
| easy | 0.9000 | 5 | 0 | ✅ |
| medium | 1.0000 | — | 0 | ✅ |
| hard | 1.0000 | — | 0 | ✅ |

---

## Setup & Usage

### Install

```bash
git clone https://github.com/meta-pytorch/OpenEnv.git
cd OpenEnv
uv sync --all-extras

cd envs/sre_incident_env
uv sync
```

### Run server locally

```bash
uv run server --host 0.0.0.0 --port 8000
```

Open the web UI: http://localhost:8000/web

### Run baseline inference

```bash
export OPENAI_API_KEY=your_key
export OPENAI_BASE_URL=https://api.groq.com/openai/v1  # optional, for Groq

uv run python baseline.py --model llama-3.1-8b-instant
uv run python baseline.py --task easy    # single task
```

### Docker

```bash
# Build
docker build -t sre-incident-env:latest -f server/Dockerfile .

# Run
docker run -p 7860:7860 sre-incident-env:latest

# Health check
curl http://localhost:7860/health
```

### Use from Python

```python
# Sync usage
from sre_incident_env import SreIncidentEnv, SreIncidentAction, ActionType

with SreIncidentEnv(base_url="http://localhost:7860").sync() as env:
    result = env.reset()
    result = env.step(SreIncidentAction(
        action_type=ActionType.LIST_ALERTS,
        target="",
        reasoning="Get full picture of what is firing."
    ))
    print(result.observation.action_result)
```

---

## 📁 Project Structure

```
sre_incident_env/
├── models.py                          # Action, Observation Pydantic models
├── client.py                          # SreIncidentEnv HTTP/WebSocket client
├── baseline.py                        # Baseline inference script
├── openenv.yaml                       # OpenEnv manifest
├── README.md                          # This file
└── server/
    ├── app.py                         # FastAPI app via create_app()
    ├── sre_incident_env_environment.py # Core environment logic + grader
    ├── tasks.py                        # 3 task scenarios (easy/medium/hard)
    └── Dockerfile                      # Container definition
```

---

## Environment Motivation

Incident response is a real, high-value task that humans do every day under pressure. Training AI agents on this task has direct practical value:

- **Faster MTTR** (Mean Time To Resolution)
- **Consistent process** — agent always checks alerts before acting
- **Knowledge transfer** — encode SRE best practices into agent behavior
- **24/7 coverage** — agents can triage while humans are paged

Unlike toy environments, every scenario here reflects patterns from real production incidents.