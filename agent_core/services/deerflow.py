"""Deer-Flow istemcisi (derin araştırma / uzun bağlam analizi).

Doğrulanan kontrat (kaynak kod: deer-flow/backend/app/gateway):
    POST /api/threads                     -> {"thread_id": ...}
    POST /api/threads/{id}/runs           -> {"run_id": ..., "status": ...}
        body: RunCreateRequest  -> assistant_id? input{input: {messages: [...]}} config? context? stream_mode?
    POST /api/threads/{id}/runs/wait      -> {"run_id": ..., ...} (bloklar, sonucu döner)
    GET  /api/threads/{id}/messages       -> konuşma geçmişi

RunCreateRequest `extra="forbid"` kullanır; bu yüzden yalnızca kontratta olan
alanlar gönderilir.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any, Dict, List, Optional

import httpx

logger = logging.getLogger("agent_core.deerflow")


class DeerFlowError(RuntimeError):
    pass


class DeerFlowClient:
    def __init__(self, base_url: str, timeout: float = 300.0, max_retries: int = 3):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.max_retries = max_retries

    async def _request(self, method: str, path: str, json: Optional[dict] = None) -> Dict[str, Any]:
        url = f"{self.base_url}{path}"
        last_exc: Optional[Exception] = None
        for attempt in range(1, self.max_retries + 1):
            try:
                async with httpx.AsyncClient(timeout=self.timeout) as client:
                    resp = await client.request(method, url, json=json)
                    if resp.status_code >= 400:
                        raise DeerFlowError(
                            f"deer-flow {method} {path} -> HTTP {resp.status_code}: {resp.text[:300]}"
                        )
                    return resp.json()
            except (httpx.HTTPError, DeerFlowError) as exc:
                last_exc = exc
                if attempt < self.max_retries:
                    await asyncio.sleep(2 ** attempt)
        raise DeerFlowError(f"deer-flow isteği başarısız: {last_exc}")

    async def create_thread(self) -> str:
        data = await self._request("POST", "/api/threads", json={})
        thread_id = data.get("thread_id") or data.get("id")
        if not thread_id:
            raise DeerFlowError(f"thread oluşturulamadı: {data}")
        logger.info("deer-flow thread oluşturuldu: %s", thread_id)
        return str(thread_id)

    def _build_run_body(
        self,
        query: str,
        assistant_id: Optional[str] = None,
        context: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        messages: List[Dict[str, str]] = [{"role": "user", "content": query}]
        body: Dict[str, Any] = {"input": {"messages": messages}}
        if assistant_id:
            body["assistant_id"] = assistant_id
        if context:
            body["context"] = context
        return body

    async def create_run(
        self,
        thread_id: str,
        query: str,
        assistant_id: Optional[str] = None,
        context: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Arka planda run başlatır, RunResponse döner (run_id, status)."""
        return await self._request(
            "POST", f"/api/threads/{thread_id}/runs",
            json=self._build_run_body(query, assistant_id, context),
        )

    async def run_and_wait(
        self,
        thread_id: str,
        query: str,
        assistant_id: Optional[str] = None,
        context: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Run'ı başlatıp tamamlanana kadar bloklar; son durumu (LangGraph state) döner."""
        data = await self._request(
            "POST", f"/api/threads/{thread_id}/runs/wait",
            json=self._build_run_body(query, assistant_id, context),
        )
        logger.info("deer-flow run tamamlandı (thread=%s)", thread_id)
        return data

    async def get_messages(self, thread_id: str) -> List[Dict[str, Any]]:
        data = await self._request("GET", f"/api/threads/{thread_id}/messages")
        return data if isinstance(data, list) else data.get("messages", [])

    async def run_research(
        self, query: str, assistant_id: Optional[str] = None,
        context: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Tek çağrı: thread oluştur, run'ı bloklayarak çalıştır, mesajları topla."""
        thread_id = await self.create_thread()
        final_state = await self.run_and_wait(thread_id, query, assistant_id, context)
        messages = await self.get_messages(thread_id)
        return {"thread_id": thread_id, "final_state": final_state, "messages": messages}

    async def health(self) -> bool:
        try:
            async with httpx.AsyncClient(timeout=5) as client:
                resp = await client.get(f"{self.base_url}/health")
                return resp.status_code == 200
        except httpx.HTTPError:
            return False
