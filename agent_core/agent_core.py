"""Ajan Çekirdeği — FastAPI giriş noktası.

Kapalı devreyi (agent-zero + deer-flow + UI-TARS + Eliza + oturum deposu)
yöneten orkestratörü çalıştırır. REST + canlı log WebSocket sunar.

Çalıştırma:
    python agent_core.py          -> http://localhost:5060
"""
from __future__ import annotations

import asyncio
import logging
import logging.handlers
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, Field

from config import get_settings
from orchestrator import Orchestrator

# ---------------------------------------------------------------------------
# Loglama: konsol + dönen dosya
# ---------------------------------------------------------------------------
LOG_DIR = Path(os.getenv("LOG_DIR", "./logs"))
LOG_DIR.mkdir(parents=True, exist_ok=True)


def setup_logging(level: int = logging.INFO) -> None:
    root = logging.getLogger()
    root.setLevel(level)
    fmt = logging.Formatter(
        "%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    console = logging.StreamHandler()
    console.setFormatter(fmt)
    file_handler = logging.handlers.RotatingFileHandler(
        LOG_DIR / "agent_core.log", maxBytes=2_000_000, backupCount=5, encoding="utf-8"
    )
    file_handler.setFormatter(fmt)
    root.addHandler(console)
    root.addHandler(file_handler)


setup_logging()
logger = logging.getLogger("agent_core.main")

settings = get_settings()
orch = Orchestrator(settings)

app = FastAPI(title="Ajan Çekirdeği (Kapalı Devre)", version="1.0.0")


# ---------------------------------------------------------------------------
# Veri modelleri
# ---------------------------------------------------------------------------
class TaskRequest(BaseModel):
    intent: str = Field(..., description="Yüksek seviye niyet/emir")
    target: Optional[str] = None
    platform: Optional[str] = None
    account: Optional[str] = None
    visual_task: Optional[str] = None


class TaskStatus(BaseModel):
    task_id: str
    status: str


# ---------------------------------------------------------------------------
# Canlı log yayını (WS)
# ---------------------------------------------------------------------------
class LogHub:
    def __init__(self) -> None:
        self._clients: Dict[str, WebSocket] = {}

    async def connect(self, ws: WebSocket) -> str:
        await ws.accept()
        cid = uuid.uuid4().hex[:8]
        self._clients[cid] = ws
        return cid

    def disconnect(self, cid: str) -> None:
        self._clients.pop(cid, None)

    async def broadcast(self, message: str, level: str = "info", **extra: Any) -> None:
        payload = {
            "type": "log",
            "level": level,
            "message": message,
            "ts": datetime.now(timezone.utc).isoformat(),
            **extra,
        }
        for cid in list(self._clients.keys()):
            ws = self._clients[cid]
            try:
                await ws.send_json(payload)
            except Exception:
                self.disconnect(cid)


hub = LogHub()


class PipelineLogHandler(logging.Handler):
    """Orkestratör loglarını WebSocket üzerinden yayınlar."""

    def emit(self, record: logging.LogRecord) -> None:
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                loop.create_task(
                    hub.broadcast(record.getMessage(), level=record.levelname.lower())
                )
        except Exception:
            pass


logging.getLogger("agent_core").addHandler(PipelineLogHandler())


# ---------------------------------------------------------------------------
# Rotalar
# ---------------------------------------------------------------------------
@app.post("/task", response_model=TaskStatus)
async def create_task(req: TaskRequest) -> TaskStatus:
    task_id = uuid.uuid4().hex[:12]
    logger.info("Görev alındı: %s (id=%s)", req.intent, task_id)

    async def _run() -> None:
        record = await orch.run_pipeline(
            intent=req.intent,
            target=req.target,
            platform=req.platform,
            account=req.account,
            visual_task=req.visual_task,
            task_id=task_id,
        )
        await hub.broadcast(
            f"Görev {task_id} bitti: {record['status']}", level=record["status"]
        )

    asyncio.create_task(_run())
    return TaskStatus(task_id=task_id, status="accepted")


@app.get("/task/{task_id}")
async def get_task(task_id: str):
    record = orch.get_task(task_id)
    if record is None:
        return {"error": "task bulunamadı"}
    return record


@app.get("/tasks")
async def list_tasks():
    return orch.list_tasks()


@app.get("/health")
async def health():
    services = await orch.health_async()
    return {"status": "alive", "ts": datetime.now(timezone.utc).isoformat(), "services": services}


@app.get("/agents")
async def list_agents():
    if not orch.eliza:
        return {"error": "Persona servisi yapilandirilmamis"}
    try:
        agents = await orch.eliza.get_agents()
        return {"agents": agents}
    except Exception as exc:
        return {"error": f"Eliza erişilemedi: {exc}"}


@app.get("/sessions")
async def list_sessions(platform: Optional[str] = None):
    if not orch.sessions:
        return {"error": "Oturum deposu yapilandirilmamis"}
    try:
        accounts = orch.sessions.list_accounts(platform)
        return {"accounts": accounts}
    except Exception as exc:
        return {"error": str(exc)}


@app.websocket("/ws")
async def ws_logs(ws: WebSocket):
    cid = await hub.connect(ws)
    try:
        while True:
            await ws.receive_text()  # ping / boş mesaj
    except WebSocketDisconnect:
        hub.disconnect(cid)


if __name__ == "__main__":
    import uvicorn

    print(">>> Ajan Cekirdegi baslatiliyor -> http://localhost:5060")
    print("   servisler:", {k: (v or "(kullanılmıyor)") for k, v in {
        "agent_zero": settings.agent_zero_url,
        "deerflow": settings.deerflow_url,
        "eliza": settings.eliza_url,
        "uitars_model_endpoint": settings.uitars_remote_endpoint or None,
    }.items()})
    uvicorn.run(app, host="0.0.0.0", port=5060)
