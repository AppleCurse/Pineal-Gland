# ARCHITECTURE AUDIT

## 1. Repository Inventory

The codebase is structured into a multi-service pattern managed mostly by Python scripts and a few external components.

- `agent_core/`: The central API gateway and orchestrator.
  - `agent_core.py`: FastAPI entrypoint.
  - `orchestrator.py`: The `Orchestrator` class managing service execution pipelines.
  - `config.py`: Environment variable loading.
  - `resonance_graph.py`: LangGraph implementation for interaction logic.
  - `mission_brief.py`: Data models.
  - `services/`: Integrations.
    - `agent_zero.py`, `deerflow.py`, `eliza.py`, `uitars.py`: External agent interfaces.
    - `llm_gateway.py`: The single-point-of-contact for LLM tasks.
    - `analyzer.py`: Generates behavioral signals.
    - `handover.py`: Manages human-in-the-loop requests.
    - `scraper.py`: Playwright integration.
    - `session_store.py`: Session crypto management.
    - `uncertainty.py`: Analyzes confidence vs evidence.
    - `memory_delta.py`, `memory_manager.py`: Handles state tracking.
- `cockpit/`: A UI interface (React/HTML over FastAPI) for human handover.
- `deploy/litellm/`: The LiteLLM proxy configuration.
- `start_all.ps1`: The primary startup script for local environments.

## 2. Abstractions and Modularity

**Orchestrator Coupling:**
The Orchestrator (`orchestrator.py`) directly imports clients (`AgentZeroClient`, `ElizaClient`, etc.). There is *no dynamic plugin registry*. It relies on a `ServiceContainer` built at startup via `build_default_services`. Adding a new service requires modifying the `Orchestrator`'s `run_pipeline` method.

**Agent Independence vs. Orchestration:**
The architecture treats Agent-Zero, DeerFlow, ElizaOS, and UI-TARS as "organs" (external services over HTTP API boundaries) rather than unified modules. The Orchestrator just sends commands and waits for responses.

## 3. Analyzer & Behavior Siganls

`ProfileAnalyzer` is implemented in `analyzer.py`. It correctly distinguishes between raw observations and signals using strict `SYSTEM_PROMPT` rules. It enforces that mental illness diagnoses are strictly forbidden. The confidence score comes straight from the LLM, and the Uncertainty engine (`uncertainty.py`) determines if the confidence correlates with the provided specific evidence.

## 4. Resonance Graph

The `Resonance Graph` is **not** a placeholder. It is an actual LangGraph state machine (`StateGraph` in `resonance_graph.py`).
- State: `ResonanceState`
- Nodes: `analyze`, `strategize`, `act`, `evaluate`
- Logic: It computes a deterministic `CompatibilityVector` without an LLM. It modifies the composite score if the `Uncertainty Engine` detects a "FLAG" (confidence/evidence mismatch). If the composite is over `ENGAGEMENT_THRESHOLD`, it transitions to direct engagement, which flags `handover_ready = True` (as direct DMing is disabled pending human approval).

## 5. Security & Deployment

- Secrets are expected to be injected via `.env`.
- `SESSION_STORE_KEY` needs to be exactly 32/64 bytes hex, otherwise the application crashes upon task creation.
- Local execution is done manually or via `start_all.ps1`.
- Docker compose exists in `agent_core/docker-compose.yml`, primarily intended for self-hosted instances of external tools (Postgres, Eliza, etc).
- `start_all.ps1` expects Windows paths (`Scripts\python.exe`) making it incompatible out of the box with Linux/Mac.

## 6. Observability

- Uses a `LogHub` (WebSocket) in `agent_core.py` to stream logs directly to connected clients.
- `agent_core.log` is rotated.
- `task_id` acts as a request correlation ID across the orchestrator, but is not strictly passed to the external services as an HTTP header.
