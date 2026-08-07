"""Agent-Zero istemcisi.

Doğrulanan kontrat (kaynak kod: agent-zero/helpers/api.py + agent-zero/api/api_message.py):
    POST /api/api_message
    Header: X-API-KEY: <mcp_server_token> (helpers.api.requires_api_key)
    Body : {"context_id": str|None, "message": str, "attachments": [...],
             "lifetime_hours": float, "project_name": str|None, "agent_profile": str|None}
    Yanıt : {"context_id": str, "response": <agent yanıtı>}

Not: /api/message uç noktası web oturum doğrulaması ister (api/message.py);
     API-anahtarı uç noktası dosya adından türetilen /api/api_message'tir.
Agent-Zero mesajı aldığında kendi içinde dinamik alt-ajan (sub-agent) yaratma/
fork mantığını yürütür; istemci yalnızca emri iletir ve context_id'yi korur.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any, Dict, List, Optional

import httpx

logger = logging.getLogger("agent_core.agent_zero")


class AgentZeroError(RuntimeError):
    pass


from services.registry import ICodeExecution

class AgentZeroClient(ICodeExecution):
    async def execute(self, command: str, context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        return await self.send_message(command, context_id=context.get("context_id") if context else None)
    def __init__(self, base_url: str, api_key: str, timeout: float = 600.0, max_retries: int = 3):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.timeout = timeout
        self.max_retries = max_retries

    async def _post(self, path: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        url = f"{self.base_url}{path}"
        headers = {"X-API-KEY": self.api_key, "Content-Type": "application/json"}
        last_exc: Optional[Exception] = None
        for attempt in range(1, self.max_retries + 1):
            try:
                async with httpx.AsyncClient(timeout=self.timeout) as client:
                    resp = await client.post(url, json=payload, headers=headers)
                    if resp.status_code >= 400:
                        raise AgentZeroError(
                            f"agent-zero {path} -> HTTP {resp.status_code}: {resp.text[:300]}"
                        )
                    data = resp.json()
                    logger.debug("agent-zero %s OK (attempt %d)", path, attempt)
                    return data
            except (httpx.HTTPError, AgentZeroError) as exc:
                last_exc = exc
                if attempt < self.max_retries:
                    await asyncio.sleep(2 ** attempt)
        raise AgentZeroError(f"agent-zero isteği başarısız: {last_exc}")

    async def send_message(
        self,
        message: str,
        context_id: Optional[str] = None,
        agent_profile: Optional[str] = None,
        project_name: Optional[str] = None,
        lifetime_hours: float = 24.0,
    ) -> Dict[str, Any]:
        """Agent-Zero'ya bir emir/komut iletir. context_id aynı sohbeti sürdürür."""
        if not message.strip():
            raise AgentZeroError("message boş olamaz")
        payload: Dict[str, Any] = {
            "message": message,
            "lifetime_hours": lifetime_hours,
        }
        if context_id:
            payload["context_id"] = context_id
        if agent_profile:
            payload["agent_profile"] = agent_profile
        if project_name:
            payload["project_name"] = project_name
        logger.info(
            "agent-zero mesaj gönderiliyor (context=%s): %s",
            context_id or "yeni",
            message[:80],
        )
        result = await self._post("/api/api_message", payload)
        logger.info("agent-zero yanıt: %s", str(result.get("response", ""))[:120])
        return result

    async def reset_chat(self, context_id: str) -> Dict[str, Any]:
        return await self._post("/api/reset_chat", {"context_id": context_id})

    async def terminate_chat(self, context_id: str) -> Dict[str, Any]:
        return await self._post("/api/terminate_chat", {"context_id": context_id})

    async def get_log(
        self, context_id: str, last_id: Optional[int] = None
    ) -> List[Dict[str, Any]]:
        payload: Dict[str, Any] = {"context_id": context_id}
        if last_id is not None:
            payload["last_id"] = last_id
        data = await self._post("/api/log_get", payload)
        return data.get("log", [])

    async def health(self) -> bool:
        try:
            async with httpx.AsyncClient(timeout=5) as client:
                resp = await client.get(f"{self.base_url}/api/health")
                return resp.status_code == 200
        except httpx.HTTPError:
            return False