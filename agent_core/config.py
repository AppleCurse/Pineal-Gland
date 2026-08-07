"""Ortam değişkenlerinden yapılandırma."""
from __future__ import annotations

import os
from dataclasses import dataclass, field

try:
    from dotenv import load_dotenv

    load_dotenv()
except Exception:
    pass


def _env(name: str, default: str = "") -> str:
    return os.getenv(name, default)


@dataclass(frozen=True)
class Settings:
    # Agent-Zero (ana orkestratör) — doğrulanan API: POST /api/message (X-API-KEY)
    agent_zero_url: str = field(default_factory=lambda: _env("AGENT_ZERO_URL", "http://localhost:5000"))
    agent_zero_api_key: str = field(default_factory=lambda: _env("AGENT_ZERO_API_KEY", ""))

    # Deer-Flow (derin araştırma / uzun bağlam analizi) — doğrulanan API: /api/threads...
    deerflow_url: str = field(default_factory=lambda: _env("DEERFLOW_URL", "http://localhost:8080"))
    deerflow_assistant_id: str = field(default_factory=lambda: _env("DEERFLOW_ASSISTANT_ID", ""))

    # UI-TARS / Agent TARS CLI (görsel/piksel tabanlı ajan — DOM seçici yok)
    uitars_cli: str = field(default_factory=lambda: _env("UITARS_CLI", "npx @agent-tars/cli"))
    uitars_model: str = field(default_factory=lambda: _env("UITARS_MODEL", "qwen3-vl-plus"))
    uitars_remote_endpoint: str = field(default_factory=lambda: _env("UITARS_REMOTE_ENDPOINT", ""))

    # ElizaOS (persona + RAG hafızası) — doğrulanan API: POST /:agentId/message
    eliza_url: str = field(default_factory=lambda: _env("ELIZA_URL", "http://localhost:3000"))
    eliza_agent_id: str = field(default_factory=lambda: _env("ELIZA_AGENT_ID", "agent"))
    eliza_token: str = field(default_factory=lambda: _env("ELIZA_TOKEN", ""))

    # Oturum deposu (Postiz mantığı: şifreli çerez/token saklama)
    session_store_path: str = field(default_factory=lambda: _env("SESSION_STORE_PATH", "./data/sessions.json"))
    session_store_key: str = field(default_factory=lambda: _env("SESSION_STORE_KEY", ""))

    # LLM Gateway (LiteLLM :4000 — tüm LLM çağrıları buradan geçer)
    llm_gateway_url: str = field(default_factory=lambda: _env("LLM_GATEWAY_URL", "http://localhost:4000/v1"))
    llm_gateway_api_key: str = field(default_factory=lambda: _env("LITELLM_MASTER_KEY", _env("LLM_GATEWAY_API_KEY", "")))
    llm_model: str = field(default_factory=lambda: _env("LLM_MODEL", "deepseek-chat"))
    llm_fallback_model: str = field(default_factory=lambda: _env("LLM_FALLBACK_MODEL", "openrouter-chat"))

    # Genel
    http_timeout: float = field(default_factory=lambda: float(_env("HTTP_TIMEOUT", "120")))
    max_retries: int = field(default_factory=lambda: int(_env("MAX_RETRIES", "3")))
    log_dir: str = field(default_factory=lambda: _env("LOG_DIR", "./logs"))


def get_settings() -> Settings:
    return Settings()
