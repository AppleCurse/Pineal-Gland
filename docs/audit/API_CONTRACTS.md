# API CONTRACTS

## 1. agent_core (Orchestrator)

Base URL: `http://localhost:5060`

### `POST /task`
- **Input**: `{"intent": "string", "target": "string?", "platform": "string?", "account": "string?", "visual_task": "string?"}`
- **Output**: `{"task_id": "string", "status": "string"}`

### `GET /task/{task_id}`
- **Input**: None
- **Output**: Task state dictionary containing steps, validation_status, error, etc.

### `GET /health`
- **Output**: JSON payload indicating alive status, individual agent/service connectivity (`agent_zero`, `deerflow`, `eliza`), and circuit breaker state.

## 2. External Agent Integrations

The `agent_core` orchestrator expects the following APIs to be available externally.

### Agent-Zero
- **Base URL**: `http://localhost:5000` (configurable)
- **Authentication**: `X-API-KEY` (MCP_SERVER_TOKEN)
- **POST `/api/api_message`**:
  - **Body**: `{"message": "str", "lifetime_hours": float, "context_id": "str?"}`
  - **Returns**: `{"context_id": "str", "response": "str"}`

### DeerFlow
- **Base URL**: `http://localhost:8001` (configurable)
- **POST `/api/threads`**: Creates a new thread.
- **POST `/api/threads/{id}/runs/wait`**:
  - **Body**: `{"input": {"messages": [{"role": "user", "content": "str"}]}}`
  - **Returns**: Final state after execution blocking.

### ElizaOS
- **Base URL**: `http://localhost:3000` (configurable)
- **POST `/:agentId/message`**:
  - **Body**: `{"text": "str", "roomId": "str", "userId": "str"}`
  - **Returns**: List of messages, e.g., `[{"text": "response", "user": "agent"}]`

### Handover (Cockpit)
- **Base URL**: `http://localhost:5050` (configurable)
- **POST `/api/handover`**:
  - **Body**: `{"type": "handover_alert", "target": "str", "score": float, "achilles_heel": "str", "chat_history": list}`
  - **Returns**: Broadcasts WebSocket event to Cockpit UI.

### Critical Notes
- The orchestrator gracefully handles external system failures by returning "unavailable" for a step and continuing the pipeline, except where strict failures occur (like missing database permissions).
