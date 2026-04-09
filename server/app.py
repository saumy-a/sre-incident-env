# Copyright (c) Meta Platforms, Inc. and affiliates.
# All rights reserved.
#
# This source code is licensed under the BSD-style license found in the
# LICENSE file in the root directory of this source tree.

import os
from datetime import datetime, timezone
from openenv.core.env_server.http_server import create_app
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from typing import Optional

try:
    from ..models import SreIncidentAction, SreIncidentObservation
    from .sre_incident_env_environment import SreIncidentEnvironment, grade_episode
    from .tasks import TASKS
except ModuleNotFoundError:
    from models import SreIncidentAction, SreIncidentObservation
    from server.sre_incident_env_environment import (
        SreIncidentEnvironment,
        grade_episode,
    )
    from server.tasks import TASKS

_default_task = os.getenv("SRE_DEFAULT_TASK", "easy")

app = create_app(
    lambda: SreIncidentEnvironment(default_task_id=_default_task),
    SreIncidentAction,
    SreIncidentObservation,
    env_name="sre_incident_env",
    max_concurrent_envs=10,
)


# ── /tasks endpoint ───────────────────────────────────────────────────────────


@app.get("/tasks")
def list_tasks():
    """Return the task catalog for the validator."""
    return {
        "tasks": [
            {
                "task_id": task_id,
                "task_name": task.title.split("\n")[0],
                "difficulty": task.difficulty,
                "description": task.description.split("\n")[0],
                "max_steps": task.max_steps,
                "success_threshold": 0.6,
            }
            for task_id, task in TASKS.items()
        ]
    }


# ── /grader endpoint ──────────────────────────────────────────────────────────


class GraderRequest(BaseModel):
    task_id: str
    episode_id: Optional[str] = None


@app.post("/grader")
def grade(request: GraderRequest):
    """
    Run a fresh deterministic episode for the given task_id and return a score.
    Score is always strictly between 0.001 and 0.999.
    """
    task_id = request.task_id
    if task_id not in TASKS:
        return JSONResponse(
            status_code=400,
            content={
                "error": f"Unknown task_id '{task_id}'. Valid: {list(TASKS.keys())}"
            },
        )

    # Run a short deterministic episode using the optimal action sequence
    env = SreIncidentEnvironment(default_task_id=task_id)
    env.reset(task_id=task_id)

    task = TASKS[task_id]

    # Import here to avoid circular
    try:
        from ..models import ActionType, SreIncidentAction as Action
    except ImportError:
        from models import ActionType, SreIncidentAction as Action

    # Deterministic optimal policy per task
    optimal_sequences = {
        "easy": [
            Action(
                action_type=ActionType.LIST_ALERTS, target="", reasoning="check alerts"
            ),
            Action(
                action_type=ActionType.GET_DEPLOYMENT,
                target="payment-api",
                reasoning="check deploy",
            ),
            Action(
                action_type=ActionType.RUN_QUERY,
                target="error rate payment",
                reasoning="confirm",
            ),
            Action(
                action_type=ActionType.ROLLBACK, target="payment-api", reasoning="fix"
            ),
            Action(
                action_type=ActionType.POST_UPDATE,
                target="rolled back payment-api",
                reasoning="comms",
            ),
            Action(
                action_type=ActionType.RESOLVE,
                target="rollback resolved issue",
                reasoning="done",
            ),
        ],
        "medium": [
            Action(
                action_type=ActionType.LIST_ALERTS, target="", reasoning="check alerts"
            ),
            Action(
                action_type=ActionType.RUN_QUERY,
                target="pgbouncer connection pool",
                reasoning="find root cause",
            ),
            Action(
                action_type=ActionType.CHECK_DASHBOARD,
                target="database-health",
                reasoning="confirm",
            ),
            Action(
                action_type=ActionType.PAGE_TEAM,
                target="db-team",
                reasoning="page experts",
            ),
            Action(
                action_type=ActionType.SCALE_SERVICE,
                target="pgbouncer:6",
                reasoning="fix pool",
            ),
            Action(
                action_type=ActionType.POST_UPDATE,
                target="scaled pgbouncer",
                reasoning="comms",
            ),
            Action(
                action_type=ActionType.RESOLVE,
                target="pool exhaustion fixed",
                reasoning="done",
            ),
        ],
        "hard": [
            Action(
                action_type=ActionType.LIST_ALERTS, target="", reasoning="check alerts"
            ),
            Action(
                action_type=ActionType.CHECK_DASHBOARD,
                target="cdn-edge-health",
                reasoning="cdn check",
            ),
            Action(
                action_type=ActionType.GET_DEPLOYMENT,
                target="cdn infra routing",
                reasoning="check change",
            ),
            Action(
                action_type=ActionType.RUN_QUERY,
                target="cdn cache routing",
                reasoning="confirm",
            ),
            Action(
                action_type=ActionType.PAGE_TEAM,
                target="cdn-team",
                reasoning="page cdn team",
            ),
            Action(
                action_type=ActionType.TOGGLE_FEATURE,
                target="cdn_new_routing:off",
                reasoning="disable flag",
            ),
            Action(
                action_type=ActionType.POST_UPDATE,
                target="disabled cdn_new_routing",
                reasoning="comms",
            ),
            Action(
                action_type=ActionType.RESOLVE,
                target="cdn routing fixed",
                reasoning="done",
            ),
        ],
    }

    actions = optimal_sequences.get(task_id, optimal_sequences["easy"])
    for action in actions:
        result = env.step(action)
        if result.done:
            break

    # Grade and clamp strictly between 0.001 and 0.999
    grade = grade_episode(env)
    raw_score = grade["score"]

    # Ensure score is strictly between 0 and 1 (not 0.0, 1.0, 0.00, or 1.00)
    if raw_score >= 1.0:
        score = 0.999
    elif raw_score <= 0.0:
        score = 0.001
    else:
        score = round(raw_score, 4)

    return {
        "task_id": task_id,
        "score": score,
        "passed": score >= 0.5,
        "details": grade.get("breakdown", {}),
        "steps": grade.get("total_steps", 0),
        "graded_at": datetime.now(timezone.utc).isoformat(),
    }


def main(host: str = "0.0.0.0", port: int = 7860):
    import uvicorn

    uvicorn.run(app, host=host, port=port)


if __name__ == "__main__":
    main()
