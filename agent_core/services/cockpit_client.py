"""
Cockpit Client — Agent Core ile Cockpit arasinda merkezi iletisim.

Bu client:
- Pending action'lari Cockpit'e iletir (human approval icin)
- Cockpit'den onay bekler
- Onay alininca aksiyonu gerceklestirir

Human Approval Boundary teknik olarak zorunlu kilinir.
"""
from __future__ import annotations

import asyncio
import logging
import os
from typing import Any, Dict, Optional

import httpx

logger = logging.getLogger("agent_core.cockpit_client")

COCKPIT_URL = os.getenv("COCKPIT_URL", "http://127.0.0.1:5050")
COCKPIT_TIMEOUT = float(os.getenv("COCKPIT_TIMEOUT", "60"))


class CockpitClientError(RuntimeError):
    pass


class CockpitClient:
    """Agent Core'dan Cockpit'e human approval istekleri iletir."""
    
    def __init__(self, cockpit_url: str = COCKPIT_URL, timeout: float = COCKPIT_TIMEOUT):
        self.cockpit_url = cockpit_url.rstrip("/")
        self.timeout = timeout
    
    async def submit_pending_action(
        self,
        task_id: str,
        action_type: str,
        platform: str,
        username: str,
        message_template: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Pending action'i Cockpit'e gonder, human approval bekle.
        
        Returns:
            {
                "status": "pending" | "approved" | "rejected" | "timeout",
                "action_id": "...",
                "approval_required": True,
            }
        """
        url = f"{self.cockpit_url}/api/action/pending"
        payload = {
            "task_id": task_id,
            "action_type": action_type,
            "platform": platform,
            "username": username,
            "message_template": message_template,
            "metadata": metadata or {},
        }
        
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                resp = await client.post(url, json=payload)
                if resp.status_code >= 400:
                    raise CockpitClientError(f"HTTP {resp.status_code}: {resp.text[:200]}")
                return resp.json()
        except httpx.ConnectError as exc:
            logger.warning("Cockpit baglantisi yok — pending action loglandi: %s", exc)
            # Cockpit ayakta degilse local log'a kaydet, task'i blocked yap
            return {
                "status": "pending",
                "action_id": f"local_{task_id}",
                "approval_required": True,
                "warning": "Cockpit unavailable — action logged locally",
            }
    
    async def check_action_status(self, action_id: str) -> Dict[str, Any]:
        """Pending action'in durumunu kontrol et."""
        url = f"{self.cockpit_url}/api/action/{action_id}/status"
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                resp = await client.get(url)
                if resp.status_code == 404:
                    return {"status": "unknown", "action_id": action_id}
                if resp.status_code >= 400:
                    raise CockpitClientError(f"HTTP {resp.status_code}: {resp.text[:200]}")
                return resp.json()
        except httpx.ConnectError:
            return {"status": "unknown", "action_id": action_id, "warning": "Cockpit unavailable"}
    
    async def execute_approved_action(
        self,
        action_id: str,
        cookies: list,
    ) -> Dict[str, Any]:
        """Onaylanmis aksiyonu Cockpit uzerinden calistir.
        
        Cookies Cockpit browser session'ina ait olmali.
        """
        url = f"{self.cockpit_url}/api/action/{action_id}/execute"
        payload = {"cookies": cookies}
        try:
            async with httpx.AsyncClient(timeout=self.timeout * 2) as client:
                resp = await client.post(url, json=payload)
                if resp.status_code >= 400:
                    raise CockpitClientError(f"HTTP {resp.status_code}: {resp.text[:200]}")
                return resp.json()
        except httpx.ConnectError as exc:
            logger.error("Cockpit baglantisi yok — aksiyon calistirilamadi: %s", exc)
            raise CockpitClientError(f"Cockpit unavailable: {exc}")


# Module-level singleton
_client: Optional[CockpitClient] = None


def get_cockpit_client() -> CockpitClient:
    global _client
    if _client is None:
        _client = CockpitClient()
    return _client
