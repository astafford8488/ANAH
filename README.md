<div align="center">

# 🧠 ANAH

### Autonomous Needs-Aware Hierarchy

[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://python.org)
[![React 18](https://img.shields.io/badge/React-18-61DAFB.svg)](https://react.dev)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)

**A self-directing agent that knows what it needs before you tell it.**

*5-level autonomous orchestration daemon with hierarchical gating — from survival checks to self-directed goal generation — plus a real-time React dashboard.*

</div>

---

## The Problem

Current AI agents wait for instructions. They don't monitor their own health, anticipate failures, or generate their own goals. ANAH inverts this — it's an always-on daemon that continuously evaluates its own needs across five priority levels, only escalating to higher-order thinking when lower needs are met.

## Architecture

```
┌─────────────────────────────────────────────────────┐
│                   ANAH DAEMON                        │
├──────────┬──────────┬──────────┬──────────┬──────────┤
│  L1      │  L2      │  L3      │  L4      │  L5      │
│ SURVIVAL │  STATE   │ECOSYSTEM │PERFORMNCE│  GOALS   │
│          │          │          │          │          │
│ Health   │ Config   │ Services │ Metrics  │ Self-    │
│ Disk     │ Drift    │ APIs     │ Optimize │ Directed │
│ Memory   │ Validate │ Deps     │ Tune     │ Generate │
└────┬─────┴────┬─────┴────┬─────┴────┬─────┴────┬─────┘
     │          │          │          │          │
     ▼          ▼          ▼          ▼          ▼
  Gate 1 ──→ Gate 2 ──→ Gate 3 ──→ Gate 4 ──→ Gate 5
  (must pass each level before advancing to the next)
```

## Hierarchical Gating

| Level | Name | What It Does | Gate Condition |
|-------|------|-------------|----------------|
| **L1** | Survival | Disk space, memory, process health, connectivity | All critical systems operational |
| **L2** | State | Configuration drift detection, state validation | Config consistent, no drift |
| **L3** | Ecosystem | External service health, API availability, dependencies | All dependencies reachable |
| **L4** | Performance | Metrics collection, optimization, tuning | Performance within thresholds |
| **L5** | Goal Generation | Self-directed task creation, autonomous planning | All lower levels satisfied |

**Key insight:** L5 (goal generation) only fires when L1-L4 are healthy. The system literally can't dream up new goals while it's on fire.

## Tech Stack

- **Daemon:** Python 3.11+, FastAPI, aiosqlite, Click, Pydantic
- **Dashboard:** React 18, Vite, WebSocket real-time updates
- **LLM Bridge:** Hermes integration for autonomous reasoning (local or API)
- **Task System:** Priority queue with approval gates and execution history

## Key Components

```
anah/
├── daemon.py           # Core loop — runs L1-L5 checks concurrently
├── config.py           # Pydantic configuration management
├── db.py               # aiosqlite database layer
├── task_queue.py        # Priority-based task queue
├── executor.py          # Task execution with approval gates
├── hermes_bridge.py     # LLM integration for reasoning
├── pattern_analyzer.py  # Behavioral pattern detection
├── checks/
│   ├── l1_survival.py   # Health, disk, memory, connectivity
│   ├── l2_state.py      # Config drift, state validation
│   ├── l3_ecosystem.py  # Service health, API checks
│   ├── l4_performance.py # Metrics, optimization
│   └── l5_goal_generation.py # Autonomous goal creation
└── dashboard/           # React real-time monitoring UI
```

## Prerequisites

- **Python 3.11+** (for the daemon)
- **Node.js 18+** (for the React dashboard)
- **pip** or **uv** for Python package management

## Getting Started

```bash
# Clone the repository
git clone https://github.com/astafford8488/ANAH.git
cd ANAH

# Set up environment
cp .env.example .env
# Edit .env and add your ANTHROPIC_API_KEY (required for L5 goal generation)

# Start the daemon
cd daemon
pip install -e .
anah start

# Start the dashboard (in a separate terminal)
cd dashboard
npm install && npm run dev
```

The daemon will begin running L1-L5 checks immediately. The dashboard connects via WebSocket and displays real-time status of all levels.

## License

MIT
