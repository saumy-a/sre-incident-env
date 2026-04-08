# Copyright (c) Meta Platforms, Inc. and affiliates.
# All rights reserved.
#
# This source code is licensed under the BSD-style license found in the
# LICENSE file in the root directory of this source tree.

"""SRE Incident Response Environment Client."""

from typing import Dict

from openenv.core import EnvClient
from openenv.core.client_types import StepResult
from openenv.core.env_server.types import State

from .models import SreIncidentAction, SreIncidentObservation


class SreIncidentEnv(EnvClient[SreIncidentAction, SreIncidentObservation, State]):
    """
    Client for the SRE Incident Response environment.

    Usage (sync):
        with SreIncidentEnv(base_url="http://localhost:8000").sync() as env:
            result = env.reset()
            result = env.step(SreIncidentAction(
                action_type="list_alerts",
                target="",
                reasoning="Get a full picture of what is firing."
            ))
            print(result.observation.action_result)

    Usage (async):
        async with SreIncidentEnv(base_url="http://localhost:8000") as env:
            result = await env.reset()
            result = await env.step(SreIncidentAction(action_type="list_alerts", target=""))
    """

    def _step_payload(self, action: SreIncidentAction) -> Dict:
        return {
            "action_type": action.action_type.value,
            "target": action.target,
            "reasoning": action.reasoning,
        }

    def _parse_result(self, payload: Dict) -> StepResult[SreIncidentObservation]:
        obs_data = payload.get("observation", {})
        observation = SreIncidentObservation(
            incident_id=obs_data.get("incident_id", ""),
            title=obs_data.get("title", ""),
            severity=obs_data.get("severity", "P2"),
            description=obs_data.get("description", ""),
            action_result=obs_data.get("action_result", ""),
            system_status=obs_data.get("system_status", {}),
            active_alerts=obs_data.get("active_alerts", []),
            timeline=obs_data.get("timeline", []),
            step=obs_data.get("step", 0),
            done=payload.get("done", False),
            reward=payload.get("reward", 0.0),
            resolved=obs_data.get("resolved", False),
            hint=obs_data.get("hint", ""),
        )
        return StepResult(
            observation=observation,
            reward=payload.get("reward", 0.0),
            done=payload.get("done", False),
        )

    def _parse_state(self, payload: Dict) -> State:
        return State(
            episode_id=payload.get("episode_id", ""),
            step_count=payload.get("step_count", 0),
        )
