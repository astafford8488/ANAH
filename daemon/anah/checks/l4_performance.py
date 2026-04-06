"""L4 — Performance & Impact checks.

Per-task + hourly aggregate. Lightweight metrics now, LLM-based quality later.
Tracks: completion rates, error rates, throughput, latency trends.
"""

import time
from dataclasses import dataclass

from anah.db import Database
from anah.task_queue import TaskQueue


@dataclass
class CheckResult:
    name: str
    passed: bool
    duration_ms: float
    message: str
    details: dict | None = None


async def check_task_completion_rate(queue: TaskQueue, min_rate: float = 70.0) -> CheckResult:
    """Check that task completion rate is above threshold."""
    start = time.monotonic()
    try:
        stats = await queue.get_stats()
        completed = stats["completed"]
        failed = stats["failed"]
        total_finished = completed + failed

        if total_finished == 0:
            elapsed = (time.monotonic() - start) * 1000
            return CheckResult("task_completion_rate", True, elapsed, "No finished tasks yet", stats)

        rate = stats["completion_rate"]
        elapsed = (time.monotonic() - start) * 1000

        if rate >= min_rate:
            return CheckResult("task_completion_rate", True, elapsed,
                             f"Completion rate: {rate}% ({completed}/{total_finished})", stats)
        return CheckResult("task_completion_rate", False, elapsed,
                         f"Completion rate low: {rate}% < {min_rate}% ({completed}/{total_finished})", stats)
    except Exception as e:
        elapsed = (time.monotonic() - start) * 1000
        return CheckResult("task_completion_rate", False, elapsed, f"Check failed: {e}")


async def check_error_rate(db: Database, window_sec: int = 3600, max_error_pct: float = 20.0) -> CheckResult:
    """Check that recent health check error rate is below threshold."""
    start = time.monotonic()
    try:
        cutoff = time.time() - window_sec
        cursor = await db._db.execute(
            "SELECT COUNT(*) as total, SUM(CASE WHEN passed = 0 THEN 1 ELSE 0 END) as failures FROM health_logs WHERE timestamp > ?",
            (cutoff,),
        )
        row = await cursor.fetchone()
        total = row[0] or 0
        failures = row[1] or 0

        elapsed = (time.monotonic() - start) * 1000
        if total == 0:
            return CheckResult("error_rate", True, elapsed, "No checks in window", {"window_sec": window_sec})

        error_pct = round(failures / total * 100, 1)
        details = {"total": total, "failures": failures, "error_pct": error_pct, "window_sec": window_sec}

        if error_pct <= max_error_pct:
            return CheckResult("error_rate", True, elapsed, f"Error rate: {error_pct}% ({failures}/{total})", details)
        return CheckResult("error_rate", False, elapsed,
                         f"Error rate high: {error_pct}% > {max_error_pct}% ({failures}/{total})", details)
    except Exception as e:
        elapsed = (time.monotonic() - start) * 1000
        return CheckResult("error_rate", False, elapsed, f"Check failed: {e}")


async def check_throughput(db: Database, window_sec: int = 3600, min_actions: int = 1) -> CheckResult:
    """Check that the system is actually doing work (not stalled)."""
    start = time.monotonic()
    try:
        cutoff = time.time() - window_sec
        cursor = await db._db.execute(
            "SELECT COUNT(*) FROM agent_actions WHERE timestamp > ? AND status = 'completed'",
            (cutoff,),
        )
        row = await cursor.fetchone()
        count = row[0] or 0

        elapsed = (time.monotonic() - start) * 1000
        details = {"completed_actions": count, "window_sec": window_sec, "min_required": min_actions}

        if count >= min_actions:
            return CheckResult("throughput", True, elapsed, f"Throughput: {count} actions in {window_sec}s", details)
        return CheckResult("throughput", False, elapsed,
                         f"Low throughput: {count} actions < {min_actions} required", details)
    except Exception as e:
        elapsed = (time.monotonic() - start) * 1000
        return CheckResult("throughput", False, elapsed, f"Check failed: {e}")


async def check_avg_latency(db: Database, window_sec: int = 3600, max_avg_ms: float = 5000.0) -> CheckResult:
    """Check that average action latency is within bounds."""
    start = time.monotonic()
    try:
        cutoff = time.time() - window_sec
        cursor = await db._db.execute(
            "SELECT AVG(duration_ms), MAX(duration_ms), MIN(duration_ms), COUNT(*) FROM agent_actions WHERE timestamp > ? AND duration_ms IS NOT NULL",
            (cutoff,),
        )
        row = await cursor.fetchone()
        avg_ms = row[0]
        max_ms = row[1]
        min_ms = row[2]
        count = row[3] or 0

        elapsed = (time.monotonic() - start) * 1000

        if count == 0:
            return CheckResult("avg_latency", True, elapsed, "No latency data yet")

        details = {"avg_ms": round(avg_ms, 1), "max_ms": round(max_ms, 1), "min_ms": round(min_ms, 1), "sample_count": count}

        if avg_ms <= max_avg_ms:
            return CheckResult("avg_latency", True, elapsed,
                             f"Avg latency: {avg_ms:.0f}ms (max {max_ms:.0f}ms)", details)
        return CheckResult("avg_latency", False, elapsed,
                         f"Avg latency high: {avg_ms:.0f}ms > {max_avg_ms:.0f}ms", details)
    except Exception as e:
        elapsed = (time.monotonic() - start) * 1000
        return CheckResult("avg_latency", False, elapsed, f"Check failed: {e}")


async def check_queue_health(queue: TaskQueue, max_queued: int = 50) -> CheckResult:
    """Check that the task queue isn't backing up."""
    start = time.monotonic()
    try:
        stats = await queue.get_stats()
        queued = stats["queued"]
        running = stats["running"]

        elapsed = (time.monotonic() - start) * 1000
        details = {"queued": queued, "running": running, "max_queued": max_queued}

        if queued <= max_queued:
            return CheckResult("queue_health", True, elapsed,
                             f"Queue: {queued} queued, {running} running", details)
        return CheckResult("queue_health", False, elapsed,
                         f"Queue backlog: {queued} > {max_queued} max", details)
    except Exception as e:
        elapsed = (time.monotonic() - start) * 1000
        return CheckResult("queue_health", False, elapsed, f"Check failed: {e}")


async def run_all(db: Database, queue: TaskQueue) -> list[CheckResult]:
    """Run all L4 checks."""
    results = []
    results.append(await check_task_completion_rate(queue))
    results.append(await check_error_rate(db))
    results.append(await check_throughput(db))
    results.append(await check_avg_latency(db))
    results.append(await check_queue_health(queue))
    return results
