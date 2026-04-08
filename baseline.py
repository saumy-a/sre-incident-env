"""
SRE Incident Response — Baseline Inference Script
Uses the OpenAI API client to run a model against all 3 tasks.
Reads credentials from environment variables.

Usage:
    export OPENAI_API_KEY=sk-...
    python baseline.py                   # runs all 3 tasks
    python baseline.py --task easy       # single task
    python baseline.py --model gpt-4o   # different model
"""

import argparse
import json
import os
import sys

from openai import OpenAI

# ── Import env directly (no server needed) ───────────────────────────────────
try:
    from server.sre_incident_env_environment import SreIncidentEnvironment, grade_episode
    from models import SreIncidentAction, ActionType
except ImportError:
    sys.path.insert(0, os.path.dirname(__file__))
    from server.sre_incident_env_environment import SreIncidentEnvironment, grade_episode
    from models import SreIncidentAction, ActionType


SYSTEM_PROMPT = """You are an expert Site Reliability Engineer (SRE) responding to a production incident.

You will receive an incident description and the result of your last action.
Your job is to investigate, identify the root cause, apply the correct fix, communicate status, and resolve the incident.

At each step you must respond with a JSON object with exactly these fields:
{
  "action_type": "<one of: run_query, check_dashboard, list_alerts, get_deployment, rollback, scale_service, restart_service, toggle_feature, page_team, post_update, resolve, escalate, wait>",
  "target": "<target of the action, e.g. service name, query string, team name>",
  "reasoning": "<brief explanation of why you are taking this action>"
}

Action guide:
- list_alerts     → get all firing alerts (target: empty or filter keyword)
- check_dashboard → view a dashboard (target: dashboard name e.g. 'cdn-edge-health')
- run_query       → execute a metric/log query (target: query string)
- get_deployment  → check recent deploys (target: service name or 'infra')
- rollback        → roll back a service (target: service name)
- scale_service   → scale a service (target: 'service:replicas' e.g. 'pgbouncer:6')
- toggle_feature  → enable/disable a feature flag (target: 'flag_name:on|off')
- page_team       → page on-call team (target: team name e.g. 'db-team', 'cdn-team')
- post_update     → post a status update (target: your update message)
- resolve         → mark incident resolved (target: resolution summary)
- escalate        → escalate severity (target: reason)

Always start by listing alerts to understand the scope.
Look for the root cause before attempting fixes.
Page the right team if the problem requires specialist knowledge.
Post a status update before resolving.
Call resolve once the correct fix is applied.

Respond ONLY with the JSON object — no markdown, no explanation outside the JSON."""


def obs_to_prompt(obs) -> str:
    """Convert observation to a user message for the LLM."""
    alerts = "\n".join(f"  - {a}" for a in obs.active_alerts) or "  (none)"
    status = "\n".join(f"  {k}: {v}" for k, v in obs.system_status.items()) or "  (unknown)"
    timeline = "\n".join(f"  {t}" for t in obs.timeline[-5:]) or "  (no actions yet)"

    msg = f"""=== INCIDENT: {obs.incident_id} | Severity: {obs.severity} ===
{obs.description}

LAST ACTION RESULT:
{obs.action_result}

ACTIVE ALERTS:
{alerts}

SYSTEM STATUS:
{status}

RECENT TIMELINE (last 5 steps):
{timeline}

Step: {obs.step}"""

    if obs.hint:
        msg += f"\n\n{obs.hint}"

    return msg


def parse_action(content: str) -> SreIncidentAction:
    """Parse LLM JSON response into SreIncidentAction."""
    # Strip markdown code fences if present
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


def run_episode(task_id: str, model: str, client: OpenAI, verbose: bool = True) -> dict:
    """Run one full episode and return the grade."""
    env = SreIncidentEnvironment(default_task_id=task_id)
    obs = env.reset(task_id=task_id)

    messages = [{"role": "system", "content": SYSTEM_PROMPT}]

    if verbose:
        print(f"\n{'='*60}")
        print(f"TASK: {task_id.upper()} — {obs.title}")
        print(f"{'='*60}")
        print(obs.description)
        print()

    for step in range(50):  # hard cap
        user_msg = obs_to_prompt(obs)
        messages.append({"role": "user", "content": user_msg})

        # Call the model
        response = client.chat.completions.create(
            model=model,
            messages=messages,
            temperature=0.0,
            max_tokens=300,
        )
        content = response.choices[0].message.content
        messages.append({"role": "assistant", "content": content})

        # Parse action
        try:
            action = parse_action(content)
        except Exception as e:
            if verbose:
                print(f"  Step {step+1}: ⚠️  Parse error: {e} | Raw: {content[:80]}")
            action = SreIncidentAction(action_type=ActionType.WAIT, target="")

        if verbose:
            print(f"  Step {step+1}: [{action.action_type.value}] → {action.target[:40]}")
            if action.reasoning:
                print(f"           reasoning: {action.reasoning[:70]}")

        obs = env.step(action)

        if verbose and obs.action_result:
            # Show first line of result
            first_line = obs.action_result.split("\n")[0]
            print(f"           result: {first_line[:70]}")

        if obs.done:
            break

    grade = grade_episode(env)

    if verbose:
        print(f"\n── GRADE ──────────────────────────────")
        print(f"  Score:        {grade['score']:.4f}  ({'PASS ✅' if grade['passed'] else 'FAIL ❌'})")
        print(f"  Steps taken:  {grade['total_steps']}")
        print(f"  Wrong actions:{grade['wrong_actions']}")
        print(f"  Breakdown:")
        for k, v in grade["breakdown"].items():
            print(f"    {k}: {v}")

    return grade


def main():
    parser = argparse.ArgumentParser(description="SRE Incident Response Baseline")
    parser.add_argument("--task", choices=["easy", "medium", "hard", "all"], default="all")
    parser.add_argument("--model", default="gpt-4o-mini")
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args()

    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        print("ERROR: OPENAI_API_KEY environment variable not set.")
        sys.exit(1)

    client = OpenAI(api_key=api_key)
    tasks = ["easy", "medium", "hard"] if args.task == "all" else [args.task]
    results = {}

    for task_id in tasks:
        grade = run_episode(task_id, args.model, client, verbose=not args.quiet)
        results[task_id] = grade

    # Summary
    print(f"\n{'='*60}")
    print(f"BASELINE SUMMARY  (model: {args.model})")
    print(f"{'='*60}")
    print(f"{'Task':<10} {'Score':>8} {'Steps':>7} {'Wrong':>7} {'Pass':>6}")
    print(f"{'-'*42}")
    for task_id, g in results.items():
        print(
            f"{task_id:<10} {g['score']:>8.4f} {g['total_steps']:>7} "
            f"{g['wrong_actions']:>7} {'✅' if g['passed'] else '❌':>6}"
        )
    print()

    # Save results
    out_path = os.path.join(os.path.dirname(__file__), "outputs", "evals", "baseline_results.json")
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w") as f:
        json.dump({"model": args.model, "results": results}, f, indent=2)
    print(f"Results saved to: {out_path}")


if __name__ == "__main__":
    main()
