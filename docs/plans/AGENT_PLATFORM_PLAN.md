# Agent Platform — Gap Analysis & Implementation Plan

This document covers **product and agent logic** that is **not** computer interaction (no new `browser.*` / `file.*` tools). For machine-facing tools (Word, Excel, shell, screenshots), see `COMPUTER_INTERACTION_PLAN.md`.

**Stack:** React (`frontend`) → Laravel (`backend`) → FastAPI (`ai-agent`).

---

## 1. Current baseline (what exists)

| Area | Status |
|------|--------|
| Auth, roles, Sanctum API | Implemented |
| Conversations & messages | Implemented; chat uses **`/chat/agent`** only |
| Tasks + queue job | Implemented; execution is **shallow** (summary, not full agent loop) |
| Memory CRUD | DB + UI; **not injected** into prompts |
| Approvals & permissions | DB + UI; **partial** enforcement (manual tool path only) |
| Notifications, activity logs | Implemented |
| Agent tool loop | `agent_chat` in `ai_service.py` with fixed tools |
| Traces | In-memory in Python; **lost on restart** |
| Realtime | React WebSocket client; **no Laravel broadcaster** wired |
| Simple `/chat` | Exists in API; **unused** by `MessageController` |

---

## 2. Gaps not covered (by category)

### 2.1 Memory & context

| Gap | Impact |
|-----|--------|
| Memories never sent to `ai-agent` | User “preferences” don’t affect replies |
| No auto-extraction from chats | No learning loop |
| No conversation summarization | Long threads hit `MAX_CONTEXT_LENGTH` with truncation only |
| No semantic retrieval | Keyword memory only (DB `key`/`value`) |

### 2.2 Knowledge & RAG

| Gap | Impact |
|-----|--------|
| No document ingestion | Cannot answer from PDFs/uploads |
| No vector store / embeddings | No “search my docs” |
| No codebase indexing tool | Dev questions lack repo context |

### 2.3 Autonomous tasks & planning

| Gap | Impact |
|-----|--------|
| `execute_task` ≠ real agent run | Tasks feel fake (3-line summary) |
| No persisted plan steps in DB | Cannot show step 1..N progress |
| No replan on failure | Single-shot behavior |
| No cancel / pause / resume | Long runs uncontrollable |

### 2.4 Human-in-the-loop (product layer)

| Gap | Impact |
|-----|--------|
| Chat tools use global approval token | Not per-action user confirm in UI |
| No pending tool UI in chat | User doesn’t see what will run |
| No mid-run cancel | — |

### 2.5 Tooling ecosystem (platform, not desktop)

| Gap | Impact |
|-----|--------|
| Single hard-coded tool schema | No plugins / MCP |
| No generic HTTP tool | Cannot call arbitrary APIs safely |
| No integration connectors | Gmail, Slack, etc. require custom Laravel code |

### 2.6 Multi-agent & reasoning

| Gap | Impact |
|-----|--------|
| One agent, one loop | No specialist sub-agents |
| No critic/reflection pass | — |
| No structured JSON output mode | — |

### 2.7 Realtime, streaming & chat UX

| Gap | Impact |
|-----|--------|
| Blocking HTTP until full reply | No token streaming |
| WebSocket not published from backend | `RealtimeContext` mostly idle |
| No attachments in messages | Images/files not in chat |
| No regenerate / edit message | — |
| Tool steps not surfaced clearly in chat UI | Metadata exists, UX thin |

### 2.8 Scheduling & triggers

| Gap | Impact |
|-----|--------|
| No Laravel `schedule()` jobs for agents | No “every morning” |
| No inbound webhooks | No GitHub/form → task |
| No event-driven task creation | Manual queue only |

### 2.9 Observability & operations

| Gap | Impact |
|-----|--------|
| Traces ephemeral | No post-mortem after restart |
| No per-user token/cost budgets | — |
| No prompt versioning | System prompt only in code |
| Health check doesn’t include memory/queue depth | Basic AI ping only |

### 2.10 Collaboration & multi-tenant

| Gap | Impact |
|-----|--------|
| Single-user isolation only | No teams/workspaces |
| No shared conversations | — |
| No per-tenant agent persona config | — |

---

## 3. Implementation phases

### Phase 1 — Memory in the loop

**Goal:** Stored memories change agent behavior.

| Task | Layer | Details |
|------|-------|---------|
| 1.1 | Laravel | `MessageController` / `AIService`: load top N memories by `importance` for user |
| 1.2 | API contract | Pass `context.memories[]` in `/chat/agent` payload |
| 1.3 | `ai-agent` | Inject into system prompt block in `agent_chat` / `chat` |
| 1.4 | UI | Optional: “pin memory” from chat |
| 1.5 | Later | Auto-suggest memories from conversation (background job) |

**Files:** `MessageController.php`, `AIService.php`, `ai_service.py`, `models/schemas.py`, `Chat.tsx`

**Acceptance:** User saves preference “always use formal tone” → next chat reflects it.

---

### Phase 2 — Honest task execution

**Goal:** Queued tasks run the real agent, not a summary stub.

| Task | Layer | Details |
|------|-------|---------|
| 2.1 | `ai-agent` | `execute_task` calls `agent_chat` or dedicated step runner with goal |
| 2.2 | Laravel | Persist `trace_id`, tool actions in `ai_tasks.metadata` |
| 2.3 | DB migration | Optional `task_steps` table: `step_order`, `status`, `output` |
| 2.4 | Queue | Increase timeout; failed state with error message |
| 2.5 | UI | Tasks page shows steps and tool trace |

**Files:** `ai_service.py`, `ExecuteAiTaskJob.php`, `TaskController.php`, `Tasks.tsx`

**Acceptance:** Task “research X and write summary file” runs tools and completes with auditable log.

---

### Phase 3 — Governance unified

**Goal:** Same policy for chat agent and manual tool execution.

| Task | Layer | Details |
|------|-------|---------|
| 3.1 | Laravel | `ToolPolicyService`: resolve allow/deny/confirm for `tool.action` |
| 3.2 | `ai-agent` | Before `execute_tool_action`, call policy API or shared rules file |
| 3.3 | Chat UX | High-risk tools create `ApprovalRequest`; pause until approved |
| 3.4 | Enforce `domain`/`folder` scopes | Map browser URL and file paths to policies |

**Files:** new `ToolPolicyService.php`, `PermissionController.php`, `tool_executor.py`, `Chat.tsx`, `AutomationMonitor.tsx`

**Acceptance:** Deny `terminal.exec` in DB → chat agent cannot run it.

---

### Phase 4 — Durable observability

**Goal:** Runs survive restarts and are searchable.

| Task | Layer | Details |
|------|-------|---------|
| 4.1 | DB | `agent_traces`, `agent_trace_events` tables |
| 4.2 | `ai-agent` | Write events on each tool round; stop using in-memory only |
| 4.3 | API | `GET /traces/{id}` backed by DB (or Laravel proxy) |
| 4.4 | UI | Automation monitor + task detail: timeline view |

**Files:** migration, `ai_service.py`, `main.py`, `AutomationMonitor.tsx`

**Acceptance:** Restart `ai-agent` → historical trace still visible.

---

### Phase 5 — Realtime & streaming

**Goal:** Responsive chat and live task updates.

| Task | Layer | Details |
|------|-------|---------|
| 5.1 | Laravel | Broadcasting (Reverb/Pusher) on message created / task status |
| 5.2 | Events | `MessageCreated`, `TaskStatusChanged` |
| 5.3 | `ai-agent` | Optional SSE endpoint for streamed tokens |
| 5.4 | Frontend | Stream tokens into chat bubble; subscribe tasks channel |

**Files:** `routes/channels.php`, event classes, `Chat.tsx`, `RealtimeContext.tsx`

**Acceptance:** Second client sees assistant message without refresh.

---

### Phase 6 — Triggers & automation (no n8n)

**Goal:** Event-driven agents inside Laravel.

| Task | Layer | Details |
|------|-------|---------|
| 6.1 | `routes/console.php` | Scheduled commands → dispatch tasks |
| 6.2 | Webhook route | Signed `POST /api/webhooks/{name}` → create task |
| 6.3 | UI | Admin: list schedules / webhook secrets |

**Acceptance:** Cron runs daily job; external POST creates task.

---

### Phase 7 — RAG & knowledge (optional, larger)

**Goal:** Answer from user documents.

| Task | Layer | Details |
|------|-------|---------|
| 7.1 | Storage | Upload endpoint + `documents` table |
| 7.2 | Pipeline | Chunk, embed (local or API), vector store |
| 7.3 | `ai-agent` | `retrieval.search` internal step before chat (not desktop tool) |
| 7.4 | UI | Knowledge library page |

**Defer until Phases 1–4 stable.**

---

### Phase 8 — Advanced agent patterns (optional)

| Task | Description |
|------|-------------|
| 8.1 | Sub-agents | Planner + executor roles in one request |
| 8.2 | Reflection | Second pass validates answer |
| 8.3 | Structured output | JSON schema for specific endpoints |
| 8.4 | MCP / plugins | Dynamic tool registration |

---

## 4. API & product modes

| Mode | Endpoint | When |
|------|----------|------|
| Fast chat (no tools) | `POST /chat` | Simple Q&A; lower risk |
| Agent chat | `POST /chat/agent` | Default product behavior today |
| Tool only | `POST /tools/execute` | Manual / approved runs |
| Task plan | `POST /tasks/plan` | UI wizard (future) |
| Task run | `POST /tasks/execute` | Queue worker |

**Deliverable:** `MessageController` option or user setting: `agent_mode: true|false`.

---

## 5. Priority matrix

| Priority | Phase | Effort | Depends on |
|----------|-------|--------|------------|
| P0 | 2 Honest tasks | High | Computer tools for real work (Phase 2 platform + computer plan) |
| P0 | 1 Memory in loop | Low | — |
| P1 | 3 Governance | Medium | Computer plan Phase 6 (aligned) |
| P1 | 4 Durable traces | Medium | — |
| P2 | 5 Realtime/streaming | Medium | — |
| P2 | 6 Triggers | Low–medium | Phase 2 |
| P3 | 7 RAG | High | — |
| P3 | 8 Multi-agent | High | — |

---

## 6. Cross-file coordination

| Topic | Computer plan | Platform plan |
|-------|---------------|---------------|
| Approvals in chat | Phase 6 governance | Phase 3 governance |
| Task execution | Tool actions | Phase 2 honest tasks |
| Traces | Tool event payloads | Phase 4 persistence |
| VPS vs laptop | Phase 0 runtime | Deploy config (out of scope here) |

Implement **governance** and **trace shape** once; both files reference the same event schema.

---

## 7. Suggested execution order (next 8–12 weeks)

```
Week 1–2:  Platform Phase 1 (memory) + Computer Phase 0 (runtime decision)
Week 3–4:  Computer Phase 1 (docx/xlsx/pdf + file ops)
Week 5–6:  Platform Phase 2 (honest tasks) + Computer Phase 2 (browser snapshot)
Week 7–8:  Platform Phase 3–4 (governance + traces)
Week 9+:   Platform Phase 5–6; Computer Phase 3 (dev shell) as needed
```

---

## 8. Status tracker

| Phase | Status | Notes |
|-------|--------|-------|
| 1 Memory in loop | Not started | |
| 2 Honest task execution | Not started | |
| 3 Governance unified | Not started | |
| 4 Durable observability | Not started | |
| 5 Realtime & streaming | Not started | |
| 6 Triggers & automation | Not started | |
| 7 RAG & knowledge | Not started | |
| 8 Advanced patterns | Not started | |

---

## 9. Related documents

- **Computer / desktop tools:** `docs/plans/COMPUTER_INTERACTION_PLAN.md`
- **Environment:** `ai-agent/.env.example`, `backend/.env.example`
