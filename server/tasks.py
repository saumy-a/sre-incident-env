"""
SRE Incident Response — Task Scenarios
Three real-world incidents: easy → medium → hard.
"""
from __future__ import annotations
from dataclasses import dataclass, field


@dataclass
class ToolResponse:
    keywords: list[str]
    response: str
    reveals_root_cause: bool = False
    is_correct_fix: bool = False


@dataclass
class Task:
    title: str
    severity: str
    description: str
    difficulty: str
    max_steps: int
    tool_responses: dict[str, list[ToolResponse]]
    correct_remediation_action: str
    correct_remediation_target: str
    needs_page: bool = False
    correct_page_team: str = ""
    hints: list[str] = field(default_factory=list)

    def get_tool_response(self, action_type: str, target: str) -> tuple[str, bool, bool]:
        responses = self.tool_responses.get(action_type, [])
        for tr in responses:
            if any(kw.lower() in target.lower() for kw in tr.keywords):
                return tr.response, tr.reveals_root_cause, tr.is_correct_fix
        return f"[{action_type}] No relevant data found for target='{target}'.", False, False


# ── TASK 1: Easy — bad deploy causing 500s ────────────────────────────────────

TASK_EASY = Task(
    title="Payment API elevated 500s after deploy",
    severity="P2",
    difficulty="easy",
    max_steps=15,
    description=(
        "INCIDENT · Severity P2\n"
        "PagerDuty: payment-api HTTP 500 error rate spiked to 18% at 14:32 UTC.\n"
        "Customer checkout is impacted. Deployment pipeline ran at 14:28 UTC.\n"
        "Goal: investigate, find root cause, apply correct fix, post a status update."
    ),
    correct_remediation_action="rollback",
    correct_remediation_target="payment-api",
    needs_page=False,
    hints=[
        "Check recent deployments — timing correlates with the error spike.",
        "Run an error-rate query to confirm scope before fixing.",
    ],
    tool_responses={
        "list_alerts": [ToolResponse(
            keywords=["", "all", "payment", "alert"],
            response=(
                "🔴 FIRING ALERTS:\n"
                "  • payment-api.http_5xx_rate > 0.10  [14:32 UTC]\n"
                "  • payment-api.p99_latency > 2000ms  [14:33 UTC]\n"
                "No other services affected."
            ),
        )],
        "get_deployment": [ToolResponse(
            keywords=["payment"],
            response=(
                "Recent deployments for payment-api:\n"
                "  v2.3.1 → v2.3.2  at 14:28 UTC  by ci-bot\n"
                "  Changelog: 'Add new discount-engine integration'\n"
                "  Previous stable: v2.3.1 (no incidents)"
            ),
            reveals_root_cause=True,
        )],
        "run_query": [
            ToolResponse(
                keywords=["error", "500", "5xx", "payment"],
                response=(
                    "http_requests_total{service='payment-api',status=~'5..'}\n"
                    "Result: error_rate=18.2%  (baseline <0.5%)\n"
                    "Spike onset: 14:28 UTC — matches deployment exactly.\n"
                    "Error: NullPointerException in DiscountEngine.apply() — new code path."
                ),
                reveals_root_cause=True,
            ),
            ToolResponse(
                keywords=["latency", "p99"],
                response="p99 latency for payment-api: 2340ms (SLO: <500ms). Elevated since 14:28 UTC.",
            ),
        ],
        "check_dashboard": [ToolResponse(
            keywords=["payment", "api"],
            response=(
                "Dashboard: payment-api-overview\n"
                "  HTTP 5xx: 18%  p99: 2340ms  RPS: 420/s\n"
                "  Error source: /v1/checkout endpoint"
            ),
        )],
        "rollback": [ToolResponse(
            keywords=["payment"],
            response=(
                "✅ Rollback: payment-api v2.3.2 → v2.3.1\n"
                "All 8 pods healthy. HTTP 5xx rate: 0.3% (baseline). Incident resolved."
            ),
            is_correct_fix=True,
        )],
        "post_update": [ToolResponse(
            keywords=[""],
            response="✅ Status update posted to #incidents and status page.",
        )],
        "scale_service": [ToolResponse(
            keywords=["payment"],
            response="Scaled payment-api. ERROR RATE UNCHANGED — scaling doesn't fix application bugs.",
        )],
        "restart_service": [ToolResponse(
            keywords=["payment"],
            response="Pods restarted. Error rate returns to 18% — bug is in new code, not runtime.",
        )],
    },
)


# ── TASK 2: Medium — DB connection pool exhaustion ────────────────────────────

TASK_MEDIUM = Task(
    title="Database connection pool exhaustion — cascade 503s",
    severity="P2",
    difficulty="medium",
    max_steps=20,
    description=(
        "INCIDENT · Severity P2\n"
        "order-service, inventory-service, and notification-service are all returning 503s.\n"
        "Alert fired at 09:15 UTC. No recent deployments. DB team not yet engaged.\n"
        "Goal: find shared root cause, page the right team, apply short-term fix, post update."
    ),
    correct_remediation_action="scale_service",
    correct_remediation_target="pgbouncer",
    needs_page=True,
    correct_page_team="db-team",
    hints=[
        "Multiple services failing suggests a shared upstream dependency.",
        "Check database connection pool metrics — PgBouncer is the pooler.",
    ],
    tool_responses={
        "list_alerts": [ToolResponse(
            keywords=["", "all", "alert"],
            response=(
                "🔴 FIRING ALERTS (09:15 UTC):\n"
                "  • order-service.http_503_rate > 0.30\n"
                "  • inventory-service.http_503_rate > 0.30\n"
                "  • notification-service.http_503_rate > 0.20\n"
                "  • postgres-primary.connection_wait_time > 5s\n"
                "  • pgbouncer.pool_saturation > 0.95\n"
                "Note: DB alerts precede service alerts by ~30s."
            ),
        )],
        "run_query": [
            ToolResponse(
                keywords=["connection", "pool", "postgres", "pgbouncer", "db"],
                response=(
                    "pgbouncer pool_saturation: 98% (max_pool_size=50, active=49)\n"
                    "postgres active_connections: 490/500\n"
                    "Connection wait queue: 312 requests\n"
                    "Root cause: connection pool exhausted — all services share this pool."
                ),
                reveals_root_cause=True,
            ),
            ToolResponse(
                keywords=["error", "503", "service"],
                response="order-service 503 rate: 34%. Error: 'could not obtain connection from pool'",
            ),
        ],
        "check_dashboard": [
            ToolResponse(
                keywords=["database", "db", "postgres", "pgbouncer"],
                response=(
                    "Dashboard: database-health\n"
                    "  PgBouncer saturation: 98%\n"
                    "  Postgres connections: 490/500\n"
                    "  Queue depth: 312\n"
                    "  Slow queries: 0 (not a query issue)"
                ),
                reveals_root_cause=True,
            ),
            ToolResponse(
                keywords=["service", "overview"],
                response=(
                    "Dashboard: services-overview\n"
                    "  order-service:        🔴 34% errors\n"
                    "  inventory-service:    🔴 31% errors\n"
                    "  notification-service: 🟡 22% errors\n"
                    "  payment-service:      🟢 OK"
                ),
            ),
        ],
        "scale_service": [
            ToolResponse(
                keywords=["pgbouncer"],
                response=(
                    "✅ Scaled pgbouncer: 2 → 6 replicas. Pool size increased to 150.\n"
                    "Connection queue draining...\n"
                    "  order-service: 34% → 1.2% ✅\n"
                    "  inventory-service: 31% → 0.8% ✅\n"
                    "Short-term fix applied. DB team must investigate root cause."
                ),
                is_correct_fix=True,
            ),
            ToolResponse(
                keywords=["order", "inventory", "notification"],
                response="Scaled app service. More replicas = MORE DB connections needed. Error rate WORSENED.",
            ),
        ],
        "page_team": [
            ToolResponse(
                keywords=["db", "database", "dba"],
                response="✅ DB team paged via PagerDuty. On-call acknowledged in 2 min.",
            ),
            ToolResponse(
                keywords=["backend", "platform", "infra", "sre"],
                response="⚠️ Backend team paged, but DB team owns this issue. Also page db-team.",
            ),
        ],
        "post_update": [ToolResponse(keywords=[""], response="✅ Status update posted.")],
        "get_deployment": [ToolResponse(
            keywords=[""],
            response="No recent deployments. Last deploy: 6 hours ago. Issue is resource-based.",
        )],
        "rollback": [ToolResponse(
            keywords=[""],
            response="No recent deployments to roll back. Issue is DB connection pool saturation.",
        )],
    },
)


# ── TASK 3: Hard — CDN misconfiguration with noisy alerts ────────────────────

TASK_HARD = Task(
    title="CDN misconfiguration causing global latency spike",
    severity="P1",
    difficulty="hard",
    max_steps=25,
    description=(
        "INCIDENT · Severity P1\n"
        "Global P99 latency is 8x above baseline. EU and APAC are unavailable.\n"
        "NA has ~40% error rate. 23 alerts firing — many are symptoms, not root cause.\n"
        "CDN routing rules were updated 20 minutes ago by the infra team.\n"
        "Goal: find the TRUE root cause amid noisy alerts, page cdn-team,\n"
        "disable the feature flag cdn_new_routing, and post executive comms."
    ),
    correct_remediation_action="toggle_feature",
    correct_remediation_target="cdn_new_routing:off",
    needs_page=True,
    correct_page_team="cdn-team",
    hints=[
        "Not all 23 alerts are root cause — look for what changed 20 min ago.",
        "CDN cache hit ratio dropped from 85% to 4% — that's the smoking gun.",
        "Feature flag cdn_new_routing was enabled with the routing rule change.",
    ],
    tool_responses={
        "list_alerts": [ToolResponse(
            keywords=["", "all", "alert"],
            response=(
                "🔴 FIRING ALERTS (23 total):\n"
                "  • global.p99_latency > 4000ms             [CRITICAL]\n"
                "  • eu-west-1.availability < 0.01            [CRITICAL]\n"
                "  • ap-southeast-1.availability < 0.01       [CRITICAL]\n"
                "  • us-east-1.error_rate > 0.40              [HIGH]\n"
                "  • cdn-edge.cache_hit_ratio < 0.05          [HIGH] ← unusual\n"
                "  • cdn-edge.origin_request_rate > 10000     [HIGH] ← unusual\n"
                "  • database.connection_pool > 0.80          [MED]  ← downstream symptom\n"
                "  • auth-service.latency > 500ms             [MED]  ← downstream symptom\n"
                "  • ... (+15 more downstream alerts)\n"
                "CDN cache hit ratio < 5% is very abnormal (baseline: 85%)."
            ),
        )],
        "check_dashboard": [
            ToolResponse(
                keywords=["cdn", "edge", "routing"],
                response=(
                    "Dashboard: cdn-edge-health\n"
                    "  Cache hit ratio: 4%  (baseline 85%) ← ANOMALY\n"
                    "  Origin request rate: 11,200/s  (baseline 800/s) ← ANOMALY\n"
                    "  Routing rule version: v2.1.0  (changed 20 min ago from v2.0.3)\n"
                    "  Edge nodes: all healthy\n"
                    "Analysis: v2.1.0 rules are sending ALL requests to origin, bypassing cache."
                ),
                reveals_root_cause=True,
            ),
            ToolResponse(
                keywords=["global", "overview"],
                response=(
                    "Global overview: ALL services affected. Common upstream: CDN edge layer.\n"
                    "EU: 0% | APAC: 0% | NA: 60% availability. Latency: 8x baseline."
                ),
            ),
        ],
        "get_deployment": [ToolResponse(
            keywords=["cdn", "infra", "routing", "edge"],
            response=(
                "Recent changes (last 30 min):\n"
                "  CDN routing rules v2.0.3 → v2.1.0  at 22:41 UTC  by infra-bot\n"
                "  Feature flag cdn_new_routing: OFF → ON  at 22:41 UTC\n"
                "No application deployments in last 2 hours."
            ),
            reveals_root_cause=True,
        )],
        "run_query": [
            ToolResponse(
                keywords=["cdn", "cache", "origin", "routing"],
                response=(
                    "CDN metrics since 22:41 UTC:\n"
                    "  cache_hit_ratio: 85% → 4% (step change at routing update)\n"
                    "  origin_rps: 800 → 11,200 (14x increase)\n"
                    "Conclusion: new routing rules bypass cache, flooding origin servers."
                ),
                reveals_root_cause=True,
            ),
            ToolResponse(
                keywords=["latency", "p99", "global"],
                response="Global p99 latency: 4,200ms (SLO: 500ms). All regions elevated since 22:41 UTC.",
            ),
        ],
        "toggle_feature": [
            ToolResponse(
                keywords=["cdn_new_routing", "cdn_routing", "new_routing"],
                response=(
                    "✅ Feature flag cdn_new_routing → OFF\n"
                    "CDN routing reverting to v2.0.3...\n"
                    "Cache warming: 4% → 78% (3 min)\n"
                    "Global latency: 4200ms → 380ms ✅\n"
                    "EU availability: 0% → 99.8% ✅\n"
                    "APAC availability: 0% → 99.6% ✅\n"
                    "NA errors: 40% → 0.4% ✅  Incident resolved."
                ),
                is_correct_fix=True,
            ),
            ToolResponse(
                keywords=["maintenance", "debug"],
                response="Flag toggled. No impact — this flag is unrelated to CDN routing.",
            ),
        ],
        "page_team": [
            ToolResponse(
                keywords=["cdn", "edge", "infra"],
                response="✅ CDN/Infra team paged. Senior engineer acknowledged immediately.",
            ),
            ToolResponse(
                keywords=["backend", "sre", "platform"],
                response="⚠️ Backend team paged. They confirm this is a CDN issue — page cdn-team.",
            ),
        ],
        "post_update": [ToolResponse(keywords=[""], response="✅ Executive update posted to #p1-bridge and status page.")],
        "rollback": [ToolResponse(
            keywords=[""],
            response="No CDN artifact to roll back. Use toggle_feature to disable cdn_new_routing instead.",
        )],
        "escalate": [ToolResponse(
            keywords=[""],
            response="Escalated to P1 war room. VP Engineering joined. Still need to apply the fix.",
        )],
    },
)


TASKS: dict[str, Task] = {
    "easy":   TASK_EASY,
    "medium": TASK_MEDIUM,
    "hard":   TASK_HARD,
}


def get_task(task_id: str) -> Task:
    if task_id not in TASKS:
        raise ValueError(f"Unknown task_id '{task_id}'. Valid: {list(TASKS.keys())}")
    return TASKS[task_id]
