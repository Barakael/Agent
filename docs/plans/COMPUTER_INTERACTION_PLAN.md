# Computer Interaction — Gap Analysis & Implementation Plan

This document covers **machine-facing capabilities** only: tools that read or change the user’s computer (browser, files, shell, apps, documents). It excludes LLM provider choice, VPS hosting, and product features defined in `AGENT_PLATFORM_PLAN.md`.

**Primary code today:** `ai-agent/services/tool_executor.py`, `browser_automation.py`, `media_player.py`, `cursor_agent.py`, `tools.py`.

---

## 1. Current baseline (what exists)

| Namespace | Actions | Limits |
|-----------|---------|--------|
| `browser` | `navigate`, `read`, `type`, `click`, `search` | Playwright + HTTP `read`; Google/YouTube search helpers; CSS selectors required for type/click |
| `file` | `read`, `write` | UTF-8 text only; write **workspace** only; project scope **read-only** |
| `terminal` | `exec` | Fixed allowlist (`ls`, `grep`, `ps`, …); no `git`/`npm`/`python` |
| `system` | `inspect` | Ports, processes, project listing, Cursor terminal tails (macOS paths) |
| `media` | `play`, `search` | Local **video** in `ALLOWED_MEDIA_DIRS`; VLC/IINA/QuickTime (macOS) |
| `cursor` | `prompt`, `resume` | Local UI / CLI / SDK; macOS-heavy (`pbcopy`, AppleScript) |

**Architecture note:** Tools run where `ai-agent` runs. A VPS-hosted agent **cannot** control Word on the user’s laptop without a **local runner** (see Phase 0).

---

## 2. Gaps not covered (by category)

### 2.1 Documents & Office (your Word/Excel ask)

| Gap | Description |
|-----|-------------|
| No `.docx` / `.xlsx` / `.pptx` creation | Cannot produce Office files programmatically |
| No PDF read/write | Cannot ingest invoices, reports, exports |
| No “open in Word/Excel” | No `open` after file generation |
| No live Office automation | No COM (Windows) or AppleScript/JXA (Mac) control of installed apps |
| Browser-only Office | Google Docs/Sheets possible via existing browser tools but not first-class |

### 2.2 Files & filesystem

| Gap | Description |
|-----|-------------|
| No `list`, `copy`, `move`, `delete`, `mkdir` | Only read/write single text files |
| No project writes | Code changes must go to workspace, not `AGENT_PROJECT_ROOT` |
| No binary formats | Images, zip, Office, PDF not supported |
| No download/upload bridge | Browser cannot save files into workspace automatically |

### 2.3 Browser & “computer use”

| Gap | Description |
|-----|-------------|
| No screenshot / vision | Model does not receive page images |
| No accessibility/DOM snapshot tool | `browser.read` is HTTP fetch, not live Playwright state for all flows |
| No multi-tab / session profile | Single page context |
| No file picker / upload | Cannot complete “attach file” flows reliably |
| Limited interaction primitives | No scroll, drag-drop, select, iframe helpers |

### 2.4 Shell & development

| Gap | Description |
|-----|-------------|
| No dev command set | `git`, `npm`, `composer`, `docker`, `pytest` not allowlisted |
| No long-running process tool | Cannot start server and tail logs as a managed action |
| No SSH / remote exec | Cannot operate on VPS from local agent (or vice versa) cleanly |

### 2.5 Desktop GUI (non-browser)

| Gap | Description |
|-----|-------------|
| No generic app control | Word, Finder, Mail, Excel UI not driven |
| No OS-level keyboard/mouse | Except Cursor AppleScript path |
| No window management | Focus, resize, multi-display |

### 2.6 Communication & clipboard

| Gap | Description |
|-----|-------------|
| No clipboard read/write tool | Clipboard only used inside Cursor flow |
| No email / calendar / chat apps | No Mail, Outlook, Slack desktop tools |

### 2.7 Media & creative

| Gap | Description |
|-----|-------------|
| Video only | No audio/music, images, screen recording |
| No generate/export PDF from HTML/markdown | — |

### 2.8 Platform & deployment

| Gap | Description |
|-----|-------------|
| macOS-centric | `open`, `pbcopy`, `lsof`, AppleScript |
| No local runner protocol | VPS agent vs laptop desktop split undefined |
| Permissions `domain`/`folder` scopes | Stored in Laravel DB, **not enforced** in Python executor |
| Chat agent bypasses per-action UI approval | Global `X-Approval-Token` only |

---

## 3. Recommended tool namespaces (target shape)

Extend `execute_tool` with new namespaces (or sub-actions) over time:

```
browser.*     → screenshot, snapshot, scroll, select, download, upload
file.*        → list, copy, move, delete, mkdir, read_binary (scoped)
document.*    → create_docx, create_xlsx, create_pdf, read_pdf, open
terminal.*    → exec (tiered policy), tail_log, run_dev (approved)
app.*         → open, focus, quit (allowlisted apps)
clipboard.*   → read, write
office.*      → (optional Phase 4) automate_word, automate_excel — platform-specific
runner.*      → (architecture) delegate action to user machine agent
```

---

## 4. Implementation phases

### Phase 0 — Runtime model (prerequisite)

**Goal:** Clarify where computer actions execute.

| Option | Use when |
|--------|----------|
| **A. Co-located** | `ai-agent` runs on the same Mac as the user; current design |
| **B. Split** | API on VPS; **local runner** on Mac executes tools via signed queue |

**Deliverables:**

- [ ] Document chosen model in README / env (`AGENT_RUNTIME=local|remote`)
- [ ] If B: minimal runner HTTP or WebSocket contract (`POST /run-tool`, job id, result)
- [ ] Health check reports `runtime` and `platform` (darwin/linux)

**Files:** new `ai-agent/services/runner_client.py` (if B), `config.py`, `docs/plans/COMPUTER_INTERACTION_PLAN.md` (this file, status section)

---

### Phase 1 — Files & documents (high value, low risk)

**Goal:** Word/Excel-style output without installed Office.

| Task | Tool | Implementation notes |
|------|------|-------------------|
| 1.1 | `document.create_docx` | `python-docx`; output under workspace; return path |
| 1.2 | `document.create_xlsx` | `openpyxl`; sheets, headers, formulas as strings |
| 1.3 | `document.read_pdf` | `pypdf` or `pdfplumber`; text extract, page limit |
| 1.4 | `document.create_pdf` | `reportlab` or HTML→PDF; optional |
| 1.5 | `app.open` | macOS `open path`; Windows `start`; Linux `xdg-open` |
| 1.6 | `file.list` | Scoped list workspace/project |
| 1.7 | `file.copy` / `file.move` / `file.delete` | Path jail same as existing resolvers |

**Deliverables:**

- [ ] Handlers in `tool_executor.py`
- [ ] Enums + descriptions in `tools.py`
- [ ] `ALLOWED_TOOL_ACTIONS` defaults in `.env.example`
- [ ] Dependencies in `requirements.txt`
- [ ] Unit tests for path jail (no `..` escape)

**Acceptance:** User asks “create a Q1 report xlsx” → file appears in workspace → optional `app.open` opens Excel/Numbers.

---

### Phase 2 — Browser “see the page”

**Goal:** Agent can reason about what Playwright actually rendered.

| Task | Tool | Implementation notes |
|------|------|-------------------|
| 2.1 | `browser.screenshot` | Playwright PNG → base64 or save to workspace; max size cap |
| 2.2 | `browser.snapshot` | Main content text + list of interactive elements (aria/roles) |
| 2.3 | `browser.scroll` | `page.mouse.wheel` or `locator.scroll_into_view` |
| 2.4 | `browser.select` | `<select>` and common dropdown patterns |
| 2.5 | `browser.download` | Wait for download event → move into workspace |

**Deliverables:**

- [ ] Extend `browser_automation.py`
- [ ] Optional: return screenshot path in tool result for UI (future)

**Acceptance:** Agent navigates to a form, snapshots, fills fields, screenshots confirm.

---

### Phase 3 — Developer shell (policy-based)

**Goal:** Real coding agent workflows with safety.

| Task | Implementation notes |
|------|-------------------|
| 3.1 | `TERMINAL_POLICY=strict|dev|custom` env | strict = current allowlist |
| 3.2 | `dev` allowlist adds `git`, `npm`, `composer`, `python`, `php`, `node` | Still no raw `bash -c` unless approved |
| 3.3 | `file.write` to `project` scope | Optional flag `ALLOW_PROJECT_WRITE=true` + approval |
| 3.4 | `terminal.tail` | Tail file under project or Cursor terminals dir |

**Deliverables:**

- [ ] `tool_executor._terminal_exec` refactor
- [ ] Laravel permission check hook (optional callback HTTP) for destructive commands

**Acceptance:** “Run tests and show failures” works in repo root without manual copy-paste.

---

### Phase 4 — Office automation (optional, fragile)

**Goal:** Control installed Microsoft Office when library output is insufficient.

| Platform | Approach |
|----------|----------|
| macOS | AppleScript / JXA via `osascript` |
| Windows | `pywin32` COM automation |
| Linux | LibreOffice UNO or skip |

| Task | Tool |
|------|------|
| 4.1 | `office.word_insert_text` | Document must exist |
| 4.2 | `office.excel_set_range` | Cell range + values |
| 4.3 | Explicit **capability probe** | Fail fast if Office not installed |

**Deliverables:**

- [ ] Separate module `office_automation.py` (platform gates)
- [ ] Default **disabled**; enable via `OFFICE_AUTOMATION_ENABLED=false`

**Acceptance:** Only for users who opt in; documented breakage risk on Office updates.

---

### Phase 5 — Desktop GUI & clipboard (higher risk)

**Goal:** Broader app control when browser is not enough.

| Task | Tool | Notes |
|------|------|-------|
| 5.1 | `clipboard.read` / `clipboard.write` | Platform APIs; redact secrets in logs |
| 5.2 | `app.focus` | Allowlist: Cursor, Word, Excel, Finder, … |
| 5.3 | GUI automation (optional) | PyAutoGUI or Accessibility API; **admin approval required** |

**Deliverables:**

- [ ] Risk tier: `requires_confirmation` synced with Laravel `Permission` model

**Acceptance:** Dangerous actions blocked unless approval row exists (see platform plan).

---

### Phase 6 — Governance wired to computer tools

**Goal:** Same rules in chat and manual task execution.

| Task | Where |
|------|-------|
| 6.1 | Enforce Laravel `Permission` (tool/domain/folder) | Middleware or pre-flight HTTP from Python |
| 6.2 | Risk classes: `read`, `write`, `exec`, `network`, `gui` | Map each action |
| 6.3 | Per-user allowlist override | DB or env per deployment |
| 6.4 | URL allowlist for `browser.navigate` | Block internal IPs if desired |

**Files:** `tool_executor.py`, `backend/app/Http/Controllers/TaskController.php`, new `ToolPolicyService` (Laravel)

---

## 5. Priority matrix

| Priority | Phase | Effort | User impact |
|----------|-------|--------|-------------|
| P0 | Phase 0 — Runtime model | Medium | Unblocks VPS vs laptop |
| P1 | Phase 1 — Documents + file ops | Medium | Word/Excel ask (library path) |
| P1 | Phase 2 — Browser screenshot/snapshot | Medium | Reliable web automation |
| P2 | Phase 3 — Dev shell | Medium | Coding agent credibility |
| P2 | Phase 6 — Governance | Medium | Safety in production |
| P3 | Phase 4 — Office COM/AppleScript | High | Niche, fragile |
| P3 | Phase 5 — GUI/clipboard | High | Security-sensitive |

---

## 6. Dependencies & packages (Phase 1 reference)

```
python-docx
openpyxl
pypdf          # or pdfplumber
reportlab      # optional PDF create
```

Playwright already present for browser phases.

---

## 7. Testing strategy

| Layer | Tests |
|-------|-------|
| Path jail | Workspace/project escape attempts fail |
| Document tools | Golden files: minimal docx/xlsx bytes valid |
| Browser | Headless smoke: navigate + snapshot on example.com |
| Terminal policy | Disallowed command rejected |
| Platform | CI on macOS optional; Linux skips Office/GUI |

---

## 8. Status tracker

| Phase | Status | Target |
|-------|--------|--------|
| 0 Runtime model | Not started | — |
| 1 Documents & files | Not started | — |
| 2 Browser vision | Not started | — |
| 3 Dev shell | Not started | — |
| 4 Office automation | Not started | — |
| 5 GUI & clipboard | Not started | — |
| 6 Governance | Not started | — |

Update this table as phases ship.

---

## 9. Related documents

- **Non-computer agent features:** `docs/plans/AGENT_PLATFORM_PLAN.md`
- **LLM / VPS milestones:** discussed in product chat (Ollama + `ai-agent` env); not duplicated here.
