# Self-Hosted AI with Ollama — Technical Plan

This document defines how to replace (or supplement) paid third-party LLM APIs with **Ollama on your own infrastructure**, while keeping the existing product stack:

**React (`frontend`) → Laravel (`backend`) → FastAPI (`ai-agent`) → Ollama (GPU host)**

Related plans:

- Agent product features: `AGENT_PLATFORM_PLAN.md`
- Computer / desktop tools: `COMPUTER_INTERACTION_PLAN.md`

---

## Executive summary

**Yes, this is possible.** Your codebase is already structured correctly: Laravel owns auth, persistence, and governance; `ai-agent` owns the LLM loop and tool execution. The main work is:

1. Add an **LLM provider abstraction** in `ai-agent` (Ollama primary, OpenAI optional fallback).
2. Deploy **Ollama on a GPU host** and point `ai-agent` at it via OpenAI-compatible `/v1`.
3. Split **inference** (VPS/GPU) from **computer actions** (local runner on the user’s Mac) per `COMPUTER_INTERACTION_PLAN.md` Phase 0.
4. Wire existing Laravel **permissions, approvals, memory, tasks, and traces** into the agent loop (per `AGENT_PLATFORM_PLAN.md`).

Self-hosting eliminates per-token API bills but trades them for **hardware capex/opex, ops burden, and lower peak model quality** on smaller GPUs.

---

## 1. Feasibility, limitations, and tradeoffs

### What works well on Ollama

| Capability | Feasibility | Notes |
|------------|-------------|-------|
| General chat | High | 7B–14B models are good for Q&A and drafting |
| Tool / function calling | Medium–High | Qwen2.5, Llama 3.1+, Mistral-Nemo support tools; quality varies vs GPT-4 class |
| Coding assistance | Medium–High | `qwen2.5-coder`, `deepseek-coder-v2`, `codellama` — strong for many tasks, weaker on large refactors |
| Embeddings | High | `nomic-embed-text`, `bge-m3` via Ollama |
| Agent loops | Medium | Your existing `agent_chat` loop maps directly; more rounds = more latency |
| RAG | High | Local embed + pgvector/Qdrant; no API cost |
| Privacy / data residency | High | Prompts never leave your network |

### Hard limitations

| Limitation | Impact | Mitigation |
|------------|--------|------------|
| **No frontier reasoning** | o1/GPT-5-class multi-step reasoning unavailable locally at same quality | Reserve external API for “hard” tasks; use smaller models for routine work |
| **Context length** | 8k–32k typical on consumer GPUs; 128k needs large VRAM or CPU offload (slow) | Summarization, RAG, truncate (you already have `truncate_context`) |
| **Throughput** | One GPU serves limited concurrent users | Queue jobs, model routing, multiple Ollama instances |
| **Vision** | Needs vision models + more VRAM (`llava`, `qwen2-vl`) | Phase later; browser screenshots as images |
| **Computer tools locality** | VPS Ollama cannot drive Word/Cursor on user laptop | **Local runner** architecture (see §8) |
| **Tool-call reliability** | Smaller models hallucinate tools or bad JSON | Stricter schemas, retry parsing, governance pre-checks |
| **Ops** | You own uptime, drivers, CUDA, model updates | Health checks, monitoring, pinned model versions |

### Cost tradeoff (rule of thumb)

- **Break-even vs OpenAI**: Often favorable above ~$200–500/month API spend *if* you already have or can justify a GPU server.
- **Hidden costs**: Engineer time, electricity, backups, monitoring, failover hardware.
- **Sweet spot**: Internal team / product with predictable volume, privacy requirements, or agent workloads that run 24/7.

---

## 2. Target architecture

### Logical view

```
┌─────────────┐     HTTPS/WSS      ┌──────────────────────────────────────┐
│   React     │ ◄────────────────► │  Laravel (backend)                   │
│  frontend   │   Sanctum JWT      │  Auth, conversations, tasks, memory, │
└─────────────┘                    │  permissions, approvals, activity log  │
                                   └──────────────┬───────────────────────┘
                                                  │ internal HTTP + API key
                                                  ▼
                                   ┌──────────────────────────────────────┐
                                   │  FastAPI (ai-agent)                  │
                                   │  LLM provider abstraction            │
                                   │  Agent loop + tool orchestration     │
                                   │  Policy preflight → Laravel          │
                                   └──────┬──────────────────┬────────────┘
                                          │                  │
                          OpenAI-compat   │                  │ tool jobs (if split)
                          /v1/chat        │                  ▼
                                          ▼         ┌────────────────────┐
                                   ┌─────────────┐  │ Local runner (Mac) │
                                   │   Ollama    │  │ tool_executor.py   │
                                   │  GPU host   │  │ browser, cursor,   │
                                   └─────────────┘  │ terminal, files    │
                                                    └────────────────────┘
```

### Deployment topology (recommended)

| Tier | Host | Services |
|------|------|----------|
| **Edge** | VPS (CPU, 4–8 GB RAM) | Nginx/Caddy, Laravel, Redis, queue worker, SQLite/Postgres |
| **Inference** | GPU server (dedicated or same VPS if GPU) | Ollama, optional second `ai-agent` instance colocated |
| **Orchestration** | Same as edge or GPU box | `ai-agent` (light CPU; talks to Ollama over private network) |
| **Desktop** | User Mac | Local runner agent (thin FastAPI or daemon) for computer tools |

**Network**: Ollama must **not** be public. Bind to private IP or `127.0.0.1` + SSH tunnel / WireGuard / VPC only.

### LLM provider abstraction (new module)

Introduce `ai-agent/services/llm/`:

```
llm/
  base.py          # LLMProvider protocol: chat(), chat_with_tools(), embed(), health()
  ollama.py        # OpenAI SDK → base_url=OLLAMA_BASE_URL/v1
  openai.py        # Current behavior (fallback)
  router.py        # Model routing + fallback policy
```

**Minimal change path**: Ollama’s API is OpenAI-compatible. Initial MVP can set:

```python
OpenAI(base_url=f"{OLLAMA_BASE_URL}/v1", api_key="ollama")
```

Refactor `AIService` to inject `LLMProvider` instead of hard-coding OpenAI.

---

## 3. Modules and services to build

### 3.1 Infrastructure services

| Service | Purpose | Priority |
|---------|---------|----------|
| **Ollama** | Model serving | P0 |
| **Redis** | Laravel queue, rate limits, session cache | P0 |
| **Postgres** (upgrade from SQLite for prod) | App DB + pgvector | P1 |
| **Vector store** | pgvector or Qdrant for RAG | P2 |
| **Nginx/Caddy** | TLS, reverse proxy, rate limit | P0 |

### 3.2 Application modules (mapped to repo)

| Module | Location | Responsibility |
|--------|----------|----------------|
| **LLM provider layer** | `ai-agent/services/llm/` | Ollama/OpenAI/fallback, streaming |
| **Model router** | `ai-agent/services/llm/router.py` | Route by task type: chat, code, embed |
| **Agent runtime** | `ai-agent/services/ai_service.py` | Refactor to use provider; keep tool loop |
| **Tool policy client** | `ai-agent/services/policy_client.py` | Call Laravel before `execute_tool_action` |
| **Local runner client** | `ai-agent/services/runner_client.py` | Delegate computer tools to Mac |
| **Memory injector** | `backend/app/Services/MemoryContextService.php` | Load memories for `/chat/agent` |
| **Tool policy service** | `backend/app/Services/ToolPolicyService.php` | Central allow/deny/confirm |
| **Trace persistence** | Laravel migrations + `ai-agent` writer | Replace in-memory traces |
| **Embedding pipeline** | `ai-agent/services/embeddings.py` + Laravel jobs | Chunk, embed, store |
| **Inference gateway** (optional) | Thin wrapper in front of Ollama | Auth, quotas, request logging |

### 3.3 New Laravel API surfaces (internal)

| Endpoint | Consumer | Purpose |
|----------|----------|---------|
| `POST /api/internal/policy/evaluate` | `ai-agent` | Tool allow/deny/confirm before execution |
| `POST /api/internal/traces` | `ai-agent` | Persist trace events |
| `GET /api/internal/users/{id}/memories` | `ai-agent` | Memory block for prompts |
| `POST /api/internal/runner/jobs` | Local runner | Poll or push tool jobs |

Protect with `AI_SERVICE_API_KEY` + IP allowlist middleware.

---

## 4. Hardware recommendations

### Ollama inference (GPU)

| Profile | GPU | VRAM | RAM | Storage | Typical models | Concurrent chat |
|---------|-----|------|-----|---------|----------------|-----------------|
| **Dev / MVP** | RTX 4060 Ti 16GB or Apple M2 Pro 16GB unified | 16 GB | 32 GB | 500 GB NVMe | 7B–8B Q4, embed  | 1–2 users |
| **Team (5–15 users)** | RTX 4090 / A5000 | 24 GB | 64 GB | 1 TB NVMe | 14B Q4 + 7B embed | 3–5 light |
| **Production** | A100 40GB / L40S 48GB | 40–48 GB | 128 GB | 2 TB NVMe | 32B Q4 or 70B Q2 | 5–10 with queue |
| **Budget CPU-only** | — | — | 64–128 GB | 1 TB | 7B Q4 very slow | Demo only |

**Guidelines:**

- **VRAM ≈ model size × quant factor** (7B Q4 ≈ 5 GB; 14B Q4 ≈ 9 GB; 32B Q4 ≈ 20 GB).
- Keep **~2 GB headroom** for context KV cache.
- Run **one primary chat model + one small embed model**; avoid loading many models at once (`OLLAMA_MAX_LOADED_MODELS=2`).
- **NVMe** matters for model load time (first request after idle).

### App / Laravel tier (CPU)

| Resource | Minimum | Recommended |
|----------|---------|-------------|
| vCPU | 2 | 4 |
| RAM | 4 GB | 8 GB |
| Disk | 40 GB SSD | 80 GB SSD |

SQLite is fine for single-node dev; use **Postgres** for production (tasks, traces, vectors).

### Local runner (user Mac)

No GPU required; same machine as today where `tool_executor.py` runs.

---

## 5. Model recommendations

Pin versions in Ollama (`ollama pull <model>`) and document in `.env.example`.

### General chat

| Model | Size | Why |
|-------|------|-----|
| **qwen2.5:14b** | 14B | Strong all-rounder, good tool use |
| **llama3.1:8b** | 8B | Fast, solid English chat |
| **mistral-nemo:12b** | 12B | Good instruction following |

**Default for Wayda chat**: `qwen2.5:14b` (GPU ≥ 16 GB) or `llama3.1:8b` (smaller GPU).

### Coding

| Model | Size | Why |
|-------|------|-----|
| **qwen2.5-coder:14b** | 14B | Best balance for agentic coding |
| **deepseek-coder-v2:16b** | 16B | Strong code generation |
| **codellama:13b** | 13B | Lighter fallback |

**Route coding tasks** (detect keywords or user setting) to coder model via `router.py`.

### Tool use / agents

| Model | Notes |
|-------|-------|
| **qwen2.5:14b** | Reliable function JSON in practice |
| **llama3.1:8b-instruct** | Acceptable for simple tool loops |
| Avoid | Tiny models (&lt;7B) for multi-step `execute_tool` loops |

Enable Ollama tool calling (model-dependent). Test your exact `AGENT_TOOLS` schema with chosen model before production.

### Embeddings

| Model | Dims | Why |
|-------|------|-----|
| **nomic-embed-text** | 768 | Fast, good general retrieval |
| **bge-m3** | 1024 | Multilingual, strong recall |
| **mxbai-embed-large** | 1024 | Alternative |

Use **one** embed model consistently for index + query.

### Vision (later)

| Model | VRAM need |
|-------|-----------|
| **llava:13b** | High |
| **qwen2-vl:7b** | Medium |

Needed for `browser.screenshot` reasoning (Computer plan Phase 2).

---

## 6. Internal API design

### Principles

1. **Laravel is the product API** — clients never call Ollama directly.
2. **`ai-agent` is the AI gateway** — single place for prompts, tools, streaming.
3. **Ollama is private infrastructure** — only `ai-agent` (and admin) reach it.
4. **Idempotent tool execution** — `task_id` + `tool_call_id` for dedup.
5. **Structured observability** — every LLM call and tool action emits events.

### Existing endpoints (keep)

| Endpoint | Role |
|----------|------|
| `POST /chat` | Fast chat, no tools |
| `POST /chat/agent` | Default product path (tools) |
| `POST /tools/execute` | Manual / approved execution |
| `POST /tasks/plan`, `/tasks/execute` | Autonomous tasks |
| `GET /health`, `/traces/{id}` | Ops |

### Extend request schema (`AgentChatRequestSchema`)

```json
{
  "messages": [...],
  "task_id": "optional-uuid",
  "max_tool_rounds": 8,
  "context": {
    "user_id": 1,
    "memories": [{"key": "tone", "value": "formal"}],
    "model_profile": "chat|code|fast",
    "rag_collection_ids": []
  },
  "options": {
    "temperature": 0.7,
    "stream": false
  }
}
```

### Extend response schema

```json
{
  "response": "...",
  "model": "qwen2.5:14b",
  "provider": "ollama",
  "tokens_used": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
  "tool_actions": [...],
  "metadata": {
    "finish_reason": "stop",
    "trace_id": "uuid",
    "latency_ms": 4200,
    "fallback_used": false
  }
}
```

Note: Ollama may not return accurate token counts; estimate or instrument locally.

### New endpoints (ai-agent)

| Method | Path | Purpose |
|--------|------|---------|
| `GET` | `/models` | List available models + health |
| `POST` | `/embed` | Batch embeddings for RAG jobs |
| `GET` | `/chat/agent/stream` | SSE token stream (Phase 2) |

### Configuration (`ai-agent/.env`)

```bash
LLM_PROVIDER=ollama                    # ollama | openai | router
OLLAMA_BASE_URL=http://gpu-internal:11434
OLLAMA_MODEL=qwen2.5:14b
OLLAMA_CODER_MODEL=qwen2.5-coder:14b
OLLAMA_EMBED_MODEL=nomic-embed-text
OPENAI_API_KEY=                        # optional fallback
OPENAI_MODEL=gpt-4o-mini
LLM_FALLBACK_ENABLED=true
LLM_FALLBACK_ON=timeout,rate_limit,health_fail
```

---

## 7. Agentic AI: tools, memory, permissions, logs, safety

### 7.1 Tool / function calling (current → target)

**Today** (`ai_service.py`):

- OpenAI `tools` + `tool_choice=auto`
- Single meta-tool `execute_tool` → `ToolExecutor`

**Target**:

1. Keep meta-tool pattern (works across models).
2. Add **JSON repair** retry if model returns malformed arguments.
3. **Preflight policy** call to Laravel before execution:

```python
policy = policy_client.evaluate(user_id, tool, action, payload)
if policy == "deny": raise ...
if policy == "confirm": create ApprovalRequest; pause loop
```

4. Optionally split into **multiple function definitions** as models improve (e.g. `browser_navigate`, `file_read`).

### 7.2 Memory

| Layer | Implementation |
|-------|----------------|
| **Short-term** | Conversation messages in DB (existing) |
| **Working** | `truncate_context` + summarization job (Platform plan Phase 1) |
| **Long-term** | `ai_memory` table → inject top-N by `importance` into `context.memories` |
| **Semantic** | Embed memories; retrieve top-k by cosine similarity (Phase 7 RAG) |

### 7.3 Permissions

Wire `permissions` table (`scope`: `tool|domain|folder`) into `ToolPolicyService`:

| Risk class | Examples | Default |
|------------|----------|---------|
| `read` | `file.read`, `browser.read` | Allow |
| `write` | `file.write`, `document.create_xlsx` | Confirm |
| `exec` | `terminal.exec` | Deny / strict allowlist |
| `network` | `browser.navigate` | Allow with domain rules |
| `gui` | `cursor.prompt`, future GUI | Confirm |

Replace global `X-Approval-Token` with **per-action** `ApprovalRequest` rows (Platform plan Phase 3).

### 7.4 Logs and traces

| Event | Store |
|-------|-------|
| LLM request/response (redacted) | `agent_trace_events` |
| Tool call + result | `task_logs` + trace events |
| Policy decisions | `activity_logs` |
| User-visible | Tasks UI, Automation monitor |

Persist traces in DB (Platform plan Phase 4); stop relying on `execution_traces` dict.

### 7.5 Safety controls

- **Tool allowlist**: `ALLOWED_TOOL_ACTIONS` (existing).
- **Path jail**: workspace/project scoping (existing in `tool_executor.py`).
- **Command allowlist**: terminal tiers (Computer plan Phase 3).
- **URL blocklist**: internal IPs, `file://`, metadata endpoints.
- **Output redaction**: strip API keys, tokens from logs.
- **Max tool rounds**: `AGENT_MAX_TOOL_ROUNDS` (existing).
- **Timeouts**: per LLM call and per tool execution.
- **Human approval** for destructive actions.
- **Kill switch**: env `AGENT_ENABLED=false` + admin UI.

---

## 8. Integration with existing system control

Your system control lives in `tool_executor.py` namespaces:

| Namespace | Integration |
|-----------|-------------|
| `browser.*` | Playwright on local runner |
| `file.*` | Workspace/project paths |
| `terminal.exec` | Sandboxed subprocess |
| `system.inspect` | Ports, processes, Cursor terminals |
| `media.*` | Local VLC/IINA |
| `cursor.*` | Local Cursor automation |

### Runtime split (required for VPS Ollama)

```
User message → Laravel → ai-agent (GPU VPS)
                              │
                    LLM decides tool call
                              │
              ┌───────────────┴───────────────┐
              │ local-only tool?              │
              └───────────────┬───────────────┘
                    yes       │        no
                      ▼       │         ▼
              Local runner    │   Execute on VPS
              on user Mac     │   (e.g. HTTP fetch only)
```

**Local runner contract** (minimal):

```
POST /runner/v1/jobs        # ai-agent enqueues
GET  /runner/v1/jobs/{id}   # poll result
Headers: Authorization: Bearer <runner_secret>
```

Implement `runner_client.py` in `ai-agent`; thin FastAPI on Mac reuses `ToolExecutor`.

### Laravel system control hooks

- `SystemController::health` — extend to check Ollama via `ai-agent` `/health`.
- `TaskController` + `ExecuteAiTaskJob` — call real `agent_chat`, not summary stub.
- `ActivityController` — log tool and LLM events.

---

## 9. Security controls (AI with system access)

### Threat model

| Threat | Control |
|--------|---------|
| Prompt injection → arbitrary shell | Tool allowlist, policy service, no raw shell |
| SSRF via browser tools | URL allowlist, block RFC1918 |
| Data exfiltration | Egress rules, log review, DLP on workspace |
| Stolen API keys | Rotate `AI_SERVICE_API_KEY`, short-lived runner tokens |
| Privilege escalation | Sanctum roles; admin-only permission edits |
| Ollama exposed to internet | Private network only; no public port 11434 |
| Supply chain (models) | Pin model hashes; pull from official Ollama library |

### Required controls checklist

- [ ] TLS everywhere (Caddy/Let’s Encrypt)
- [ ] Sanctum auth on all product APIs
- [ ] Service-to-service API keys (`AI_SERVICE_API_KEY`, `BACKEND_API_KEY`)
- [ ] Separate **runner secret** per machine
- [ ] IP allowlist for internal endpoints
- [ ] Rate limiting (`throttle:high-cost-ai` on messages — extend for GPU cost)
- [ ] Audit log for tool exec + approvals
- [ ] Secrets not in prompts or trace storage
- [ ] Principle of least privilege on VPS (non-root containers)
- [ ] Regular model + dependency updates

---

## 10. Phased implementation roadmap

### Phase 0 — Ollama MVP (1–2 weeks)

**Goal**: Chat works on self-hosted model; no product behavior regression.

| Task | Owner |
|------|-------|
| Provision GPU host; install Ollama | Infra |
| Pull `qwen2.5:14b` (or `llama3.1:8b`) | Infra |
| Add `LLM_PROVIDER`, `OLLAMA_*` to `config.py` | `ai-agent` |
| Refactor `AIService` to use configurable `base_url` | `ai-agent` |
| Update `health_check` to ping Ollama `/api/tags` | `ai-agent` |
| Docker Compose: `ollama` + `ai-agent` + `backend` + `redis` | Infra |
| Manual test: `POST /chat` and `/chat/agent` | QA |

**Acceptance**: Frontend chat returns responses from Ollama; health shows `ai_service_ready: true`.

### Phase 1 — Provider router + fallback (1 week)

| Task | Details |
|------|---------|
| `llm/router.py` | Route `model_profile` to chat vs coder model |
| Fallback to OpenAI | On timeout / health fail if `LLM_FALLBACK_ENABLED` |
| Token/latency metadata | Log even if estimated |

### Phase 2 — Platform alignment (2–3 weeks)

Align with `AGENT_PLATFORM_PLAN.md` Phases 1–2:

- Memory injection into agent prompts
- Honest task execution via `agent_chat`
- Basic trace persistence

### Phase 3 — Governance + local runner (2–3 weeks)

Align with Platform Phase 3 + Computer Phase 0:

- `ToolPolicyService` + preflight from Python
- Local runner for Mac tools while Ollama on VPS
- Per-action approvals in UI

### Phase 4 — Production hardening (2 weeks)

- Postgres migration
- Nginx/Caddy TLS
- Prometheus/Grafana or Laravel Pulse + Ollama metrics
- Queue workers for long tasks
- Model version pinning in deploy

### Phase 5 — RAG + embeddings (3–4 weeks)

Align with Platform Phase 7:

- `POST /embed` + pgvector
- Document upload pipeline
- `retrieval.search` internal step

### Phase 6 — Streaming + scale (ongoing)

- SSE streaming to frontend
- Multiple Ollama replicas + load balancer
- Request queue when GPU saturated

---

## 11. Recommended stack

| Layer | Recommendation | Notes |
|-------|----------------|-------|
| **Frontend** | React + Vite (existing) | Add SSE client for streaming |
| **Backend** | Laravel 11 + Sanctum (existing) | Product API, governance |
| **AI gateway** | FastAPI + uvicorn (existing) | Provider abstraction |
| **LLM runtime** | **Ollama** | OpenAI-compatible `/v1` |
| **Queue** | **Redis** + Laravel Horizon | GPU-bound jobs must queue |
| **Database** | **PostgreSQL** (prod) | SQLite OK for dev |
| **Vector DB** | **pgvector** extension | Simpler ops; or Qdrant if scale |
| **Cache** | Redis | Model list, policy cache |
| **Monitoring** | Prometheus + Grafana, or Datadog | GPU util, Ollama queue depth, p95 latency |
| **Logging** | Structured JSON → Loki or CloudWatch | Correlate `trace_id` |
| **Auth** | Sanctum (users), Bearer tokens (services) | |
| **Deployment** | Docker Compose (MVP) → **Docker Swarm or k8s** | GPU node labels for Ollama |
| **Reverse proxy** | **Caddy** (auto TLS) or Nginx | Rate limit `/api/conversations/*/messages` |
| **Containerization** | Multi-stage Dockerfiles per service | `nvidia-container-toolkit` on GPU host |

### Example Compose services (skeleton)

```yaml
services:
  ollama:
    image: ollama/ollama:latest
    deploy:
      resources:
        reservations:
          devices:
            - capabilities: [gpu]
    volumes:
      - ollama_data:/root/.ollama
    networks: [internal]

  ai-agent:
    build: ./ai-agent
    environment:
      LLM_PROVIDER: ollama
      OLLAMA_BASE_URL: http://ollama:11434
    depends_on: [ollama]
    networks: [internal, app]

  backend:
    build: ./backend
    depends_on: [postgres, redis]
    networks: [app]

  redis:
    image: redis:7-alpine

  postgres:
    image: pgvector/pgvector:pg16
```

---

## 12. Cost, performance, and external API fallback

### Performance expectations (indicative)

| Model | GPU | Tokens/sec | 500 token reply |
|-------|-----|------------|-----------------|
| llama3.1:8b Q4 | RTX 4090 | ~80–120 | ~5 s |
| qwen2.5:14b Q4 | RTX 4090 | ~40–70 | ~8 s |
| qwen2.5:14b Q4 | RTX 4060 Ti | ~25–40 | ~15 s |
| 7B CPU only | — | ~3–8 | 60–180 s |

Agent loops multiply latency: **8 tool rounds × 10 s ≈ 80 s** — use queue + UI progress.

### Cost comparison (monthly, rough)

| Option | Cost drivers |
|--------|--------------|
| OpenAI API only | $0.15–$15 per 1M tokens (model-dependent); spikes with agents |
| Self-hosted RTX 4090 server | ~$150–400 cloud GPU or ~$2k hardware + power |
| Hybrid | Baseline on Ollama; peak on API |

### When to keep external API fallback

| Scenario | Use external API |
|----------|------------------|
| Ollama down or overloaded | Yes — `LLM_FALLBACK_ENABLED` |
| Complex reasoning / architecture design | Optional premium route |
| Highest-quality coding on huge repos | Cursor/cloud coder APIs |
| Unsupported modality (latest vision/audio) | Yes |
| Burst traffic beyond GPU capacity | Yes — queue or fallback |

**Router policy example**:

```
if health(ollama) == fail: use openai
elif task.priority == critical and queue_depth > 5: use openai
elif model_profile == code and vram_pressure: use openai_codex
else: use ollama
```

### Cost controls (self-hosted)

- Queue long tasks; don’t block HTTP workers on GPU
- Cap `max_tool_rounds` and context length
- Per-user daily token budget (estimated) in Laravel
- Smaller model for planning, larger for final answer (cascade)
- Unload idle models (`OLLAMA_KEEP_ALIVE=5m`)

---

## Code change map (first PR)

| File | Change |
|------|--------|
| `ai-agent/config.py` | `LLM_PROVIDER`, `OLLAMA_BASE_URL`, `OLLAMA_MODEL` |
| `ai-agent/services/llm/ollama.py` | New provider |
| `ai-agent/services/ai_service.py` | Inject provider; generic health check |
| `ai-agent/.env.example` | Document Ollama vars |
| `backend/config/services.php` | Optional `ai.provider` metadata for health UI |
| `backend/app/Http/Controllers/SystemController.php` | Surface Ollama status |
| `docker-compose.yml` | New — Ollama + services |

---

## Status tracker

| Phase | Status | Target |
|-------|--------|--------|
| 0 Ollama MVP | Not started | — |
| 1 Provider router + fallback | Not started | — |
| 2 Platform alignment | Not started | See `AGENT_PLATFORM_PLAN.md` |
| 3 Governance + local runner | Not started | See `COMPUTER_INTERACTION_PLAN.md` |
| 4 Production hardening | Not started | — |
| 5 RAG + embeddings | Not started | — |
| 6 Streaming + scale | Not started | — |

---

## Decision log

| Date | Decision | Rationale |
|------|----------|-----------|
| 2026-06-18 | Ollama via OpenAI-compatible client for MVP | Minimal diff in `AIService` |
| 2026-06-18 | Split inference VPS vs local runner | Computer tools require user machine |
| 2026-06-18 | Postgres + pgvector for prod | Single DB for app + vectors |
| 2026-06-18 | qwen2.5 family as default | Strong tool use + coding balance |

---

## References

- [Ollama OpenAI compatibility](https://github.com/ollama/ollama/blob/main/docs/openai.md)
- [Ollama tool calling](https://ollama.com/blog/tool-support)
- Existing env: `ai-agent/.env.example`, `backend/.env.example`
