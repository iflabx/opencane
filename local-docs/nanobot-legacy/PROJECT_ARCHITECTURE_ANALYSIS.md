# Nanobot Project Architecture and Feature Analysis

## 1. Project Positioning

`nanobot` is a lightweight personal AI assistant framework built around a unified agent core with multi-channel integrations.

Primary traits:

- Multi-channel message ingress/egress
- Tool-augmented LLM loop (function calling style)
- Persistent sessions and memory
- Cron scheduling and heartbeat-driven proactive tasks
- Extensible provider / tool / channel / skill architecture


## 2. High-Level Architecture

Core runtime path:

1. Channel receives user input
2. Channel pushes inbound message into bus
3. Agent loop consumes message and builds context
4. LLM returns response and/or tool calls
5. Tools execute and feed results back to loop
6. Final response is published to outbound bus
7. Channel manager routes response back to target channel

Conceptual flow:

```text
User
  -> Channel (Telegram/Slack/Email/...)
  -> MessageBus.inbound
  -> AgentLoop
      -> ContextBuilder (bootstrap + memory + skills + history)
      -> LLM Provider (LiteLLM)
      -> ToolRegistry (file/shell/web/message/spawn/cron)
  -> MessageBus.outbound
  -> ChannelManager
  -> Channel.send()
  -> User
```


## 3. Layered Module Breakdown

### 3.1 CLI and Runtime Orchestration

- File: `nanobot/cli/commands.py`
- Main commands:
  - `nanobot onboard`
  - `nanobot agent`
  - `nanobot gateway`
  - `nanobot cron ...`
  - `nanobot channels ...`
  - `nanobot status`

Runtime assembly in `gateway`:

- Load config
- Build bus
- Build provider
- Build `AgentLoop`
- Build `CronService` + callback into agent
- Build `HeartbeatService` + callback into agent
- Build `ChannelManager`
- Run agent loop and channel manager concurrently

### 3.2 Message Transport Layer

- Files:
  - `nanobot/bus/events.py`
  - `nanobot/bus/queue.py`
- `InboundMessage` / `OutboundMessage` are canonical internal event payloads.
- `MessageBus` decouples channels from agent via async queues.

### 3.3 Channel Adapter Layer

- Base abstraction:
  - `nanobot/channels/base.py`
- Channel lifecycle:
  - `start()`, `stop()`, `send()`
- Permission check:
  - `allow_from` list enforced by `BaseChannel.is_allowed()`

Implemented adapters include:

- Telegram, Discord, WhatsApp, Feishu, DingTalk, Slack, Email, QQ, Mochat

Notable behavior:

- Telegram supports media download + optional voice transcription
- Slack supports mention/open/allowlist channel policies and thread context
- Email supports IMAP polling + SMTP replies, with explicit consent gate
- Mochat supports Socket.IO + HTTP fallback workers, mention and delayed reply policies

### 3.4 Agent Core Layer

- Files:
  - `nanobot/agent/loop.py`
  - `nanobot/agent/context.py`
  - `nanobot/agent/skills.py`
  - `nanobot/agent/memory.py`
  - `nanobot/agent/subagent.py`

Responsibilities:

- Session-aware context construction
- Iterative LLM <-> tool loop (`max_iterations`)
- System-message handling for background subagent completion
- Session persistence after each turn

Context assembly includes:

- Core identity prompt
- Workspace bootstrap files (`AGENTS.md`, `SOUL.md`, `USER.md`, `TOOLS.md`, optional `IDENTITY.md`)
- Long-term and daily memory
- Skills:
  - always-loaded skill bodies
  - summary index for progressive loading

### 3.5 Tooling Layer

- Registry and schema validation:
  - `nanobot/agent/tools/base.py`
  - `nanobot/agent/tools/registry.py`
- Built-in tools:
  - Filesystem: `read_file`, `write_file`, `edit_file`, `list_dir`
  - Shell: `exec`
  - Web: `web_search`, `web_fetch`
  - Messaging: `message`
  - Background tasks: `spawn`
  - Scheduling: `cron` (if cron service is enabled)

Safety controls:

- Path restriction via `restrict_to_workspace`
- Shell deny-pattern guard for dangerous commands
- Per-command timeout and output truncation

### 3.6 Provider Layer

- Files:
  - `nanobot/providers/base.py`
  - `nanobot/providers/litellm_provider.py`
  - `nanobot/providers/registry.py`
  - `nanobot/providers/transcription.py`

Design:

- `LiteLLMProvider` gives a single chat interface.
- `ProviderSpec` registry is the source of truth for:
  - provider matching
  - env var mapping
  - model prefixing
  - gateway detection (e.g., OpenRouter, AiHubMix)
  - model-specific overrides

### 3.7 Persistence and Stateful Services

- Session history:
  - `nanobot/session/manager.py`
  - JSONL storage under `~/.nanobot/sessions`
- Memory:
  - `workspace/memory/MEMORY.md` and daily note files
- Cron:
  - `nanobot/cron/service.py`
  - persisted job store under `~/.nanobot/cron/jobs.json`
- Heartbeat:
  - `nanobot/heartbeat/service.py`
  - periodic prompt trigger based on `HEARTBEAT.md`


## 4. Key Feature Set

### 4.1 Conversation Modes

- One-shot CLI question (`agent -m`)
- Interactive CLI session
- Multi-channel online gateway mode

### 4.2 Multi-Platform Chat Integrations

- Telegram, Discord, WhatsApp (via Node bridge), Feishu, DingTalk, Slack, Email, QQ, Mochat

### 4.3 Agentic Tool Use

- File operations
- Command execution
- Web search and fetch
- Outbound proactive messaging
- Background subagent delegation
- Scheduling through cron tool

### 4.4 Proactive and Scheduled Work

- Cron jobs:
  - `every`, `cron`, `at`
- Heartbeat checks:
  - Periodic wake-up to process `HEARTBEAT.md`

### 4.5 Skills System

- Built-in skills (`nanobot/skills`)
- Workspace custom skills (`workspace/skills`)
- Metadata-based discovery and requirements checking
- Progressive disclosure to control context size


## 5. Security and Guardrails

Implemented controls:

- Channel allowlist checks (`allow_from`)
- Optional workspace-only tool sandboxing (`restrict_to_workspace`)
- Shell dangerous command guard
- URL validation for web fetch
- Email explicit consent gate (`consent_granted`)

Documented security guidance:

- `SECURITY.md` includes key handling, deployment practices, dependency audit, and operational checklist.


## 6. Notable Implementation Observations

1. Version mismatch:
   - `pyproject.toml` package version is `0.1.3.post6`
   - `nanobot/__init__.py` exposes `__version__ = "0.1.0"`

2. `gateway --port` currently affects output text only; no HTTP server bind is started in current gateway path.

3. `SessionManager` constructor receives `workspace`, but session persistence location is fixed under `~/.nanobot/sessions`.

4. `MessageBus.dispatch_outbound()` exists, but gateway path uses `ChannelManager._dispatch_outbound()` for routing.


## 7. Testing Snapshot

Current repository test coverage includes:

- CLI input behavior
- Tool schema validation
- Email channel behavior
- Docker smoke script

In this environment, `pytest` executable was not available, so test suite was not executed here.


## 8. Overall Assessment

The architecture is pragmatic and modular:

- Clear separation between transport, agent reasoning, tool execution, and provider adaptation
- Good extensibility through registries and base abstractions
- Rich real-world integration surface despite relatively small codebase

Best-fit scenarios:

- Personal AI assistant gateway
- Agent framework learning and experimentation
- Rapid prototyping for multi-channel LLM assistants
