# Copyright (c) Meta Platforms, Inc. and affiliates.
# All rights reserved.
#
# This source code is licensed under the BSD-style license found in the
# LICENSE file in the root directory of this source tree.

"""
SRE Incident Response Environment — Core Logic.
Implements reset(), step(), state() per the OpenEnv spec.
"""

from uuid import uuid4

from openenv.core.env_server.interfaces import Environment
from openenv.core.env_server.types import State

try:
    from ..models import ActionType, SreIncidentAction, SreIncidentObservation
    from .tasks import TASKS, get_task
except ImportError:
    from models import ActionType, SreIncidentAction, SreIncidentObservation
    from server.tasks import TASKS, get_task


# Reward constants
R_ROOT_CAUSE = 0.20
R_REMEDIATION = 0.35
R_COMMS = 0.10
R_PAGE = 0.10
R_RESOLVE = 0.15
R_REASONING = 0.02
R_WRONG = -0.05
R_TIMEOUT = -0.20
R_EARLY_RESOLVE = -0.15
R_WRONG_PAGE = -0.05


class SreIncidentEnvironment(Environment):
    """
    SRE Incident Response OpenEnv environment.
    One episode = one incident scenario (easy / medium / hard).
    """

    SUPPORTS_CONCURRENT_SESSIONS: bool = True

    def __init__(self, default_task_id: str | None = None):
        self._default_task_id = default_task_id or "easy"
        self._task = None
        self._task_id = self._default_task_id
        self._state = State(episode_id=str(uuid4()), step_count=0)
        self._timeline: list[str] = []
        self._root_cause_found = False
        self._remediation_applied = False
        self._comms_posted = False
        self._team_paged = False
        self._wrong_actions = 0
        self._cumulative_reward = 0.0

    def reset(self, task_id: str | None = None) -> SreIncidentObservation:
        chosen = task_id or self._default_task_id
        self._task = get_task(chosen)
        self._task_id = chosen
        self._state = State(episode_id=str(uuid4()), step_count=0)
        self._timeline = []
        self._root_cause_found = False
        self._remediation_applied = False
        self._comms_posted = False
        self._team_paged = False
        self._wrong_actions = 0
        self._cumulative_reward = 0.0

        return SreIncidentObservation(
            incident_id=self._state.episode_id[:8].upper(),
            title=self._task.title,
            severity=self._task.severity,
            description=self._task.description,
            action_result="Environment ready. Start investigating the incident.",
            system_status=self._make_status(),
            active_alerts=self._get_alerts(),
            timeline=[],
            step=0,
            done=False,
            reward=0.0,
            resolved=False,
            hint="",
        )

    def step(self, action: SreIncidentAction) -> SreIncidentObservation:  # type: ignore[override]
        assert self._task is not None, "Call reset() before step()"

        self._state.step_count += 1
        step = self._state.step_count
        atype = action.action_type
        target = action.target or ""
        reward = 0.0
        done = False
        resolved = False
        action_result = ""

        # Reasoning bonus
        if action.reasoning.strip():
            reward += R_REASONING

        # Timeout
        if step >= self._task.max_steps and atype != ActionType.RESOLVE:
            reward += R_TIMEOUT
            done = True
            action_result = (
                f"⏰ MAX STEPS ({self._task.max_steps}) reached. "
                "Incident not resolved in time."
            )
            self._cumulative_reward += reward
            self._timeline.append(f"Step {step}: TIMEOUT reward={reward:+.3f}")
            return self._build_obs(action_result, reward, done, resolved)

        # Dispatch
        if atype == ActionType.RESOLVE:
            if self._remediation_applied:
                reward += R_RESOLVE
                done = True
                resolved = True
                action_result = (
                    f"✅ Incident resolved! Steps: {step} | "
                    f"Total reward: {self._cumulative_reward + reward:.3f}"
                )
            else:
                reward += R_EARLY_RESOLVE
                action_result = "⚠️ Cannot resolve — correct fix not applied yet."

        elif atype == ActionType.PAGE_TEAM:
            text, _, _ = self._task.get_tool_response("page_team", target)
            action_result = text
            if self._task.needs_page and not self._team_paged:
                if self._task.correct_page_team.lower() in target.lower():
                    reward += R_PAGE
                    self._team_paged = True
                else:
                    reward += R_WRONG_PAGE
                    self._wrong_actions += 1

        elif atype == ActionType.POST_UPDATE:
            text, _, _ = self._task.get_tool_response("post_update", target)
            action_result = text
            if not self._comms_posted:
                reward += R_COMMS
                self._comms_posted = True
            else:
                action_result += " (duplicate — no extra reward)"

        elif atype in (
            ActionType.RUN_QUERY,
            ActionType.CHECK_DASHBOARD,
            ActionType.LIST_ALERTS,
            ActionType.GET_DEPLOYMENT,
        ):
            text, reveals_rc, _ = self._task.get_tool_response(atype.value, target)
            action_result = text
            if reveals_rc and not self._root_cause_found:
                reward += R_ROOT_CAUSE
                self._root_cause_found = True
                action_result += "\n\n🔍 ROOT CAUSE IDENTIFIED."

        elif atype in (
            ActionType.ROLLBACK,
            ActionType.SCALE_SERVICE,
            ActionType.RESTART_SERVICE,
            ActionType.TOGGLE_FEATURE,
        ):
            text, _, is_fix = self._task.get_tool_response(atype.value, target)
            action_result = text
            if is_fix and not self._remediation_applied:
                reward += R_REMEDIATION
                self._remediation_applied = True
                action_result += "\n\n✅ CORRECT REMEDIATION APPLIED."
            elif not is_fix:
                reward += R_WRONG
                self._wrong_actions += 1

        elif atype == ActionType.ESCALATE:
            text, _, _ = self._task.get_tool_response("escalate", target)
            action_result = text

        elif atype == ActionType.WAIT:
            action_result = "Waited one step. No change."
            reward += R_WRONG

        self._cumulative_reward += reward
        self._timeline.append(
            f"Step {step}: [{atype.value}] target='{target[:25]}' reward={reward:+.3f}"
        )

        return self._build_obs(action_result, reward, done, resolved)

    @property
    def state(self) -> State:
        return self._state

    # ── helpers ──────────────────────────────────────────────────────────────

    def _build_obs(self, action_result, reward, done, resolved):
        hint = ""
        if self._task:
            step = self._state.step_count
            hints = self._task.hints
            if step >= 5 and not self._root_cause_found and len(hints) >= 1:
                hint = f"💡 {hints[0]}"
            elif step >= 10 and not self._remediation_applied and len(hints) >= 2:
                hint = f"💡 {hints[1]}"

        return SreIncidentObservation(
            incident_id=self._state.episode_id[:8].upper(),
            title=self._task.title if self._task else "",
            severity=self._task.severity if self._task else "P2",
            description=self._task.description if self._task else "",
            action_result=action_result,
            system_status=self._make_status(),
            active_alerts=self._get_alerts(),
            timeline=list(self._timeline),
            step=self._state.step_count,
            done=done,
            reward=reward,
            resolved=resolved,
            hint=hint,
        )

    def _make_status(self):
        if not self._task or self._remediation_applied:
            return {"all_services": "✅ HEALTHY"}
        t = self._task.title.lower()
        if "payment" in t:
            return {"payment-api": "🔴 18% 5xx errors", "other_services": "🟢 OK"}
        if "database" in t:
            return {
                "order-service": "🔴 503s",
                "inventory-service": "🔴 503s",
                "pgbouncer": "🔴 98% pool saturation",
            }
        if "cdn" in t:
            return {
                "cdn-edge": "🔴 cache miss storm (4%)",
                "eu-west-1": "🔴 unavailable",
                "ap-southeast-1": "🔴 unavailable",
                "us-east-1": "🟡 40% errors",
            }
        return {}

    def _get_alerts(self):
        if not self._task or self._remediation_applied:
            return []
        t = self._task.title.lower()
        if "payment" in t:
            return [
                "payment-api.http_5xx_rate > 0.10",
                "payment-api.p99_latency > 2000ms",
            ]
        if "database" in t:
            return [
                "order-service.http_503_rate > 0.30",
                "pgbouncer.pool_saturation > 0.95",
            ]
        if "cdn" in t:
            return [
                "global.p99_latency > 4000ms",
                "eu-west-1.availability < 0.01",
                "cdn-edge.cache_hit_ratio < 0.05",
            ]
        return []


# ── Grader ────────────────────────────────────────────────────────────────────


def grade_episode(env: SreIncidentEnvironment) -> dict:
    """Score a completed episode. Returns scores strictly between 0 and 1."""
    task = env._task
    score = 0.0
    breakdown = {}

    breakdown["root_cause_identified"] = 0.20 if env._root_cause_found else 0.0
    score += breakdown["root_cause_identified"]

    breakdown["remediation_applied"] = 0.35 if env._remediation_applied else 0.0
    score += breakdown["remediation_applied"]

    breakdown["comms_posted"] = 0.10 if env._comms_posted else 0.0
    score += breakdown["comms_posted"]

    if task and task.needs_page:
        breakdown["correct_team_paged"] = 0.10 if env._team_paged else 0.0
        score += breakdown["correct_team_paged"]
    else:
        breakdown["correct_team_paged"] = "N/A"

    breakdown["resolved"] = 0.15 if env._remediation_applied else 0.0
    score += breakdown["resolved"]

    eff = max(0.0, 0.10 - env._wrong_actions * 0.02)
    breakdown["efficiency_bonus"] = round(eff, 3)
    score += eff

    final_score = round(min(max(score, 0.01), 0.999), 4)

    return {
        "task_id": env._task_id,
        "total_steps": env._state.step_count,
        "wrong_actions": env._wrong_actions,
        "score": final_score,
        "breakdown": breakdown,
        "passed": score >= 0.60,
    }
