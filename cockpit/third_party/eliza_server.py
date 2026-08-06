"""
ElizaOS Servisi — FastAPI + LiteLLM Entegrasyonu + Oda Bazlı Kalıcı Hafıza.

REST API Endpoints:
    GET  /health            -> Healthcheck
    GET  /agents            -> Aktif ajan listesi
    POST /{agent_id}/message -> Mesaj gönder & Persona + Hafıza yanıtı al
"""
import json
import logging
import os
from pathlib import Path
from typing import Any, Dict, List, Optional
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import httpx

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("eliza_service")

BASE_DIR = Path(__file__).resolve().parent
MEMORY_FILE = BASE_DIR / "eliza_memory.json"
LITELLM_URL = os.getenv("LITELLM_URL", "http://localhost:4000/v1")
LITELLM_KEY = os.getenv("LITELLM_KEY", "sk-litellm-master-key-2026")
MODEL_NAME = os.getenv("ELIZA_MODEL", "openai/dijitalvarlik")

app = FastAPI(title="ElizaOS Persona & Memory Service", version="1.0.0")

class MessageRequest(BaseModel):
    text: str
    roomId: str
    userId: str = "system"
    unique: Optional[bool] = None

class MemoryStore:
    def __init__(self, filepath: Path):
        self.filepath = filepath
        self.data: Dict[str, List[Dict[str, str]]] = self._load()

    def _load(self) -> Dict[str, List[Dict[str, str]]]:
        if self.filepath.exists():
            try:
                return json.loads(self.filepath.read_text(encoding="utf-8"))
            except Exception as e:
                logger.warning(f"Hafıza dosyası okunamadı: {e}")
        return {}

    def save(self):
        try:
            self.filepath.write_text(json.dumps(self.data, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception as e:
            logger.error(f"Hafıza kaydetme hatası: {e}")

    def add_message(self, room_id: str, sender: str, text: str):
        if room_id not in self.data:
            self.data[room_id] = []
        self.data[room_id].append({"sender": sender, "text": text})
        if len(self.data[room_id]) > 20:
            self.data[room_id] = self.data[room_id][-20:]
        self.save()

    def get_history(self, room_id: str) -> List[Dict[str, str]]:
        return self.data.get(room_id, [])

memory = MemoryStore(MEMORY_FILE)

@app.get("/health")
async def health():
    return {"status": "ok", "service": "ElizaOS"}

@app.get("/agents")
async def get_agents():
    return [
        {
            "id": "default",
            "name": "ElizaOS Persona Agent",
            "description": "Sosyal Medya, İletişim ve RAG Hafıza Ajanı",
            "status": "active"
        }
    ]

@app.post("/{agent_id}/message")
async def post_message(agent_id: str, req: MessageRequest):
    room_id = req.roomId or "default"
    user_text = req.text.strip()
    
    logger.info(f"Mesaj alındı (agent={agent_id}, room={room_id}, user={req.userId}): {user_text[:60]}")
    
    if user_text:
        memory.add_message(room_id, req.userId, user_text)
    else:
        history = memory.get_history(room_id)
        if not history:
            return [{"text": "Henüz bu oda için kayıtlı bağlam yok.", "user": "agent", "action": "NONE"}]
        context_str = "\n".join(f"{m['sender']}: {m['text']}" for m in history)
        return [{"text": f"Oda Bağlamı ({room_id}):\n{context_str}", "user": "agent", "action": "RECALL"}]

    history = memory.get_history(room_id)
    messages = [
        {
            "role": "system",
            "content": (
                "Sen ElizaOS Persona Ajanısın. Doğal, empatik, akıllı ve bağlama uygun Türkçe yanıtlar verirsin. "
                "Önceki konuşma geçmişini dikkate alarak yanıt ver."
            )
        }
    ]
    for m in history:
        role = "user" if m["sender"] != "agent" else "assistant"
        messages.append({"role": role, "content": m["text"]})

    reply_text = ""
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                f"{LITELLM_URL}/chat/completions",
                headers={"Authorization": f"Bearer {LITELLM_KEY}", "Content-Type": "application/json"},
                json={
                    "model": MODEL_NAME,
                    "messages": messages,
                    "max_tokens": 512,
                    "temperature": 0.7
                }
            )
            if resp.status_code == 200:
                data = resp.json()
                reply_text = data["choices"][0]["message"]["content"].strip()
            else:
                logger.warning(f"LiteLLM hatası ({resp.status_code}): {resp.text[:200]}")
                reply_text = f"[ElizaOS] LiteLLM yanıt veremedi ({resp.status_code}), varsayılan persona aktif."
    except Exception as e:
        logger.error(f"LiteLLM bağlantı hatası: {e}")
        reply_text = f"[ElizaOS Local] Mesajınız alındı ve hafızaya işlendi: '{user_text}'"

    memory.add_message(room_id, "agent", reply_text)

    return [{"text": reply_text, "user": "agent", "action": "CONTINUE"}]

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=3000)
