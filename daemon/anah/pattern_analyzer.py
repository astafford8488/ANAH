"""Pattern Analyzer — detect recurring failures, optimization opportunities, and trends.

This is the "local brain" that feeds L5 goal generation.
Pure data analysis, no LLM required.
"""

import time
from dataclasses import dataclass, field

from anah.db import Database
from anah.task_queue import TaskQueue


@dataclass
class Pattern:
    category: str  # failure_pattern, performance_trend, idle_opportunity, maintenance
    severity: str  # info, warning, critical
    title: str
    description: str
    evidence: dict = field(default_factory=dict)
    suggested_action: str = ""


class PatternAnalyzer:
    def __init__(self, db: Database, queue: TaskQueue):
        self.db = db
        self.queue = queue

    async def analyze(self) -> list[Pattern]:
        """Run all pattern detectors and return findings."""
        patterns = []
        patterns.extend(await self._detect_recurring_failures())
        patterns.extend(await self._detect_performance_trends())
        patterns.extend(await self._detect_idle_opportunities())
        patterns.extend(await self._detect_maintenance_needs())
        patterns.extend(await self._detect_check_anomalies())
        return patterns

    async def _detect_recurring_failures(self) -> list[Pattern]:
        """Find checks that fail repeatedly."""
        patterns = []
        cursor = await self.db._db.execute("""
            SELECT check_name, level, COUNT(*) as fail_count,
                   MIN(timestamp) as first_fail, MAX(timestamp) as last_fail
            FROM health_logs
            WHERE passed = 0 AND timestamp > ?
            GROUP BY check_name, level
            HAVING fail_count >= 3
            ORDER BY fail_count DESC
        """, (time.time() - 3600,))  # Last hour

        rows = await cursor.fetchall()
        for row in rows:
            r = dict(row)
            patterns.append(Pattern(
                category="failure_pattern",
                severity="warning" if r["fail_count"] < 5 else "critical",
                title=f"Recurring failure: {r['check_name']}",
                description=f"L{r['level']} check '{r['check_name']}' has failed {r['fail_count']} times in the last hour",
                evidence={"check_name": r["check_name"], "level": r["level"], "fail_count": r["fail_count"]},
                suggested_action=f"self_diagnostic: investigate {r['check_name']} recurring failures",
            ))
        return patterns

    async def _detect_performance_trends(self) -> list[Pattern]:
        """Detect degrading performance (increasing latencies)."""
        patterns = []

        # Compare average latency in last 15 min vs previous 15 min
        now = time.time()
        cursor = await self.db._db.execute("""
            SELECT
                AVG(CASE WHEN timestamp > ? THEN duration_ms END) as recent_avg,
                AVG(CASE WHEN timestamp <= ? AND timestamp > ? THEN duration_ms END) as previous_avg,
                COUNT(CASE WHEN timestamp > ? THEN 1 END) as recent_count
            FROM agent_actions
            WHERE duration_ms IS NOT NULL AND timestamp > ?
        """, (now - 900, now - 900, now - 1800, now - 900, now - 1800))

        row = await cursor.fetchone()
        if row:
            r = dict(row)
            recent = r["recent_avg"]
            previous = r["previous_avg"]
            if recent and previous and r["recent_count"] >= 5:
                ratio = recent / previous if previous > 0 else 1
                if ratio > 1.5:
                    patterns.append(Pattern(
                        category="performance_trend",
                        severity="warning",
                        title="Performance degradation detected",
                        description=f"Average action latency increased {ratio:.1f}x ({previous:.0f}ms -> {recent:.0f}ms)",
                        evidence={"recent_avg_ms": round(recent, 1), "previous_avg_ms": round(previous, 1), "ratio": round(ratio, 2)},
                        suggested_action="self_diagnostic: investigate performance degradation",
                    ))
                elif ratio < 0.7:
                    patterns.append(Pattern(
                        category="performance_trend",
                        severity="info",
                        title="Performance improvement detected",
                        description=f"Average action latency decreased ({previous:.0f}ms -> {recent:.0f}ms)",
                        evidence={"recent_avg_ms": round(recent, 1), "previous_avg_ms": round(previous, 1)},
                    ))
        return patterns

    async def _detect_idle_opportunities(self) -> list[Pattern]:
        """Detect when the system is idle and could do proactive work."""
        patterns = []
        stats = await self.queue.get_stats()

        if stats["queued"] == 0 and stats["running"] == 0:
            # Check how long we've been idle
            cursor = await self.db._db.execute("""
                SELECT MAX(completed_at) as last_completed FROM task_queue WHERE status = 'completed'
            """)
            row = await cursor.fetchone()
            if row and row[0]:
                idle_sec = time.time() - row[0]
                if idle_sec > 60:
                    patterns.append(Pattern(
                        category="idle_opportunity",
                        severity="info",
                        title=f"System idle for {idle_sec:.0f}s",
                        description="Task queue is empty. Opportunity for proactive maintenance or exploration.",
                        evidence={"idle_seconds": round(idle_sec), "queue_stats": stats},
                        suggested_action="health_report: idle-triggered system assessment",
                    ))
        return patterns

    async def _detect_maintenance_needs(self) -> list[Pattern]:
        """Detect when maintenance tasks should be scheduled."""
        patterns = []

        # Check log volume
        cursor = await self.db._db.execute("SELECT COUNT(*) FROM health_logs")
        row = await cursor.fetchone()
        log_count = row[0] if row else 0

        if log_count > 5000:
            patterns.append(Pattern(
                category="maintenance",
                severity="info",
                title=f"Large log volume: {log_count} entries",
                description="Consider running cleanup to maintain database performance",
                evidence={"log_count": log_count},
                suggested_action="cleanup: high log volume maintenance",
            ))

        # Check if backup is stale
        import os
        db_path = self.db.db_path
        backup_path = str(db_path) + ".backup"
        if os.path.exists(backup_path):
            age = time.time() - os.path.getmtime(backup_path)
            if age > 1800:  # 30 min
                patterns.append(Pattern(
                    category="maintenance",
                    severity="warning",
                    title=f"Backup is {age/60:.0f} minutes old",
                    description="Database backup may be stale",
                    evidence={"backup_age_sec": round(age)},
                    suggested_action="self_diagnostic: verify backup freshness",
                ))
        return patterns

    async def _detect_check_anomalies(self) -> list[Pattern]:
        """Detect unusual patterns in check results."""
        patterns = []

        # Find checks with high variance in duration (unstable)
        cursor = await self.db._db.execute("""
            SELECT check_name, level,
                   AVG(duration_ms) as avg_ms,
                   MAX(duration_ms) as max_ms,
                   MIN(duration_ms) as min_ms,
                   COUNT(*) as count
            FROM health_logs
            WHERE timestamp > ?
            GROUP BY check_name, level
            HAVING count >= 5 AND max_ms > avg_ms * 3
        """, (time.time() - 3600,))

        rows = await cursor.fetchall()
        for row in rows:
            r = dict(row)
            patterns.append(Pattern(
                category="performance_trend",
                severity="info",
                title=f"Unstable check latency: {r['check_name']}",
                description=f"L{r['level']} '{r['check_name']}' latency range {r['min_ms']:.0f}-{r['max_ms']:.0f}ms (avg {r['avg_ms']:.0f}ms)",
                evidence={"check_name": r["check_name"], "avg_ms": round(r["avg_ms"], 1), "max_ms": round(r["max_ms"], 1)},
            ))
        return patterns

    async def get_context_summary(self) -> dict:
        """Generate a context summary for LLM-based goal generation."""
        hierarchy = await self.db.get_hierarchy()
        queue_stats = await self.queue.get_stats()
        recent_logs = await self.db.get_recent_logs(limit=20)
        recent_actions = await self.db.get_recent_actions(limit=20)
        patterns = await self.analyze()

        # Calculate health scores
        total_checks = len(recent_logs)
        passed = sum(1 for l in recent_logs if l["passed"])

        return {
            "hierarchy": {h["name"]: h["status"] for h in hierarchy},
            "health_score": round(passed / total_checks * 100, 1) if total_checks > 0 else 0,
            "queue": queue_stats,
            "patterns": [{"category": p.category, "severity": p.severity, "title": p.title, "description": p.description, "suggested_action": p.suggested_action} for p in patterns],
            "recent_failures": [{"check": l["check_name"], "level": l["level"], "message": l["message"]} for l in recent_logs if not l["passed"]],
            "active_levels": sum(1 for h in hierarchy if h["status"] == "healthy"),
            "total_levels": len(hierarchy),
        }
