import { useState, useEffect, useCallback } from "react";

const COLORS = {
  bg: "#0a0e17",
  surface: "#111827",
  surfaceLight: "#1a2332",
  border: "#2a3a4f",
  text: "#e2e8f0",
  textMuted: "#8899aa",
  textDim: "#556677",
  accent: "#3b82f6",
  green: "#10b981",
  greenGlow: "rgba(16, 185, 129, 0.15)",
  amber: "#f59e0b",
  amberGlow: "rgba(245, 158, 11, 0.15)",
  red: "#ef4444",
  redGlow: "rgba(239, 68, 68, 0.15)",
  purple: "#8b5cf6",
  purpleGlow: "rgba(139, 92, 246, 0.15)",
  cyan: "#06b6d4",
  cyanGlow: "rgba(6, 182, 212, 0.15)",
};

const LEVEL_CONFIG = {
  1: { name: "Operational Survival", color: COLORS.green, glow: COLORS.greenGlow, icon: "L1", cadence: "30s" },
  2: { name: "Persistent State Safety", color: COLORS.cyan, glow: COLORS.cyanGlow, icon: "L2", cadence: "5m" },
  3: { name: "Task Ecosystem Health", color: COLORS.amber, glow: COLORS.amberGlow, icon: "L3", cadence: "15m" },
  4: { name: "Performance & Impact", color: COLORS.accent, glow: "rgba(59,130,246,0.15)", icon: "L4", cadence: "2m" },
  5: { name: "Goal Generation", color: COLORS.purple, glow: COLORS.purpleGlow, icon: "L5", cadence: "triggered" },
};

const STATUS_COLORS = {
  healthy: COLORS.green,
  degraded: COLORS.amber,
  critical: COLORS.red,
  suspended: COLORS.textDim,
  unknown: COLORS.textDim,
};

const TASK_STATUS_COLORS = {
  pending_approval: COLORS.purple,
  queued: COLORS.amber,
  running: COLORS.accent,
  completed: COLORS.green,
  failed: COLORS.red,
};

const API_BASE = "/api";
const POLL_INTERVAL = 3000;

function usePolling(endpoint, interval = POLL_INTERVAL) {
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);

  const fetchData = useCallback(async () => {
    try {
      const res = await fetch(`${API_BASE}${endpoint}`);
      if (!res.ok) throw new Error(`${res.status}`);
      const json = await res.json();
      setData(json);
      setError(null);
    } catch (e) {
      setError(e.message);
    }
  }, [endpoint]);

  useEffect(() => {
    fetchData();
    const id = setInterval(fetchData, interval);
    return () => clearInterval(id);
  }, [fetchData, interval]);

  return { data, error, refetch: fetchData };
}

function timeAgo(ts) {
  if (!ts) return "never";
  const age = Date.now() / 1000 - ts;
  if (age < 60) return `${Math.round(age)}s ago`;
  if (age < 3600) return `${Math.round(age / 60)}m ago`;
  return `${(age / 3600).toFixed(1)}h ago`;
}

function StatusBadge({ status }) {
  const color = STATUS_COLORS[status] || COLORS.textDim;
  return (
    <span style={{
      display: "inline-flex", alignItems: "center", gap: "6px",
      fontSize: "12px", fontWeight: 600, color,
      background: `${color}22`, border: `1px solid ${color}44`,
      padding: "3px 10px", borderRadius: "4px",
      fontFamily: "'JetBrains Mono', monospace", textTransform: "uppercase",
    }}>
      <span style={{
        width: "7px", height: "7px", borderRadius: "50%", background: color,
        boxShadow: status === "healthy" ? `0 0 6px ${color}` : "none",
      }} />
      {status}
    </span>
  );
}

function HierarchyCard({ level }) {
  const config = LEVEL_CONFIG[level.level] || {};
  const statusColor = STATUS_COLORS[level.status] || COLORS.textDim;

  let checks = [];
  if (level.details) {
    const d = typeof level.details === "string" ? JSON.parse(level.details) : level.details;
    checks = d.checks || [];
  }

  return (
    <div style={{
      border: `1px solid ${config.color}44`,
      borderLeft: `3px solid ${statusColor}`,
      borderRadius: "8px",
      padding: "14px 16px",
      background: `linear-gradient(90deg, ${config.glow}, ${COLORS.surface})`,
    }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: checks.length > 0 ? "10px" : "0" }}>
        <div style={{ display: "flex", alignItems: "center", gap: "10px" }}>
          <span style={{
            fontSize: "11px", fontWeight: 700, color: COLORS.bg,
            background: config.color, padding: "2px 8px", borderRadius: "3px",
            fontFamily: "'JetBrains Mono', monospace",
          }}>{config.icon}</span>
          <span style={{ fontSize: "15px", fontWeight: 700, color: COLORS.text }}>{config.name}</span>
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: "10px" }}>
          <span style={{ fontSize: "11px", color: COLORS.textDim, fontFamily: "'JetBrains Mono', monospace" }}>
            {timeAgo(level.last_check)}
          </span>
          <StatusBadge status={level.status} />
        </div>
      </div>

      {checks.length > 0 && (
        <div style={{ display: "flex", flexWrap: "wrap", gap: "6px" }}>
          {checks.map((c, i) => (
            <span key={i} style={{
              fontSize: "11px",
              color: c.passed ? COLORS.green : COLORS.red,
              background: c.passed ? `${COLORS.green}15` : `${COLORS.red}15`,
              border: `1px solid ${c.passed ? COLORS.green : COLORS.red}33`,
              padding: "2px 8px", borderRadius: "3px",
              fontFamily: "'JetBrains Mono', monospace",
            }}>
              {c.passed ? "+" : "x"} {c.name.replace(/_/g, " ")}
            </span>
          ))}
        </div>
      )}
    </div>
  );
}

function StatsBar({ stats, taskStats }) {
  if (!stats) return null;
  const items = [
    { label: "Levels Healthy", value: `${stats.levels_healthy}/${stats.levels_total}`, color: stats.levels_healthy === stats.levels_total ? COLORS.green : stats.levels_healthy >= 3 ? COLORS.amber : COLORS.red },
    { label: "Pass Rate", value: `${stats.pass_rate}%`, color: stats.pass_rate >= 95 ? COLORS.green : stats.pass_rate >= 80 ? COLORS.amber : COLORS.red },
    { label: "Tasks Done", value: taskStats ? taskStats.completed : 0, color: COLORS.green },
    { label: "Queue Depth", value: taskStats ? taskStats.queued : 0, color: taskStats && taskStats.queued > 10 ? COLORS.amber : COLORS.text },
    { label: "Task Success", value: taskStats ? `${taskStats.completion_rate}%` : "---", color: taskStats && taskStats.completion_rate >= 90 ? COLORS.green : COLORS.amber },
    { label: "Failures", value: stats.recent_checks_failed, color: stats.recent_checks_failed > 0 ? COLORS.red : COLORS.green },
  ];

  return (
    <div style={{ display: "grid", gridTemplateColumns: `repeat(${items.length}, 1fr)`, gap: "10px", marginBottom: "20px" }}>
      {items.map((item) => (
        <div key={item.label} style={{
          border: `1px solid ${COLORS.border}`,
          borderRadius: "8px",
          padding: "12px 14px",
          background: COLORS.surface,
        }}>
          <div style={{ fontSize: "10px", color: COLORS.textDim, textTransform: "uppercase", letterSpacing: "0.06em", marginBottom: "4px" }}>
            {item.label}
          </div>
          <div style={{ fontSize: "20px", fontWeight: 700, color: item.color, fontFamily: "'JetBrains Mono', monospace" }}>
            {item.value}
          </div>
        </div>
      ))}
    </div>
  );
}

function ActionLog({ actions }) {
  if (!actions || actions.length === 0) {
    return (
      <div style={{ padding: "24px", textAlign: "center", color: COLORS.textDim, fontSize: "13px" }}>
        No agent actions recorded yet. Start the daemon to see activity.
      </div>
    );
  }

  const typeColors = {
    check: COLORS.accent,
    repair: COLORS.amber,
    goal: COLORS.purple,
    task_exec: COLORS.cyan,
    task_enqueue: COLORS.purple,
    report: COLORS.green,
    notification: COLORS.red,
    lifecycle: COLORS.green,
  };

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: "1px", maxHeight: "500px", overflowY: "auto" }}>
      {actions.map((action) => {
        const color = typeColors[action.action_type] || COLORS.textMuted;
        return (
          <div key={action.id} style={{
            display: "grid",
            gridTemplateColumns: "80px 50px 100px 1fr 80px",
            gap: "8px",
            padding: "8px 12px",
            alignItems: "center",
            background: COLORS.surface,
            borderBottom: `1px solid ${COLORS.border}33`,
            fontSize: "12px",
          }}>
            <span style={{ color: COLORS.textDim, fontFamily: "'JetBrains Mono', monospace", fontSize: "11px" }}>
              {timeAgo(action.timestamp)}
            </span>
            <span style={{ color: COLORS.textMuted, fontFamily: "'JetBrains Mono', monospace", fontSize: "11px" }}>
              {action.level ? `L${action.level}` : "--"}
            </span>
            <span style={{
              color, fontSize: "10px", fontWeight: 600,
              textTransform: "uppercase", fontFamily: "'JetBrains Mono', monospace",
            }}>
              {action.action_type}
            </span>
            <span style={{ color: COLORS.textMuted, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
              {action.description}
            </span>
            <span style={{
              fontSize: "11px", fontFamily: "'JetBrains Mono', monospace",
              color: action.status === "completed" ? COLORS.green : action.status === "failed" ? COLORS.red : COLORS.amber,
            }}>
              {action.duration_ms ? `${Math.round(action.duration_ms)}ms` : action.status}
            </span>
          </div>
        );
      })}
    </div>
  );
}

function HealthLog({ logs }) {
  if (!logs || logs.length === 0) {
    return (
      <div style={{ padding: "24px", textAlign: "center", color: COLORS.textDim, fontSize: "13px" }}>
        No health check logs yet.
      </div>
    );
  }

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: "1px", maxHeight: "500px", overflowY: "auto" }}>
      {logs.map((log) => {
        const levelConfig = LEVEL_CONFIG[log.level] || {};
        return (
          <div key={log.id} style={{
            display: "grid",
            gridTemplateColumns: "80px 50px 160px 1fr 80px",
            gap: "8px",
            padding: "6px 12px",
            alignItems: "center",
            background: COLORS.surface,
            borderBottom: `1px solid ${COLORS.border}22`,
            fontSize: "12px",
          }}>
            <span style={{ color: COLORS.textDim, fontFamily: "'JetBrains Mono', monospace", fontSize: "11px" }}>
              {timeAgo(log.timestamp)}
            </span>
            <span style={{
              color: levelConfig.color || COLORS.textMuted,
              fontFamily: "'JetBrains Mono', monospace", fontSize: "11px", fontWeight: 600,
            }}>
              L{log.level}
            </span>
            <span style={{ color: COLORS.textMuted, fontFamily: "'JetBrains Mono', monospace", fontSize: "11px" }}>
              {log.check_name}
            </span>
            <span style={{ color: COLORS.textMuted, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
              {log.message}
            </span>
            <span style={{
              fontFamily: "'JetBrains Mono', monospace", fontSize: "11px", fontWeight: 600,
              color: log.passed ? COLORS.green : COLORS.red,
            }}>
              {log.passed ? "PASS" : "FAIL"} {log.duration_ms ? `${Math.round(log.duration_ms)}ms` : ""}
            </span>
          </div>
        );
      })}
    </div>
  );
}

function TaskQueuePanel({ tasks, taskStats, onSubmitTask, onApprove, onReject }) {
  const [newTitle, setNewTitle] = useState("");
  const [newPriority, setNewPriority] = useState(0);

  const handleSubmit = async (e) => {
    e.preventDefault();
    if (!newTitle.trim()) return;
    await onSubmitTask(newTitle, newPriority);
    setNewTitle("");
    setNewPriority(0);
  };

  return (
    <div>
      {/* Task Stats Summary */}
      {taskStats && (
        <div style={{ display: "grid", gridTemplateColumns: "repeat(6, 1fr)", gap: "10px", marginBottom: "20px" }}>
          {[
            { label: "Awaiting Approval", value: taskStats.pending_approval || 0, color: COLORS.purple },
            { label: "Queued", value: taskStats.queued, color: COLORS.amber },
            { label: "Running", value: taskStats.running, color: COLORS.accent },
            { label: "Completed", value: taskStats.completed, color: COLORS.green },
            { label: "Failed", value: taskStats.failed, color: COLORS.red },
            { label: "Avg Duration", value: taskStats.avg_duration_ms ? `${Math.round(taskStats.avg_duration_ms)}ms` : "---", color: COLORS.text },
          ].map((s) => (
            <div key={s.label} style={{
              border: `1px solid ${COLORS.border}`, borderRadius: "8px",
              padding: "10px 14px", background: COLORS.surface,
            }}>
              <div style={{ fontSize: "10px", color: COLORS.textDim, textTransform: "uppercase", letterSpacing: "0.06em", marginBottom: "3px" }}>
                {s.label}
              </div>
              <div style={{ fontSize: "18px", fontWeight: 700, color: s.color, fontFamily: "'JetBrains Mono', monospace" }}>
                {s.value}
              </div>
            </div>
          ))}
        </div>
      )}

      {/* Enqueue Form */}
      <form onSubmit={handleSubmit} style={{
        display: "flex", gap: "8px", marginBottom: "16px",
        padding: "12px", background: COLORS.surface,
        border: `1px solid ${COLORS.border}`, borderRadius: "8px",
      }}>
        <input
          value={newTitle}
          onChange={(e) => setNewTitle(e.target.value)}
          placeholder="Task title (e.g. echo: test task, health_report: ad hoc)"
          style={{
            flex: 1, padding: "8px 12px", fontSize: "13px",
            background: COLORS.bg, color: COLORS.text,
            border: `1px solid ${COLORS.border}`, borderRadius: "4px",
            fontFamily: "'JetBrains Mono', monospace",
            outline: "none",
          }}
        />
        <select
          value={newPriority}
          onChange={(e) => setNewPriority(Number(e.target.value))}
          style={{
            padding: "8px 12px", fontSize: "12px",
            background: COLORS.bg, color: COLORS.text,
            border: `1px solid ${COLORS.border}`, borderRadius: "4px",
            fontFamily: "'JetBrains Mono', monospace",
          }}
        >
          <option value={0}>P0 Low</option>
          <option value={3}>P3 Med</option>
          <option value={5}>P5 High</option>
          <option value={9}>P9 Urgent</option>
        </select>
        <button type="submit" style={{
          padding: "8px 20px", fontSize: "12px", fontWeight: 600,
          background: COLORS.accent, color: "#fff",
          border: "none", borderRadius: "4px", cursor: "pointer",
          fontFamily: "'JetBrains Mono', monospace",
        }}>
          ENQUEUE
        </button>
      </form>

      {/* Task List */}
      <h2 style={{ fontSize: "14px", fontWeight: 600, color: COLORS.textMuted, textTransform: "uppercase", letterSpacing: "0.05em", marginBottom: "12px" }}>
        Task History
      </h2>
      <div style={{ border: `1px solid ${COLORS.border}`, borderRadius: "8px", overflow: "hidden" }}>
        {!tasks || tasks.length === 0 ? (
          <div style={{ padding: "24px", textAlign: "center", color: COLORS.textDim, fontSize: "13px" }}>
            No tasks yet. Enqueue one above or wait for the daemon to generate system tasks.
          </div>
        ) : (
          <div style={{ display: "flex", flexDirection: "column", gap: "1px", maxHeight: "400px", overflowY: "auto" }}>
            {tasks.map((task) => {
              const statusColor = TASK_STATUS_COLORS[task.status] || COLORS.textDim;
              const duration = task.completed_at && task.started_at
                ? `${Math.round((task.completed_at - task.started_at) * 1000)}ms`
                : null;
              return (
                <div key={task.id} style={{
                  display: "grid",
                  gridTemplateColumns: "80px 40px 70px 1fr 90px",
                  gap: "8px",
                  padding: "8px 12px",
                  alignItems: "center",
                  background: COLORS.surface,
                  borderBottom: `1px solid ${COLORS.border}33`,
                  fontSize: "12px",
                }}>
                  <span style={{ color: COLORS.textDim, fontFamily: "'JetBrains Mono', monospace", fontSize: "11px" }}>
                    {timeAgo(task.created_at)}
                  </span>
                  <span style={{
                    fontSize: "10px", fontWeight: 700, textAlign: "center",
                    color: task.priority >= 5 ? COLORS.red : task.priority >= 3 ? COLORS.amber : COLORS.textDim,
                    fontFamily: "'JetBrains Mono', monospace",
                  }}>
                    P{task.priority}
                  </span>
                  <span style={{
                    fontSize: "10px", fontWeight: 600, color: COLORS.bg,
                    background: statusColor, padding: "2px 6px", borderRadius: "3px",
                    textAlign: "center", textTransform: "uppercase",
                    fontFamily: "'JetBrains Mono', monospace",
                  }}>
                    {task.status === "pending_approval" ? "PENDING" : task.status}
                  </span>
                  <div style={{ overflow: "hidden" }}>
                    <div style={{ color: COLORS.text, fontSize: "12px", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                      {task.title}
                    </div>
                    {task.description && (
                      <div style={{ color: COLORS.textDim, fontSize: "11px", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                        {task.description}
                      </div>
                    )}
                  </div>
                  <span style={{
                    fontSize: "11px", fontFamily: "'JetBrains Mono', monospace",
                    color: COLORS.textMuted, textAlign: "right",
                    display: "flex", alignItems: "center", justifyContent: "flex-end", gap: "4px",
                  }}>
                    {task.status === "pending_approval" && onApprove && onReject ? (
                      <>
                        <button
                          onClick={() => onApprove(task.id)}
                          style={{
                            fontSize: "9px", fontWeight: 700, cursor: "pointer",
                            background: `${COLORS.green}22`, color: COLORS.green,
                            border: `1px solid ${COLORS.green}44`, borderRadius: "3px",
                            padding: "2px 6px", fontFamily: "'JetBrains Mono', monospace",
                          }}
                        >APPROVE</button>
                        <button
                          onClick={() => onReject(task.id)}
                          style={{
                            fontSize: "9px", fontWeight: 700, cursor: "pointer",
                            background: `${COLORS.red}22`, color: COLORS.red,
                            border: `1px solid ${COLORS.red}44`, borderRadius: "3px",
                            padding: "2px 6px", fontFamily: "'JetBrains Mono', monospace",
                          }}
                        >REJECT</button>
                      </>
                    ) : (
                      duration || (task.status === "running" ? "running..." : task.source)
                    )}
                  </span>
                </div>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
}

function GoalsPanel({ goals, goalStats, onDismiss }) {
  return (
    <div>
      {/* Goal Stats */}
      {goalStats && (
        <div style={{ display: "grid", gridTemplateColumns: "repeat(5, 1fr)", gap: "10px", marginBottom: "20px" }}>
          {[
            { label: "Goals Generated", value: goalStats.total, color: COLORS.purple },
            { label: "Enacted", value: goalStats.enacted, color: COLORS.green },
            { label: "Dismissed", value: goalStats.dismissed || 0, color: COLORS.red },
            { label: "From LLM", value: goalStats.from_llm, color: COLORS.cyan },
            { label: "From Patterns", value: goalStats.from_patterns, color: COLORS.amber },
          ].map((s) => (
            <div key={s.label} style={{
              border: `1px solid ${COLORS.border}`, borderRadius: "8px",
              padding: "10px 14px", background: COLORS.surface,
            }}>
              <div style={{ fontSize: "10px", color: COLORS.textDim, textTransform: "uppercase", letterSpacing: "0.06em", marginBottom: "3px" }}>
                {s.label}
              </div>
              <div style={{ fontSize: "18px", fontWeight: 700, color: s.color, fontFamily: "'JetBrains Mono', monospace" }}>
                {s.value}
              </div>
            </div>
          ))}
        </div>
      )}

      {/* Mode Indicator */}
      <div style={{
        padding: "10px 16px", marginBottom: "16px",
        background: `${COLORS.purple}15`, border: `1px solid ${COLORS.purple}33`,
        borderRadius: "8px", display: "flex", alignItems: "center", gap: "10px",
      }}>
        <span style={{
          fontSize: "11px", fontWeight: 700, color: COLORS.bg,
          background: COLORS.purple, padding: "2px 8px", borderRadius: "3px",
          fontFamily: "'JetBrains Mono', monospace",
        }}>L5</span>
        <span style={{ fontSize: "12px", color: COLORS.textMuted }}>
          Goal generation triggers when the task queue is empty. Goals are auto-enacted as tasks.
        </span>
        <span style={{
          marginLeft: "auto", fontSize: "11px", fontFamily: "'JetBrains Mono', monospace",
          color: goalStats && goalStats.from_llm > 0 ? COLORS.cyan : COLORS.amber,
        }}>
          {goalStats && goalStats.from_llm > 0 ? "LLM MODE" : "PATTERN FALLBACK"}
        </span>
      </div>

      {/* Goal List */}
      <h2 style={{ fontSize: "14px", fontWeight: 600, color: COLORS.textMuted, textTransform: "uppercase", letterSpacing: "0.05em", marginBottom: "12px" }}>
        Generated Goals
      </h2>
      <div style={{ border: `1px solid ${COLORS.border}`, borderRadius: "8px", overflow: "hidden" }}>
        {!goals || goals.length === 0 ? (
          <div style={{ padding: "24px", textAlign: "center", color: COLORS.textDim, fontSize: "13px" }}>
            No goals generated yet. L5 activates when all levels are healthy and the task queue is empty.
          </div>
        ) : (
          <div style={{ display: "flex", flexDirection: "column", gap: "1px", maxHeight: "500px", overflowY: "auto" }}>
            {goals.map((goal) => {
              const statusColor = goal.status === "enacted" ? COLORS.green : goal.status === "dismissed" ? COLORS.red : COLORS.amber;
              return (
                <div key={goal.id} style={{
                  padding: "12px 16px",
                  background: COLORS.surface,
                  borderBottom: `1px solid ${COLORS.border}33`,
                  borderLeft: `3px solid ${COLORS.purple}66`,
                }}>
                  <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "6px" }}>
                    <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
                      <span style={{
                        fontSize: "10px", fontWeight: 700, textAlign: "center",
                        color: goal.priority >= 5 ? COLORS.red : goal.priority >= 3 ? COLORS.amber : COLORS.textDim,
                        fontFamily: "'JetBrains Mono', monospace",
                      }}>P{goal.priority}</span>
                      <span style={{ fontSize: "13px", fontWeight: 600, color: COLORS.text }}>
                        {goal.title}
                      </span>
                    </div>
                    <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
                      <span style={{
                        fontSize: "10px", fontFamily: "'JetBrains Mono', monospace",
                        color: goal.source === "llm" ? COLORS.cyan : COLORS.amber,
                        background: goal.source === "llm" ? `${COLORS.cyan}22` : `${COLORS.amber}22`,
                        padding: "2px 6px", borderRadius: "3px",
                      }}>
                        {goal.source === "llm" ? "LLM" : "PATTERN"}
                      </span>
                      <span style={{
                        fontSize: "10px", fontWeight: 600, color: COLORS.bg,
                        background: statusColor, padding: "2px 6px", borderRadius: "3px",
                        textTransform: "uppercase", fontFamily: "'JetBrains Mono', monospace",
                      }}>
                        {goal.status}
                      </span>
                      <span style={{ fontSize: "11px", color: COLORS.textDim, fontFamily: "'JetBrains Mono', monospace" }}>
                        {timeAgo(goal.timestamp)}
                      </span>
                      {goal.status !== "dismissed" && onDismiss && (
                        <button
                          onClick={() => onDismiss(goal.id)}
                          title="Dismiss — L5 won't repeat this goal"
                          style={{
                            fontSize: "10px", fontWeight: 600, cursor: "pointer",
                            background: `${COLORS.red}22`, color: COLORS.red,
                            border: `1px solid ${COLORS.red}44`, borderRadius: "3px",
                            padding: "2px 8px", fontFamily: "'JetBrains Mono', monospace",
                          }}
                        >
                          DISMISS
                        </button>
                      )}
                    </div>
                  </div>
                  {goal.description && (
                    <div style={{ fontSize: "12px", color: COLORS.textMuted, marginBottom: "4px" }}>
                      {goal.description}
                    </div>
                  )}
                  {goal.reasoning && (
                    <div style={{ fontSize: "11px", color: COLORS.textDim, fontStyle: "italic" }}>
                      Reasoning: {goal.reasoning}
                    </div>
                  )}
                  {goal.task_id && (
                    <div style={{ fontSize: "10px", color: COLORS.purple, fontFamily: "'JetBrains Mono', monospace", marginTop: "4px" }}>
                      Task #{goal.task_id}
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
}

export default function App() {
  const [activeTab, setActiveTab] = useState("overview");
  const { data: hierarchy } = usePolling("/hierarchy");
  const { data: stats } = usePolling("/health-stats");
  const { data: actionsData } = usePolling("/actions");
  const { data: logsData } = usePolling("/health-logs?limit=100");
  const { data: tasksData, refetch: refetchTasks } = usePolling("/tasks?include_done=true&limit=50");
  const { data: taskStats } = usePolling("/task-stats");
  const { data: goalsData, refetch: refetchGoals } = usePolling("/goals");
  const { data: goalStats, refetch: refetchGoalStats } = usePolling("/goal-stats");

  const tabs = [
    { id: "overview", label: "Overview" },
    { id: "goals", label: "L5 Goals" },
    { id: "tasks", label: "Task Queue" },
    { id: "actions", label: "Agent Actions" },
    { id: "logs", label: "Health Logs" },
  ];

  const daemonOnline = hierarchy && hierarchy.levels && hierarchy.levels.some(
    (l) => l.status !== "unknown"
  );

  const handleDismissGoal = async (goalId) => {
    try {
      await fetch(`${API_BASE}/goals/${goalId}/dismiss`, { method: "POST" });
      refetchGoals();
      refetchGoalStats();
    } catch (e) {
      console.error("Failed to dismiss goal:", e);
    }
  };

  const handleApproveTask = async (taskId) => {
    try {
      await fetch(`${API_BASE}/tasks/${taskId}/approve`, { method: "POST" });
      refetchTasks();
    } catch (e) {
      console.error("Failed to approve task:", e);
    }
  };

  const handleRejectTask = async (taskId) => {
    try {
      await fetch(`${API_BASE}/tasks/${taskId}/reject`, { method: "POST" });
      refetchTasks();
    } catch (e) {
      console.error("Failed to reject task:", e);
    }
  };

  const handleSubmitTask = async (title, priority) => {
    try {
      await fetch(`${API_BASE}/tasks`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ title, priority, source: "dashboard" }),
      });
      refetchTasks();
    } catch (e) {
      console.error("Failed to enqueue task:", e);
    }
  };

  return (
    <div style={{
      background: COLORS.bg, minHeight: "100vh", color: COLORS.text,
      fontFamily: "'Inter', -apple-system, sans-serif",
    }}>
      {/* Header */}
      <div style={{
        padding: "16px 24px",
        borderBottom: `1px solid ${COLORS.border}`,
        display: "flex", justifyContent: "space-between", alignItems: "center",
      }}>
        <div style={{ display: "flex", alignItems: "center", gap: "12px" }}>
          <h1 style={{
            fontSize: "18px", fontWeight: 700, margin: 0,
            fontFamily: "'JetBrains Mono', monospace", color: COLORS.text,
          }}>
            ANAH
          </h1>
          <span style={{ fontSize: "12px", color: COLORS.textDim }}>Autonomous Needs-Aware Hierarchy</span>
          <span style={{
            fontSize: "10px", color: COLORS.accent, fontFamily: "'JetBrains Mono', monospace",
            background: `${COLORS.accent}22`, border: `1px solid ${COLORS.accent}44`,
            padding: "2px 8px", borderRadius: "3px",
          }}>PHASE 3</span>
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: "12px" }}>
          <span style={{
            display: "inline-flex", alignItems: "center", gap: "6px",
            fontSize: "11px", fontFamily: "'JetBrains Mono', monospace",
            color: daemonOnline ? COLORS.green : COLORS.red,
          }}>
            <span style={{
              width: "8px", height: "8px", borderRadius: "50%",
              background: daemonOnline ? COLORS.green : COLORS.red,
              boxShadow: daemonOnline ? `0 0 8px ${COLORS.green}` : "none",
              animation: daemonOnline ? "pulse 2s infinite" : "none",
            }} />
            {daemonOnline ? "DAEMON ONLINE" : "DAEMON OFFLINE"}
          </span>
        </div>
      </div>

      {/* Tabs */}
      <div style={{
        borderBottom: `1px solid ${COLORS.border}`,
        padding: "0 24px",
        display: "flex", gap: "0",
      }}>
        {tabs.map((tab) => (
          <button
            key={tab.id}
            onClick={() => setActiveTab(tab.id)}
            style={{
              background: activeTab === tab.id ? COLORS.surface : "transparent",
              border: `1px solid ${activeTab === tab.id ? COLORS.border : "transparent"}`,
              borderBottom: activeTab === tab.id ? `1px solid ${COLORS.surface}` : `1px solid ${COLORS.border}`,
              borderRadius: "6px 6px 0 0",
              padding: "10px 20px",
              color: activeTab === tab.id ? COLORS.text : COLORS.textMuted,
              fontSize: "13px",
              fontWeight: activeTab === tab.id ? 600 : 400,
              cursor: "pointer",
              marginBottom: "-1px",
              transition: "all 0.15s ease",
            }}
          >
            {tab.label}
            {tab.id === "tasks" && taskStats && (taskStats.queued > 0 || (taskStats.pending_approval || 0) > 0) && (
              <span style={{
                marginLeft: "6px", fontSize: "10px", fontWeight: 700,
                background: (taskStats.pending_approval || 0) > 0 ? COLORS.purple : COLORS.amber,
                color: COLORS.bg,
                padding: "1px 6px", borderRadius: "8px",
              }}>{(taskStats.pending_approval || 0) > 0 ? `${taskStats.pending_approval} pending` : taskStats.queued}</span>
            )}
          </button>
        ))}
      </div>

      {/* Content */}
      <div style={{ padding: "24px", maxWidth: "1200px" }}>
        {activeTab === "overview" && (
          <>
            <StatsBar stats={stats} taskStats={taskStats} />
            <div style={{ marginBottom: "12px" }}>
              <h2 style={{ fontSize: "14px", fontWeight: 600, color: COLORS.textMuted, textTransform: "uppercase", letterSpacing: "0.05em", marginBottom: "12px" }}>
                Hierarchy Status
              </h2>
              <div style={{ display: "flex", flexDirection: "column", gap: "8px" }}>
                {hierarchy && hierarchy.levels
                  ? hierarchy.levels.map((level) => <HierarchyCard key={level.level} level={level} />)
                  : <div style={{ color: COLORS.textDim, fontSize: "13px", padding: "20px", textAlign: "center" }}>
                      Connecting to daemon API...
                    </div>
                }
              </div>
            </div>
          </>
        )}

        {activeTab === "goals" && (
          <GoalsPanel goals={goalsData?.goals} goalStats={goalStats} onDismiss={handleDismissGoal} />
        )}

        {activeTab === "tasks" && (
          <TaskQueuePanel
            tasks={tasksData?.tasks}
            taskStats={taskStats}
            onSubmitTask={handleSubmitTask}
            onApprove={handleApproveTask}
            onReject={handleRejectTask}
          />
        )}

        {activeTab === "actions" && (
          <div>
            <h2 style={{ fontSize: "14px", fontWeight: 600, color: COLORS.textMuted, textTransform: "uppercase", letterSpacing: "0.05em", marginBottom: "12px" }}>
              Agent Actions
            </h2>
            <div style={{ border: `1px solid ${COLORS.border}`, borderRadius: "8px", overflow: "hidden" }}>
              <ActionLog actions={actionsData?.actions} />
            </div>
          </div>
        )}

        {activeTab === "logs" && (
          <div>
            <h2 style={{ fontSize: "14px", fontWeight: 600, color: COLORS.textMuted, textTransform: "uppercase", letterSpacing: "0.05em", marginBottom: "12px" }}>
              Health Check Logs
            </h2>
            <div style={{ border: `1px solid ${COLORS.border}`, borderRadius: "8px", overflow: "hidden" }}>
              <HealthLog logs={logsData?.logs} />
            </div>
          </div>
        )}
      </div>

      <style>{`
        @keyframes pulse {
          0%, 100% { opacity: 1; }
          50% { opacity: 0.5; }
        }
        * { box-sizing: border-box; }
        body { margin: 0; background: ${COLORS.bg}; }
        ::-webkit-scrollbar { width: 6px; }
        ::-webkit-scrollbar-track { background: ${COLORS.bg}; }
        ::-webkit-scrollbar-thumb { background: ${COLORS.border}; border-radius: 3px; }
        input::placeholder { color: ${COLORS.textDim}; }
        input:focus, select:focus { border-color: ${COLORS.accent} !important; }
        button:hover { opacity: 0.9; }
      `}</style>
    </div>
  );
}
