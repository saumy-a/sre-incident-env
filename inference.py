"""
Inference Script — SRE Incident Response Environment
=====================================================
STDOUT FORMAT (mandatory):
    [START] task=<task_name> env=<benchmark> model=<model_name>
    [STEP]  step=<n> action=<action_str> reward=<0.00> done=<true|false> error=<msg|null>
    [END]   success=<true|false> steps=<n> score=<score> rewards=<r1,r2,...,rn>

Environment variables:
    API_BASE_URL        LLM endpoint (default: Groq)
    MODEL_NAME          Model identifier
    HF_TOKEN / API_KEY  API key
    SRE_TASK            Task to run: easy | medium | hard (default: easy)
    ENV_BASE_URL        HF Space base URL (default: https://saumy-a-sre-incident-env.hf.space)
"""

import asyncio
import json
import os
import textwrap
from typing import List, Optional

from openai import OpenAI

from sre_incident_env.client import SreIncidentEnv
from sre_incident_env.models import SreIncidentAction, ActionType

# ── Configuration ─────────────────────────────────────────────────────────────
API_KEY      = os.getenv("HF_TOKEN") or os.getenv("API_KEY") or os.getenv("OPENAI_API_KEY")
API_BASE_URL = os.getenv("API_BASE_URL", "https://api.groq.com/openai/v1")
MODEL_NAME   = os.getenv("MODEL_NAME", "llama-3.1-8b-instant")
TASK_NAME    = os.getenv("SRE_TASK", "easy")
ENV_BASE_URL = os.getenv("ENV_BASE_URL", "https://saumy-a-sre-incident-env.hf.space")
BENCHMARK    = "sre_incident_env"
MAX_STEPS    = 25
TEMPERATURE  = 0.0
MAX_TOKENS   = 400  
SUCCESS_SCORE_THRESHOLD = 0.60

# ── Logging helpers ────────────────────────────────────────────────────────────
def log_start(task: str, env: str, model: str) -> None:
    print(f"[START] task={task} env={env} model={model}", flush=True)

def log_step(step: int, action: str, reward: float, done: bool, error: Optional[str]) -> None:
    error_val = error if error else "null"
    done_val = str(done).lower()
    action_clean = action.replace("\n", " ").replace("\r", "")[:120]
    print(
        f"[STEP] step={step} action={action_clean} reward={reward:.2f} done={done_val} error={error_val}",
        flush=True,
    )

def log_end(success: bool, steps: int, score: float, rewards: List[float]) -> None:
    rewards_str = ",".join(f"{r:.2f}" for r in rewards)
    print(
        f"[END] success={str(success).lower()} steps={steps} score={score:.3f} rewards={rewards_str}",
        flush=True,
    )

# ── Prompts ────────────────────────────────────────────────────────────────────
SYSTEM_PROMPT = textwrap.dedent("""
    You are an expert Site Reliability Engineer (SRE) responding to a production incident.

    At each step respond with a JSON object — no markdown, no explanation outside the JSON:
    {
      "action_type": "<one of: run_query, check_dashboard, list_alerts, get_deployment, rollback, scale_service, restart_service, toggle_feature, page_team, post_update, resolve, escalate, wait>",
      "target": "<target of the action>",
      "reasoning": "<brief explanation>"
    }

    Action guide:
    - list_alerts       → get all firing alerts (target: empty string)
    - check_dashboard   → view dashboard (target: dashboard name e.g. 'cdn-edge-health')
    - run_query         → metric/log query (target: query string)
    - get_deployment    → recent deploys (target: service or 'infra')
    - rollback          → roll back service (target: service name)
    - scale_service     → scale up (target: 'service:replicas' e.g. 'pgbouncer:6')
    - toggle_feature    → enable/disable flag (target: 'flag_name:on|off')
    - page_team         → page on-call team (target: team name e.g. 'db-team')
    - post_update       → status comms (target: your update message)
    - resolve           → close incident (target: resolution summary)

    Strategy:
    1. Start by listing alerts to understand scope.
    2. Investigate to find the ROOT CAUSE before fixing.
    3. Apply the correct remediation action.
    4. Page the right team if the issue is specialist (db-team, cdn-team).
    5. Post a status update.
    6. Call resolve once the fix is confirmed.
""").strip()


def obs_to_prompt(obs) -> str:
    alerts  = "\n".join(f"  - {a}" for a in obs.active_alerts) or "  (none)"
    status  = "\n".join(f"  {k}: {v}" for k, v in obs.system_status.items()) or "  (unknown)"
    timeline = "\n".join(f"  {t}" for t in obs.timeline[-5:]) or "  (no actions yet)"
    msg = (
        f"=== INCIDENT {obs.incident_id} | Severity: {obs.severity} ===\n"
        f"{obs.description}\n\n"
        f"LAST ACTION RESULT:\n{obs.action_result}\n\n"
        f"ACTIVE ALERTS:\n{alerts}\n\n"
        f"SYSTEM STATUS:\n{status}\n\n"
        f"RECENT TIMELINE (last 5):\n{timeline}\n\n"
        f"Step: {obs.step}"
    )
    if obs.hint:
        msg += f"\n\n{obs.hint}"
    return msg


def parse_action(content: str) -> SreIncidentAction:
    content = content.strip()
    if content.startswith("```"):
        content = content.split("```")[1]
        if content.startswith("json"):
            content = content[4:]
    content = content.strip()
    data = json.loads(content)
    return SreIncidentAction(
        action_type=ActionType(data["action_type"]),
        target=data.get("target", ""),
        reasoning=data.get("reasoning", ""),
    )


# ── Single episode runner ──────────────────────────────────────────────────────
async def run_episode(task_id: str, client: OpenAI, env) -> dict:
    rewards: List[float] = []
    steps_taken = 0
    score = 0.0
    success = False

    log_start(task=task_id, env=BENCHMARK, model=MODEL_NAME)

    messages = [{"role": "system", "content": SYSTEM_PROMPT}]

    try:
        result = await env.reset()
        obs = result.observation if hasattr(result, "observation") else result

        for step in range(1, MAX_STEPS + 1):
            done = getattr(obs, "done", False) or getattr(result, "done", False)
            if done:
                break

            user_msg = obs_to_prompt(obs)
            messages.append({"role": "user", "content": user_msg})

            try:
                completion = client.chat.completions.create(
                    model=MODEL_NAME,
                    messages=messages,
                    temperature=TEMPERATURE,
                    max_tokens=MAX_TOKENS,
                )
                content = (completion.choices[0].message.content or "").strip()
                messages.append({"role": "assistant", "content": content})
            except Exception as exc:
                content = '{"action_type": "wait", "target": "", "reasoning": "LLM error"}'
                messages.append({"role": "assistant", "content": content})
                print(f"[DEBUG] LLM error step {step}: {exc}", flush=True)

            error_msg = None
            try:
                action = parse_action(content)
            except Exception as exc:
                error_msg = str(exc)[:80]
                action = SreIncidentAction(action_type=ActionType.WAIT, target="")

            result = await env.step(action)
            obs = result.observation if hasattr(result, "observation") else result
            reward = getattr(result, "reward", 0.0) or 0.0
            done   = getattr(result, "done", False)

            rewards.append(reward)
            steps_taken = step

            action_str = f"{action.action_type.value}(target={action.target[:40]!r})"
            log_step(step=step, action=action_str, reward=reward, done=done, error=error_msg)

            if done:
                break

        raw_score = sum(rewards)
        score = min(max(raw_score, 0.0), 1.0)
        success = score >= SUCCESS_SCORE_THRESHOLD

    except Exception as exc:
        print(f"[DEBUG] Episode error: {exc}", flush=True)

    finally:
        try:
            await env.close()
        except Exception as e:
            print(f"[DEBUG] env.close() error: {e}", flush=True)
        log_end(success=success, steps=steps_taken, score=score, rewards=rewards)

    return {"task": task_id, "score": score, "success": success, "steps": steps_taken}


# ── Main ───────────────────────────────────────────────────────────────────────
async def main() -> None:
    if not API_KEY:
        raise RuntimeError(
            "No API key found. Set HF_TOKEN, API_KEY, or OPENAI_API_KEY environment variable."
        )

    client = OpenAI(base_url=API_BASE_URL, api_key=API_KEY)

    tasks = os.getenv("SRE_TASKS", TASK_NAME).split(",")  # e.g. "easy,medium,hard"

    for task_id in tasks:
        task_id = task_id.strip()
        # Connect directly to HF Space — no Docker needed
        async with SreIncidentEnv(base_url=ENV_BASE_URL) as env:
            await run_episode(task_id, client, env)


if __name__ == "__main__":
    asyncio.run(main())