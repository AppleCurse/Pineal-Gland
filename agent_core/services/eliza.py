"""ElizaOS istemcisi (persona + RAG hafızası).

Eliza'nın REST API'si (resmi dokümantasyon):
    GET  /agents                              -> ajan listesi
    POST /:agentId/message
        body: {"text": str, "roomId": str, "userId": str, "unique": bool?}
        yanıt: [{"text": str, "user": "agent", "action": ...}, ...]

RAG hafızası Eliza içinde roomId kapsamında tutulur. Bu adaptör hedef başına
sabit bir roomId kullanır; böylece her hedefin geçmişi ve karakter belleği
ElizaOS'un vektör deposunda kalıcı olur.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

import httpx

logger = logging.getLogger("agent_core.eliza")


class ElizaError(RuntimeError):
    pass


class ElizaClient:
    def __init__(self, base_url: str, agent_id: str, token: str = "", timeout: float = 60.0):
        self.base_url = base_url.rstrip("/")
        self.agent_id = agent_id
        self.token = token
        self.timeout = timeout

    def _headers(self) -> Dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        return headers

    async def get_agents(self) -> List[Dict[str, Any]]:
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            resp = await client.get(f"{self.base_url}/agents", headers=self._headers())
            if resp.status_code >= 400:
                raise ElizaError(f"eliza /agents -> HTTP {resp.status_code}: {resp.text[:300]}")
            data = resp.json()
            return data if isinstance(data, list) else data.get("agents", [])

    async def send_message(
        self,
        text: str,
        room_id: str,
        user_id: str = "system",
        unique: Optional[bool] = None,
    ) -> List[Dict[str, Any]]:
        """Persona ile konuşur. room_id, RAG hafızasının kapsamıdır (hedef başına sabit)."""
        payload: Dict[str, Any] = {"text": text, "roomId": room_id, "userId": user_id}
        if unique is not None:
            payload["unique"] = unique
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            resp = await client.post(
                f"{self.base_url}/{self.agent_id}/message", json=payload, headers=self._headers()
            )
            if resp.status_code >= 400:
                raise ElizaError(
                    f"eliza /{self.agent_id}/message -> HTTP {resp.status_code}: {resp.text[:300]}"
                )
            data = resp.json()
            logger.info("eliza yanıt (room=%s): %s", room_id, str(data)[:200])
            return data if isinstance(data, list) else []

    async def recall(self, room_id: str, user_id: str = "system") -> str:
        """Odanın RAG hafızasını yoklar: boş hatırlatma isteği döndürür."""
        replies = await self.send_message("", room_id, user_id, unique=False)
        return "\n".join(r.get("text", "") for r in replies if r.get("user") == "agent")

    async def health(self) -> bool:
        try:
            async with httpx.AsyncClient(timeout=5) as client:
                resp = await client.get(f"{self.base_url}/agents", headers=self._headers())
                return resp.status_code == 200
        except httpx.HTTPError:
            return False
