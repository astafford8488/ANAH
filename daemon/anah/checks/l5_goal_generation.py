"""L5 — Goal Generation & Exploration.

Triggered when task queue is empty or on-demand.
Full LLM reasoning when API key is available, local pattern-based fallback otherwise.
"""

import json
import logging
import os
import time
from dataclasses import dataclass

from anah.db import Database
from anah.task_queue import TaskQueue
from anah.pattern_analyzer import PatternAnalyzer

logger = logging.getLogger("anah.l5")

SYSTEM_PROMPT = """You are ANAH's L5 Goal Generation engine — the autonomous reasoning layer of an agent hierarchy system.

Your role: analyze the current system state and generate actionable goals (tasks) that improve system health, performance, and capabilities.

Context about the hierarchy:
- L1 (Operational Survival): network, filesystem, compute monitoring (30s heartbeat)
- L2 (Persistent State Safety): config integrity, DB integrity, backups (5min)
- L3 (Task Ecosystem Health): external API health, integration pings (15min)
- L4 (Performance & Impact): completion rates, error rates, throughput, latency (2min)
- L5 (Goal Generation): YOU — pattern analysis, self-improvement, autonomous task creation

You will receive a context summary containing:
- Current hierarchy status
- Health score
- Queue statistics
- Detected patterns and anomalies
- Recent failures

IMPORTANT DEDUPLICATION RULE:
You will also receive a list of recently generated goals. DO NOT propose goals that are similar to recent ones.
A goal is "similar" if it addresses the same topic, metric, or system area as a recent goal — even with different wording.
Always generate NOVEL goals that cover different aspects of the system.

Your job: Generate 1-3 specific, actionable tasks. Each task must have:
- title: prefixed with handler type (health_report:, self_diagnostic:, cleanup:, echo:)
- priority: 0-9 (higher = more urgent)
- description: what this task should accomplish
- reasoning: why this task is valuable right now

Respond with valid JSON array of tasks. Example:
[
  {
    "title": "self_diagnostic: investigate network latency spikes",
    "priority": 5,
    "description": "Network connectivity checks showing high variance. Run full diagnostic to identify root cause.",
    "reasoning": "Pattern analyzer detected 3x latency increase in network checks over the last 15 minutes."
  }
]

If the system is healthy and idle, generate exploratory or maintenance tasks. Never return an empty array — there's always something to improve."""

USER_PROMPT_TEMPLATE = """Current system state:

{context_json}

Recently generated goals (DO NOT repeat these or similar topics):
{recent_goals}

Based on this state, generate 1-3 actionable tasks that are DIFFERENT from the recent goals above. Respond with JSON only."""


@dataclass
class GeneratedGoal:
    title: str
    priority: int
    description: str
    reasoning: str
    source: str  # "llm" or "pattern_fallback"


def _titles_similar(a: str, b: str, threshold: float = 0.5) -> bool:
    """Check if two goal titles are similar using word overlap ratio."""
    words_a = set(a.lower().split())
    words_b = set(b.lower().split())
    # Remove common prefixes like "health_report:", "self_diagnostic:"
    stop = {"health_report:", "self_diagnostic:", "cleanup:", "echo:", "a", "the", "and", "of", "for", "to", "in"}
    words_a -= stop
    words_b -= stop
    if not words_a or not words_b:
        return False
    overlap = len(words_a & words_b)
    return overlap / min(len(words_a), len(words_b)) >= threshold


def _dedup_goals(new_goals: list[GeneratedGoal], recent_titles: list[str]) -> list[GeneratedGoal]:
    """Filter out goals that are too similar to recently generated ones."""
    filtered = []
    for goal in new_goals:
        is_dup = any(_titles_similar(goal.title, rt) for rt in recent_titles)
        if is_dup:
            logger.info(f"L5 dedup: skipping similar goal '{goal.title}'")
        else:
            filtered.append(goal)
    return filtered


async def generate_goals_llm(context: dict, recent_goals_text: str = "None") -> list[GeneratedGoal]:
    """Generate goals using Claude API."""
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        return []

    try:
        import httpx
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                "https://api.anthropic.com/v1/messages",
                headers={
                    "x-api-key": api_key,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
                },
                json={
                    "model": "claude-sonnet-4-20250514",
                    "max_tokens": 1024,
                    "system": SYSTEM_PROMPT,
                    "messages": [
                        {"role": "user", "content": USER_PROMPT_TEMPLATE.format(
                            context_json=json.dumps(context, indent=2),
                            recent_goals=recent_goals_text,
                        )}
                    ],
                },
            )

        if resp.status_code != 200:
            logger.warning(f"Claude API returned {resp.status_code}: {resp.text[:200]}")
            return []

        data = resp.json()
        content = data["content"][0]["text"]

        # Parse JSON from response (handle markdown code blocks)
        if "```json" in content:
            content = content.split("```json")[1].split("```")[0]
        elif "```" in content:
            content = content.split("```")[1].split("```")[0]

        tasks = json.loads(content.strip())
        return [
            GeneratedGoal(
                title=t["title"],
                priority=t.get("priority", 3),
                description=t.get("description", ""),
                reasoning=t.get("reasoning", ""),
                source="llm",
            )
            for t in tasks
        ]
    except Exception as e:
        logger.error(f"LLM goal generation failed: {e}")
        return []


async def generate_goals_fallback(context: dict, patterns: list) -> list[GeneratedGoal]:
    """Generate goals from pattern analysis (no LLM needed)."""
    goals = []

    # Priority 1: Address detected patterns with suggested actions
    for pattern in patterns:
        if pattern.suggested_action:
            severity_priority = {"critical": 7, "warning": 5, "info": 3}.get(pattern.severity, 3)
            goals.append(GeneratedGoal(
                title=pattern.suggested_action,
                priority=severity_priority,
                description=pattern.description,
                reasoning=f"Pattern detected: {pattern.title} ({pattern.category})",
                source="pattern_fallback",
            ))

    # Priority 2: If healthy and idle, generate proactive tasks
    if not goals and context.get("health_score", 0) >= 95:
        queue = context.get("queue", {})
        if queue.get("queued", 0) == 0 and queue.get("running", 0) == 0:
            goals.append(GeneratedGoal(
                title="health_report: proactive system assessment",
                priority=2,
                description="System is healthy and idle. Generate a comprehensive health report for monitoring.",
                reasoning=f"All systems healthy ({context.get('health_score')}% pass rate), queue empty — good time for assessment.",
                source="pattern_fallback",
            ))

    # Priority 3: Periodic self-improvement suggestions
    if not goals:
        completed = context.get("queue", {}).get("completed", 0)
        if completed > 0 and completed % 10 == 0:
            goals.append(GeneratedGoal(
                title="self_diagnostic: milestone check at {completed} tasks",
                priority=2,
                description=f"System has completed {completed} tasks. Run diagnostic to verify system integrity.",
                reasoning=f"Milestone reached: {completed} tasks completed.",
                source="pattern_fallback",
            ))

    return goals


@dataclass
class CheckResult:
    name: str
    passed: bool
    duration_ms: float
    message: str
    details: dict | None = None


async def run_goal_generation(db: Database, queue: TaskQueue) -> tuple[list[GeneratedGoal], dict]:
    """Run full L5 goal generation cycle. Returns (goals, context)."""
    analyzer = PatternAnalyzer(db, queue)
    context = await analyzer.get_context_summary()
    patterns = await analyzer.analyze()

    # Fetch recent goals for deduplication (last 20, excluding dismissed)
    recent_goals = await db.get_recent_goals(limit=20)
    recent_titles = [g["title"] for g in recent_goals if g.get("status") != "dismissed"]
    recent_goals_text = "\n".join(
        f"- [{g.get('status', '?')}] {g['title']}" for g in recent_goals[:15]
    ) if recent_goals else "None (first generation cycle)"

    # Try LLM first, fall back to pattern analysis
    goals = await generate_goals_llm(context, recent_goals_text)
    if not goals:
        goals = await generate_goals_fallback(context, patterns)
        if goals:
            logger.info(f"L5 generated {len(goals)} goals via pattern fallback")
    else:
        logger.info(f"L5 generated {len(goals)} goals via Claude API")

    # Post-generation dedup filter against recent goals
    before_count = len(goals)
    goals = _dedup_goals(goals, recent_titles)
    if len(goals) < before_count:
        logger.info(f"L5 dedup: filtered {before_count - len(goals)} duplicate goals")

    # If all goals were duplicates, generate a fallback exploratory goal
    if not goals and before_count > 0:
        goals = [GeneratedGoal(
            title="health_report: comprehensive system snapshot",
            priority=2,
            description="All generated goals were duplicates of recent ones. Creating a fresh system snapshot instead.",
            reasoning="Deduplication filter removed all proposed goals — system may need novel exploration targets.",
            source="dedup_fallback",
        )]
        logger.info("L5 dedup: all goals filtered, using dedup fallback")

    return goals, context


async def run_check(db: Database, queue: TaskQueue) -> CheckResult:
    """Run L5 as a check — verify goal generation is functional."""
    start = time.monotonic()
    try:
        analyzer = PatternAnalyzer(db, queue)
        context = await analyzer.get_context_summary()
        patterns = await analyzer.analyze()

        has_api_key = bool(os.environ.get("ANTHROPIC_API_KEY"))
        elapsed = (time.monotonic() - start) * 1000

        details = {
            "patterns_detected": len(patterns),
            "pattern_categories": list(set(p.category for p in patterns)),
            "llm_available": has_api_key,
            "health_score": context.get("health_score", 0),
            "active_levels": context.get("active_levels", 0),
        }

        return CheckResult(
            "goal_generation",
            True,
            elapsed,
            f"L5 ready: {len(patterns)} patterns, LLM {'available' if has_api_key else 'fallback mode'}",
            details,
        )
    except Exception as e:
        elapsed = (time.monotonic() - start) * 1000
        return CheckResult("goal_generation", False, elapsed, f"L5 check failed: {e}")
