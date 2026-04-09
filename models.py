# Copyright (c) Meta Platforms, Inc. and affiliates.
# All rights reserved.
#
# This source code is licensed under the BSD-style license found in the
# LICENSE file in the root directory of this source tree.

"""
Data models for the SRE Incident Response Environment.
Typed Pydantic models for Action, Observation, and State.
"""

import datetime
from enum import Enum
from typing import Any, Dict, List, Optional

from openenv.core.env_server.types import Action, Observation
from pydantic import BaseModel, Field


class ActionType(str, Enum):
    # Investigation
    RUN_QUERY = "run_query"
    CHECK_DASHBOARD = "check_dashboard"
    LIST_ALERTS = "list_alerts"
    GET_DEPLOYMENT = "get_deployment"
    # Remediation
    ROLLBACK = "rollback"
    SCALE_SERVICE = "scale_service"
    RESTART_SERVICE = "restart_service"
    TOGGLE_FEATURE = "toggle_feature"
    # Communication
    PAGE_TEAM = "page_team"
    POST_UPDATE = "post_update"
    # Resolution
    RESOLVE = "resolve"
    ESCALATE = "escalate"
    WAIT = "wait"


class SreIncidentAction(Action):
    """Action taken by the SRE agent during incident response."""

    action_type: ActionType = Field(
        ...,
        description=(
            "Type of action. One of: run_query, check_dashboard, list_alerts, "
            "get_deployment, rollback, scale_service, restart_service, "
            "toggle_feature, page_team, post_update, resolve, escalate, wait"
        ),
    )
    target: str = Field(
        default="",
        description=(
            "Target of the action:\n"
            "  run_query       → query string\n"
            "  check_dashboard → dashboard name\n"
            "  get_deployment  → service name\n"
            "  rollback        → service name\n"
            "  scale_service   → 'service:replicas' e.g. 'api:10'\n"
            "  restart_service → service name\n"
            "  toggle_feature  → 'flag_name:on|off'\n"
            "  page_team       → team name\n"
            "  post_update     → update message\n"
            "  resolve         → resolution summary\n"
            "  escalate        → escalation reason\n"
            "  list_alerts     → filter or empty for all\n"
            "  wait            → ignored\n"
        ),
    )
    reasoning: str = Field(
        default="",
        description="Agent's reasoning for this action (optional, earns small reward bonus)",
    )


class SreIncidentObservation(Observation):
    """What the SRE agent observes after each action."""

    # Incident context
    incident_id: str = Field(default="", description="Unique incident ID")
    title: str = Field(default="", description="Short incident title")
    severity: str = Field(default="P2", description="Severity: P1/P2/P3/P4")
    description: str = Field(default="", description="Full incident description")

    # Feedback from last action
    action_result: str = Field(default="", description="Output of the last action")

    # Environment state
    system_status: Dict[str, Any] = Field(
        default_factory=dict, description="Current service statuses"
    )
    active_alerts: List[str] = Field(
        default_factory=list, description="Currently firing alerts"
    )
    timeline: List[str] = Field(
        default_factory=list, description="Chronological action log"
    )

    # Episode info
    step: int = Field(default=0, description="Current step number")
    resolved: bool = Field(
        default=False, description="Was incident correctly resolved?"
    )
    hint: str = Field(default="", description="Progressive hint (may be empty)")


class GraderResult(BaseModel):
    """Result from the /grader endpoint."""

    task_id: str
    score: float = Field(..., description="Score strictly between 0 and 1")
    passed: bool
    details: Dict[str, Any] = Field(default_factory=dict)
    graded_at: str = Field(
        default_factory=lambda: datetime.datetime.utcnow().isoformat() + "Z"
    )
