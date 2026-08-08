"""
LLM Bridge — Cockpit'in dogrudan OpenRouter cagrilari yerine
Agent Core LLM Gateway'i kullanmasini saglar.

Bu bridge:
- Cockpit'ten gelen LLM isteklerini Agent Core LLMGateway'e yonlendirir
- Merkezi routing, fallback, cost tracking saglar
- Circuit breaker ve token budget'i ortak kullanir

Kullanim:
    python cockpit_llm_bridge.py  # :5051 portunda calisir
"""
from __future__ import annotations

import asyncio
import logging
import os
import sys
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

# Agent Core LLMGateway'i import et
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "agent_core"))
from services.llm_gateway import LLMGateway, LLMGatewayError

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("cockpit_llm_bridge")

app = FastAPI(title="LLM Bridge", version="0.1.0")


class LLMRequest(BaseModel):
    system_prompt: str
    user_message: str
    model: Optional[str] = None
    temperature: float = 0.2
    max_tokens: int = 1024


class LLMResponse(BaseModel):
    content: Optional[str]
    model_used: str
    success: bool
    error: Optional[str] = None


# Global LLMGateway instance
_gateway: Optional[LLMGateway] = None


def get_gateway() -> LLMGateway:
    global _gateway
    if _gateway is None:
        _gateway = LLMGateway()
    return _gateway


@app.post("/v1/chat/completions", response_model=LLMResponse)
async def chat_completions(req: LLMRequest) -> LLMResponse:
    """LLM Gateway uzerinden chat tamamlama."""
    gateway = get_gateway()
    
    messages = [
        {"role": "system", "content": req.system_prompt},
        {"role": "user", "content": req.user_message},
    ]
    
    try:
        content = await gateway.chat(
            messages=messages,
            model=req.model,
            temperature=req.temperature,
            max_tokens=req.max_tokens,
        )
        return LLMResponse(
            content=content,
            model_used=gateway.model,
            success=True,
        )
    except LLMGatewayError as exc:
        logger.error("LLM Gateway hatasi: %s", exc)
        return LLMResponse(
            content=None,
            model_used=req.model or gateway.model,
            success=False,
            error=str(exc),
        )


@app.get("/health")
async def health() -> Dict[str, Any]:
    """Sağlık kontrolü + gateway status."""
    gateway = get_gateway()
    return {
        "status": "alive",
        "gateway_model": gateway.model,
        "fallback_model": gateway.fallback_model,
        "usage_stats": gateway.get_usage_stats(),
    }


if __name__ == "__main__":
    import uvicorn
    
    host = os.getenv("LLM_BRIDGE_HOST", "127.0.0.1")
    port = int(os.getenv("LLM_BRIDGE_PORT", "5051"))
    
    print(f"[START] LLM Bridge baslatiliyor...")
    print(f"[URL]   http://{host}:{port}")
    print(f"[INFO]  Tum LLM cagrilari Agent Core LLMGateway uzerinden gececek")
    
    uvicorn.run(app, host=host, port=port)
