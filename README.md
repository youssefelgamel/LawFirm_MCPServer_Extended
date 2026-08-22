# Ashfords & Kane Law Firm — Intelligent Case Intake & Assignment System

[![Tests](https://img.shields.io/badge/tests-pytest-blue)](https://github.com/)
[![License](https://img.shields.io/badge/license-MIT-lightgrey)](LICENSE)

A secure, audited intake workflow for legal case intake and assignment, built around a Model Context Protocol (MCP) server. The server exposes a small set of guarded tools so an AI assistant can help intake staff without gaining direct, unrestricted access to sensitive firm data.

## Table of Contents

- [Overview](#overview)
- [Quick Start](#quick-start)
- [Architecture](#architecture)
- [MCP Tools](#mcp-tools)
- [Conflict Clearance Workflow](#conflict-clearance-workflow)
- [Configuration & Environment](#configuration--environment)
- [Tests & Benchmarks](#tests--benchmarks)
- [Troubleshooting & Common Pitfalls](#troubleshooting--common-pitfalls)
- [Important Files](#important-files)
- [Contributing](#contributing)
- [License & Contact](#license--contact)

## Overview

This repository contains:

- A Python-based MCP server (core logic, tools, memory & retrieval subsystems).
- A LangGraph-driven **Conflict Clearance** workflow with human-in-the-loop partner sign-off, crash-safe checkpointing, and a ticketing path for external service failures.
- A context-evaluation harness to compare and benchmark context strategies and RAG configurations.
- A small Next.js demo UI (`lawfirm-ui`) for interactive experiments.
- DB schema and seed scripts to reproduce demo datasets.

## Quick Start

### Prerequisites

- Python 3.10+
- pip
- Node.js (optional — only for the demo UI)

### Setup

**Windows (PowerShell):**
```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

**macOS / Linux:**
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### Initialize the demo database (optional)

```bash
python db/init_db.py
```

### Run the MCP server

```bash
python -m mcp_server.server
```

### Run the context evaluation (produces CSV results)

```bash
python -m context_eval.run_eval
```

### Run the demo UI (optional)

```bash
cd lawfirm-ui
npm install
npm run dev
# open http://localhost:3000
```

### Run tests

```bash
pytest
```

## Architecture

The system is built from a few distinct layers:

- **MCP tool layer** — a small, audited interface of read-only and guarded write tools (see [MCP Tools](#mcp-tools)). Tools that need information not yet provided use MCP's elicitation mechanism to ask for it interactively, rather than failing outright.
- **Conflict Clearance graph** — a LangGraph state machine that runs every new case through search, risk evaluation, policy retrieval, and partner sign-off before it's cleared or rejected. See [Conflict Clearance Workflow](#conflict-clearance-workflow) for details.
- **Memory pipeline** — short-term buffers routed through decision logging into consolidated semantic and history stores.
- **Retrieval layer** — multiple interchangeable strategies (Naive, Hybrid, Agentic, Graph) for pulling relevant context.

**Conversation flow (conceptual):**
```
User / agent turn → RollingBuffer (short-term)
                       │
                       ▼
               MemoryRouter → (forget | episodic_store.json)
                       │ (decisions logged)
                       ▼
                MemoryConsolidator → semantic_store.json + history_store.json
```

**Retrieval flow (conceptual):**
```
Agent query → Retrieval strategy (Naive | Hybrid | Agentic | Graph)
            → VectorStore / BM25 / Graph → returned chunks → summarizer/decision
```

## MCP Tools

All tools live in `mcp_server/tools.py` and are registered against the single shared `mcp` instance in `mcp_server/mcp_instance.py`.

| Tool | Purpose |
|---|---|
| `database_health` | Confirms the DB connection is live and returns row counts per table. |
| `get_client` | Looks up a client by `party_id`. |
| `get_case` | Looks up full case detail, joined with client name and case type. |
| `get_lawyer` | Looks up a lawyer's profile and caseload. |
| `get_conflict_checks` | Returns conflict-check results for a case. |
| `accept_case` | Accepts a case; unlocks `assign_case_to_lawyer`. |
| `reject_case` | Rejects a case with a recorded reason. |
| `assign_case_to_lawyer` | Assigns an accepted case to a lawyer, enforcing status and caseload limits. |

Several tools (`accept_case`, `reject_case`, `assign_case_to_lawyer`) use an elicitation pattern via `require_fields(ctx, ...)`: if a required argument is missing, the tool prompts the calling agent/UI for it through `ctx.elicit(...)` instead of erroring out.

## Conflict Clearance Workflow

The core case-review process is a LangGraph graph (`state_graph/conflict_clearance/graph.py`):

```
intake → decompose_conflict_check → search → evaluate → retrieve_policy → draft_memo → partner_signoff → cleared / rejected
```

- **Human-in-the-loop sign-off**: when `evaluate` produces a risk score above threshold, `partner_signoff` raises a LangGraph `interrupt()`, pausing the run until a partner records an `approve`/`reject` decision.
- **Crash safety**: every step is checkpointed to SQLite via a custom `DBCheckpointSaver`. If the process dies mid-run, restarting and resuming with the same `thread_id` continues exactly where it left off — no re-run of completed steps.
- **External service failures**: the `search` node calls an external conflict-search service. A timeout or malformed response is *not* treated as a HITL decision — it's caught, logged as an open row in the `tickets` table (with the last-good checkpoint ID attached), and the run halts. Resolving the ticket via `resume_from_ticket()` resumes the graph from that checkpoint, re-entering `search` rather than restarting from `intake`.

## Configuration & Environment

Common environment variables used by the project (no secrets in source):

- `DATABASE_URL` — path or connection string for the DB (e.g. `sqlite:///./db/lawfirm.db`).
- `ENV` — runtime environment (`development`, `testing`, `production`).
- `LOG_LEVEL` — `DEBUG`, `INFO`, `WARN`, `ERROR`.
- `NEXT_PUBLIC_API_URL` — URL the demo UI uses for API calls when running locally.

If additional environment variables are required by a specific integration, they're documented near the integration code (search for `os.environ` usages).

## Tests & Benchmarks

- Full suite: `pytest`
- Checkpointer + Conflict Clearance graph: `pytest tests/test_checkpointer.py tests/test_conflict_clearance.py -v`
- MCP elicitation flow (accept/reject/assign, interactive): `python tests/mcp_server_elicitation_test.py`
- MCP tool registration smoke test: `python smoke_test.py`
- Memory routing tests: `pytest mcp_server/memory/tests/test_router.py`
- Consolidation tests: `pytest mcp_server/memory/tests/test_consolidation.py`
- Context evaluation: `python -m context_eval.run_eval` → results in `context_eval/results/`

## Troubleshooting & Common Pitfalls

- **Missing DB**: run `python db/init_db.py` and inspect `db/schema.sql`.
- **Router appears not to write**: this is by design — router decisions are logged, and consolidation is responsible for promotions.
- **Retrieval problems when `hnswlib` is missing**: `VectorStore` falls back to a NumPy-based exact search. Install `hnswlib` if you need large-vector performance.
- **Smoke test reports 0/N tools registered**: check `mcp_server/tools.py` for a stray `mcp = FastMCP(...)` re-assignment after the `from .mcp_instance import mcp` import — this silently creates a second, orphaned MCP instance that decorators register against instead of the shared one.
- **A tool call fails with a signature error it shouldn't have** (e.g. unexpected keyword argument, or "multiple values for argument"): search for a duplicate `def` of that tool name elsewhere in `tools.py`. Python silently keeps the last definition in the file, so an old placeholder further down can shadow — and un-register — the real, decorated implementation above it.

## Important Files

- [`mcp_server/server.py`](mcp_server/server.py)
- [`mcp_server/tools.py`](mcp_server/tools.py)
- [`mcp_server/mcp_instance.py`](mcp_server/mcp_instance.py)
- [`mcp_server/memory/short_term.py`](mcp_server/memory/short_term.py)
- [`mcp_server/memory/router.py`](mcp_server/memory/router.py)
- [`mcp_server/memory/consolidation.py`](mcp_server/memory/consolidation.py)
- [`state_graph/conflict_clearance/graph.py`](state_graph/conflict_clearance/graph.py)
- [`state_graph/checkpointer.py`](state_graph/checkpointer.py)
- [`state_graph/tickets.py`](state_graph/tickets.py)
- [`context_eval/run_eval.py`](context_eval/run_eval.py)
- [`project_root/rag`](project_root/rag)
- [`db/schema.sql`](db/schema.sql)
- [`lawfirm-ui/README.md`](lawfirm-ui/README.md)

## Contributing

- Keep changes small and focused. Add tests, and update the context evaluation if behavior changes affect context strategies or retrieval.
- Preserve audit logs when changing routing or consolidation behavior.
- Before adding a new tool or graph node, check for existing definitions of the same name — see [Common Pitfalls](#troubleshooting--common-pitfalls).

## License & Contact

This repository uses the MIT license (see `LICENSE`). For questions about the project or design decisions, open an issue or contact the maintainers listed in the repository metadata.

---

*This README targets developers running, modifying, and extending the MCP server. If a shorter, non-technical README for stakeholders, or a longer step-by-step guide with API call examples, would be more useful, say which audience and which sections to expand.*
