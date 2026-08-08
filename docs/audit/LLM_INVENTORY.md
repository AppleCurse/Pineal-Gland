# LLM INVENTORY

## LLM Gateway Architecture

The system uses a centralized LLM Gateway approach via the LiteLLM proxy (`deploy/litellm`).

- **Primary Endpoint**: `http://localhost:4000/v1`
- **Authentication**: `Bearer <LITELLM_MASTER_KEY>`
- **Internal Python Interface**: `agent_core/services/llm_gateway.py`

### Python `LLMGateway` Class Features:
1. **Fallback**: Hardcoded loop over `self.model` then `self.fallback_model` (`openrouter-chat`).
2. **Circuit Breaker**: Uses `CircuitBreaker` class. If a model fails consecutively, the circuit opens for a cooldown period (default 60s), bypassing it in favor of the fallback model.
3. **Structured Output**: Custom `chat_and_parse` function handles Pydantic schemas. If JSON decoding fails, it uses Regex. If validation fails, it issues a "Retry: error ..." prompt back to the LLM (up to `max_parse_retries`).
4. **Token Budgeting**: A simple `TokenBudget` tracks usage by model in memory.

### Inventory of Calls

| File/Module | Function | Model Selection | Usage Type | Notes |
|-------------|----------|-----------------|------------|-------|
| `services/analyzer.py` | `analyze()` | Gateway default (DeepSeek) | Structured Output (`BehavioralProfile`) | Strictly forbids mental illness diagnosis in prompt. |
| `services/uitars.py` | `UITarsModelClient.predict()` | Visual LM Endpoint (UI-TARS) | Raw VLM Vision Inference | Bypasses the Gateway. Direct call to remote VLM instance (`UITARS_REMOTE_ENDPOINT`). |
| External: `DeerFlow` | `backend/config.yaml` | `langchain_openai:ChatOpenAI` -> Gateway | Agent Re-routing | Points base_url to `http://localhost:4000/v1`. Uses Gateway Master Key. |
| External: `Agent-Zero` | `model_providers.yaml` | `llmgateway` (openai provider) -> Gateway | Agent Re-routing | Points api_base to `http://localhost:4000/v1`. Uses Gateway Master Key. |

### Note on Hardcoded Variables
- `agent_core.py` and `config.py` default `llm_model` to `deepseek-chat` and `llm_fallback_model` to `openrouter-chat`.
- No direct provider calls are made by the `agent_core` logic, besides the `UI-TARS` visual model bypass.
