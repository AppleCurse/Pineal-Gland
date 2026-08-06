"""
Human-in-the-Loop Devirme — Cockpit WebSocket Entegrasyonu (Telegram YOK).

handover_ready = True olduğunda Cockpit'e (localhost:5050/api/handover) POST atar.
Cockpit bunu tüm WebSocket bağlantılarına "handover_alert" olarak yayınlar.

Frontend:
  - Kırmızı yanıp sönen "IPLER SENDE MOSYO" uyarısı
  - Sohbet geçmişi ekranda gösterilir
  - Frekans skoru çubuğu

Kullanım:
    python handover.py --target "@hedef" --achilles "Asil tendonu" --score 8.5
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from typing import Any, Dict, List, Optional, TypedDict

import httpx
from dotenv import load_dotenv

load_dotenv()
logger = logging.getLogger("agent_core.handover")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

# Cockpit adresi — Telegram KULLANILMIYOR
COCKPIT_URL = os.getenv("COCKPIT_URL", "http://localhost:5050")
COCKPIT_HANDOVER_ENDPOINT = f"{COCKPIT_URL}/api/handover"

# LangGraph opsiyonel
try:
    from langgraph.graph import StateGraph, END
    LANGGRAPH_AVAILABLE = True
except ImportError:
    LANGGRAPH_AVAILABLE = False
    logger.warning("langgraph kurulu degil — standalone modda calisiyor")


# ─── LangGraph State Şeması ────────────────────────────────────────────────────
class HandoverState(TypedDict):
    target_username: str
    achilles_tendon: str
    frequency_score: float
    conversation_snippet: str
    chat_history: List[Dict[str, str]]
    handover_ready: bool
    handover_sent: bool
    error: Optional[str]


# ─── Cockpit WebSocket Devirme Gönderici ──────────────────────────────────────
class CockpitHandover:
    """Telegram YOK. Cockpit /api/handover REST endpoint'ine POST atar."""

    def __init__(self, cockpit_url: str = COCKPIT_URL):
        self.cockpit_url = cockpit_url
        self.endpoint = f"{cockpit_url}/api/handover"

    async def notify(self, state: HandoverState) -> Dict[str, Any]:
        """Cockpit'e devir sinyali gönderir → WS broadcast tetiklenir."""
        payload = {
            "type": "handover_alert",
            "target": state["target_username"],
            "score": state["frequency_score"],
            "achilles_heel": state["achilles_tendon"],
            "chat_history": state.get("chat_history", []),
        }

        # Konsola da yaz (debug)
        score_bar = "#" * int(state["frequency_score"]) + "." * (10 - int(state["frequency_score"]))
        logger.info(
            "\n[DEVIR HAZIR]\nHedef: %s\nAsil Tendonu: %s\nFrekans: %.1f/10  [%s]\nCockpit: %s",
            state["target_username"],
            state["achilles_tendon"],
            state["frequency_score"],
            score_bar,
            self.endpoint,
        )

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.post(self.endpoint, json=payload)
                if resp.status_code == 200:
                    result = resp.json()
                    logger.info("Cockpit devir algiladi: %s", result)
                    return {"status": "sent_to_cockpit", "result": result}
                else:
                    logger.error("Cockpit hatasi %d: %s", resp.status_code, resp.text[:200])
                    return {"status": "cockpit_error", "error": resp.text[:200]}
        except httpx.ConnectError:
            logger.warning(
                "Cockpit'e baglanılamadi (%s) — devir konsola yazildi", self.endpoint
            )
            return {"status": "cockpit_offline", "payload": payload}
        except Exception as exc:
            logger.error("Devir hatasi: %s", exc)
            return {"status": "error", "error": str(exc)}


# ─── LangGraph Node'ları ───────────────────────────────────────────────────────
async def check_handover_node(state: HandoverState) -> HandoverState:
    if state.get("handover_ready"):
        logger.info(
            "Devir tetiklendi: %s (skor: %.1f)",
            state["target_username"],
            state["frequency_score"],
        )
    return state


async def send_handover_node(state: HandoverState) -> HandoverState:
    handler = CockpitHandover()
    result = await handler.notify(state)
    state["handover_sent"] = result.get("status") in (
        "sent_to_cockpit", "cockpit_offline"
    )
    if not state["handover_sent"]:
        state["error"] = result.get("error", "Bilinmeyen hata")
    return state


# ─── Frekans Ölçer ────────────────────────────────────────────────────────────
class FrequencyLimiter:
    """Hesap ısıtma ve etkileşim hız sınırlayıcısı."""

    def __init__(self, max_per_minute: int = 5, cooldown: float = 12.0):
        self.max_per_minute = max_per_minute
        self.cooldown = cooldown
        self._log: Dict[str, List[float]] = {}

    async def check_and_wait(self, channel_id: str) -> bool:
        import random
        now = time.time()
        log = self._log.setdefault(channel_id, [])
        self._log[channel_id] = [t for t in log if now - t < 60.0]

        if len(self._log[channel_id]) >= self.max_per_minute:
            logger.warning(
                "Frekans siniri asildi (%s) — %d sn bekleniyor",
                channel_id, int(self.cooldown)
            )
            await asyncio.sleep(self.cooldown)
            return False

        self._log[channel_id].append(now)
        await asyncio.sleep(random.uniform(1.0, 3.0))
        return True


# ─── LangGraph Grafiği ────────────────────────────────────────────────────────
def build_handover_graph():
    if not LANGGRAPH_AVAILABLE:
        return None
    builder = StateGraph(HandoverState)
    builder.add_node("check", check_handover_node)
    builder.add_node("send", send_handover_node)
    builder.set_entry_point("check")
    builder.add_conditional_edges(
        "check",
        lambda s: "send" if s.get("handover_ready") else END,
        {"send": "send", END: END},
    )
    builder.add_edge("send", END)
    return builder.compile()


async def trigger_handover(
    target_username: str,
    achilles_tendon: str,
    frequency_score: float,
    conversation_snippet: str = "",
    chat_history: Optional[List[Dict[str, str]]] = None,
) -> HandoverState:
    """Devir sürecini başlatır. Cockpit'e POST atar."""
    state: HandoverState = {
        "target_username": target_username,
        "achilles_tendon": achilles_tendon,
        "frequency_score": frequency_score,
        "conversation_snippet": conversation_snippet,
        "chat_history": chat_history or [],
        "handover_ready": True,
        "handover_sent": False,
        "error": None,
    }

    graph = build_handover_graph()
    if graph:
        result = await graph.ainvoke(state)
        return result
    else:
        state = await check_handover_node(state)
        state = await send_handover_node(state)
        return state


# ─── CLI ──────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Human-in-the-Loop Devir — Cockpit WebSocket")
    parser.add_argument("--target", required=True, help="Hedef kullanici adi (@kullanici)")
    parser.add_argument("--achilles", required=True, help="Psikolojik acik / Asil tendonu")
    parser.add_argument("--score", type=float, default=7.5, help="Frekans skoru (0-10)")
    parser.add_argument("--snippet", default="", help="Son sohbet snippeti")
    args = parser.parse_args()

    result = asyncio.run(
        trigger_handover(
            target_username=args.target,
            achilles_tendon=args.achilles,
            frequency_score=args.score,
            conversation_snippet=args.snippet,
        )
    )
    output = json.dumps(result, ensure_ascii=True, indent=2, default=str)
    sys.stdout.buffer.write(output.encode("utf-8"))
    sys.stdout.buffer.write(b"\n")
