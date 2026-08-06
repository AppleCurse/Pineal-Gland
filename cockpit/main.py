"""
AI Agent Cockpit — FastAPI + WebSocket + GERÇEK Playwright tarayıcı.

Orta: canli tarayici aynasi (gerçek Playwright ekran görüntüsü akışı)
Alt  : canli sohbet (Mösyö <-> Ajan) + tarayici komutlari
Ust  : beceri kutucuklari (tiklanabilir ac/kapat)
Yan  : kalici hafiza + kisilik ayarlari (JSON dosyasinda saklanir)

Calistirma:
    python main.py          -> http://localhost:5050
"""
from __future__ import annotations

import asyncio
import json
import os
import re
import sys
import time
import uuid
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

try:
    from dotenv import load_dotenv

    load_dotenv()
except Exception:  # python-dotenv yoksa sorun degil
    pass

try:
    import httpx
except Exception:  # httpx yoksa LLM entegrasyonu pasif kalir
    httpx = None

from browser_agent import browser

BASE_DIR = Path(__file__).resolve().parent
TEMPLATES_DIR = BASE_DIR / "templates"
MEMORY_FILE = BASE_DIR / "memory.json"
PERSONALITY_FILE = BASE_DIR / "personality.json"
SKILLS_FILE = BASE_DIR / "skills.json"

OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "")

OPENROUTER_MODEL = os.getenv("OPENROUTER_MODEL", "anthropic/claude-sonnet-5")

# MissionBrief cikti dosyasi (agent_core ile ortak)
AGENT_CORE_DIR = BASE_DIR.parent / "agent_core"
MISSION_BRIEF_FILE = AGENT_CORE_DIR / "current_mission_brief.json"

STREAM_ENABLED = True  # canli ayna akisi acik/kapali (WS: stream_toggle)


@asynccontextmanager
async def lifespan(_: FastAPI):
    asyncio.create_task(browser.start())
    asyncio.create_task(mirror_stream())
    yield
    await browser.stop()


app = FastAPI(title="Ajan Kokpiti", version="0.2.0", lifespan=lifespan)
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


# ---------------------------------------------------------------------------
# Veri modelleri
# ---------------------------------------------------------------------------
class RadarCommand(BaseModel):
    intent: str


class PersonalityUpdate(BaseModel):
    updates: Dict[str, Any]


# ---------------------------------------------------------------------------
# Kalici Hafiza Motoru (JSON dosyasinda saklanir)
# ---------------------------------------------------------------------------
class MemoryEngine:
    def __init__(self, filepath: Path):
        self.filepath = filepath
        self.data: Dict[str, Any] = self._load()

    def _load(self) -> Dict[str, Any]:
        if self.filepath.exists():
            try:
                return json.loads(self.filepath.read_text(encoding="utf-8"))
            except Exception:
                pass
        return {"profiles": {}, "conversations": {}, "learnings": {}, "log": []}

    def _touch(self, category: str) -> Dict[str, Any]:
        if category not in self.data:
            self.data[category] = {}
        return self.data[category]

    def remember(self, category: str, key: str, value: Any) -> None:
        self._touch(category)[key] = value
        self._log("remember", category, key)
        self.save()

    def recall(self, category: str, key: Optional[str] = None) -> Any:
        bucket = self.data.get(category, {})
        if key is not None:
            return bucket.get(key)
        return bucket

    def forget(self, category: str, key: str) -> bool:
        bucket = self.data.get(category)
        if bucket and key in bucket:
            del bucket[key]
            self._log("forget", category, key)
            self.save()
            return True
        return False

    def clear(self) -> None:
        self.data = {"profiles": {}, "conversations": {}, "learnings": {}, "log": []}
        self.save()

    def _log(self, action: str, category: str, key: str) -> None:
        self.data.setdefault("log", []).append(
            {
                "action": action,
                "category": category,
                "key": key,
                "ts": datetime.now().isoformat(),
            }
        )

    def save(self) -> None:
        self.filepath.write_text(
            json.dumps(self.data, indent=2, ensure_ascii=False), encoding="utf-8"
        )

    def stats(self) -> Dict[str, int]:
        return {
            "profiles": len(self.recall("profiles")),
            "conversations": len(self.recall("conversations")),
            "learnings": len(self.recall("learnings")),
            "log": len(self.data.get("log", [])),
        }


memory = MemoryEngine(MEMORY_FILE)


# ---------------------------------------------------------------------------
# Kisilik Motoru
# ---------------------------------------------------------------------------
class PersonalityEngine:
    DEFAULT = {
        "name": "Mösyö'nün Ajansı",
        "tone": "entelektüel, samimi, doğrudan",
        "rules": [
            "Asla 'Selam, naber?' deme.",
            "Hedefin paylaştığı spesifik bir detayı yakala.",
            "Yapay / primci profilleri anında ele.",
            "Sohbet gerçek frekansı yakalayınca devret.",
        ],
        "interests": ["sinema", "edebiyat", "müzik", "felsefe", "sokak kültürü"],
        "dealbreakers": ["özensiz dil", "popülist caps", "sahte derinlik", "gösteriş"],
        "voice": "Sen Mösyö'nün kültürel radarısın. Onun frekansına uyan profilleri sezersin, sığ kişileri elersin.",
        "custom_prompt": "",
    }

    def __init__(self, filepath: Path):
        self.filepath = filepath
        self.data: Dict[str, Any] = self._load()

    def _load(self) -> Dict[str, Any]:
        if self.filepath.exists():
            try:
                return json.loads(self.filepath.read_text(encoding="utf-8"))
            except Exception:
                pass
        self._write(self.DEFAULT)
        return dict(self.DEFAULT)

    def _write(self, data: Dict[str, Any]) -> None:
        self.filepath.write_text(
            json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8"
        )

    def update(self, updates: Dict[str, Any]) -> None:
        self.data.update(updates)
        self._write(self.data)

    def get(self) -> Dict[str, Any]:
        return self.data


personality = PersonalityEngine(PERSONALITY_FILE)


# ---------------------------------------------------------------------------
# Beceri Motoru
# ---------------------------------------------------------------------------
class SkillsEngine:
    DEFAULT_SKILLS = [
        {"id": "scout", "name": "Keşif & Tarama", "icon": "🔍", "active": True,
         "description": "Instagram/X üzerinde profilleri tara"},
        {"id": "vision", "name": "Görsel Analiz", "icon": "👁️", "active": True,
         "description": "Fotoğraf estetiği, renk paleti, mekân kalitesi"},
        {"id": "psych", "name": "Davranış Sinyali", "icon": "🧠", "active": True,
         "description": "Metin/görsel sinyallerinden olasılıksal profil"},
        {"id": "icebreaker", "name": "Buz Kırıcı", "icon": "💬", "active": True,
         "description": "Hedefe özel ilk mesaj üretimi"},
        {"id": "warmup", "name": "Isıtma & Diyalog", "icon": "🔥", "active": False,
         "description": "Sohbeti ilerlet, frekansı ölç"},
        {"id": "handover", "name": "Devir", "icon": "🔔", "active": True,
         "description": "Frekans yakalanınca Mösyö'ye bildir"},
        {"id": "memory", "name": "Kalıcı Hafıza", "icon": "💾", "active": True,
         "description": "Profilleri ve diyalogları hatırla"},
        {"id": "stealth", "name": "Gizli Mod", "icon": "🕶️", "active": True,
         "description": "İnsan davranışı taklidi, hız sınırı"},
    ]

    def __init__(self, filepath: Path):
        self.filepath = filepath
        self.data: Dict[str, Any] = self._load()

    def _load(self) -> Dict[str, Any]:
        if self.filepath.exists():
            try:
                return json.loads(self.filepath.read_text(encoding="utf-8"))
            except Exception:
                pass
        self._write({"skills": self.DEFAULT_SKILLS})
        return {"skills": list(self.DEFAULT_SKILLS)}

    def _write(self, data: Dict[str, Any]) -> None:
        self.filepath.write_text(
            json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8"
        )

    def toggle(self, skill_id: str) -> Optional[bool]:
        for s in self.data["skills"]:
            if s["id"] == skill_id:
                s["active"] = not s["active"]
                self._write(self.data)
                return s["active"]
        return None

    def get_all(self) -> List[Dict[str, Any]]:
        return self.data["skills"]

    def get_active(self) -> List[str]:
        return [s["id"] for s in self.data["skills"] if s["active"]]


skills = SkillsEngine(SKILLS_FILE)


# ---------------------------------------------------------------------------
# WebSocket baglanti yoneticisi
# ---------------------------------------------------------------------------
class ConnectionManager:
    def __init__(self):
        self.connections: Dict[str, WebSocket] = {}

    async def connect(self, ws: WebSocket) -> str:
        await ws.accept()
        cid = uuid.uuid4().hex[:8]
        self.connections[cid] = ws
        await self.broadcast({"type": "log", "message": f"Bağlandı: {cid}"})
        return cid

    def disconnect(self, cid: str) -> None:
        self.connections.pop(cid, None)

    async def send(self, cid: str, data: dict) -> None:
        ws = self.connections.get(cid)
        if ws:
            try:
                await ws.send_json(data)
            except Exception:
                self.disconnect(cid)

    async def broadcast(self, data: dict) -> None:
        for cid in list(self.connections.keys()):
            await self.send(cid, data)


manager = ConnectionManager()


# ---------------------------------------------------------------------------
# Ajan durumu
# ---------------------------------------------------------------------------
class AgentState:
    def __init__(self):
        self.current_page: str = "—"
        self.status: str = "Hazır"
        self.activity: str = "Tarama başlatılmadı."
        self.current_profile: Optional[str] = None
        self.radar_active: bool = False
        self.current_intent: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "current_page": browser.current_url or self.current_page,
            "status": self.status,
            "activity": self.activity,
            "current_profile": self.current_profile,
            "radar_active": self.radar_active,
            "current_intent": self.current_intent,
            "browser_running": browser.running,
            "browser_title": browser.title,
        }


agent = AgentState()


# ---------------------------------------------------------------------------
# Opsiyonel LLM (OpenRouter). API anahtari yoksa basit yerel yanitlayici.
# ---------------------------------------------------------------------------
async def llm_respond(system_prompt: str, user_message: str) -> Optional[str]:
    if not OPENROUTER_API_KEY or httpx is None:
        return None
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                "https://openrouter.ai/api/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {OPENROUTER_API_KEY}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": OPENROUTER_MODEL,
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_message},
                    ],
                    "temperature": 0.2,
                },
            )
            resp.raise_for_status()
            return resp.json()["choices"][0]["message"]["content"]
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Tarayici komutlari (sohbetten /go, /type, /scroll ... gibi)
# ---------------------------------------------------------------------------
async def run_browser_command(command: str, arg: str = "") -> str:
    try:
        if command == "go":
            await browser.goto(arg or "https://example.com")
            return f"🌐 Gidildi: {browser.current_url}"
        if command == "search":
            if not arg:
                return "❌ Aranacak sorgu gerekli: /search <sorgu>"
            await browser.search(arg)
            return f"🔎 Arandı: '{arg}' → {browser.current_url}"
        if command == "back":
            await browser.back()
            return f"↩ {browser.current_url}"
        if command == "forward":
            await browser.forward()
            return f"↪ {browser.current_url}"
        if command == "reload":
            await browser.reload()
            return f"⟲ Yenilendi: {browser.current_url}"
        if command == "scroll":
            await browser.scroll("up" if arg == "up" else "down")
            return "📜 Kaydırıldı."
        if command == "type":
            if not arg:
                return "❌ Yazılacak metin gerekli: /type <metin>"
            await browser.type_text(arg)
            return f"⌨️ Yazıldı: {arg[:60]}"
        if command == "enter":
            await browser.press("Enter")
            return "⏎ Enter basıldı."
        if command == "links":
            links = await browser.get_links(15)
            return "\n".join(f"- {l['text'] or l['href']}" for l in links) or "Bağlantı yok."
        if command == "page":
            text = await browser.snapshot_text(1500)
            return "📄 " + text.replace("\n", " ")[:1500]
        if command == "screenshot":
            frame = await browser.screenshot_jpeg(80)
            if frame:
                await manager.broadcast({"type": "mirror_frame", "image": frame})
                return "🖼 Ekran görüntüsü aynaya gönderildi."
            return "❌ Ekran görüntüsü alınamadı."
        if command == "login":
            parts = arg.split(None, 2)
            if len(parts) < 3:
                return (
                    "❌ Kullanım: /login <platform> <kullanıcı> <şifre>\n"
                    "Örnek: /login instagram foto@mail.com şifre123"
                )
            platform_name, uname, passwd = parts[0].lower(), parts[1], parts[2]
            await manager.broadcast({"type": "log", "message": f"{platform_name} girişine başlanıyor..."})
            ok = await browser.do_login(platform_name, uname, passwd)
            if ok:
                return f"✅ {platform_name.title()} girişi BAŞARILI."
            else:
                return f"❌ {platform_name.title()} girişi BAŞARISIZ."
    except Exception as exc:
        return f"⚠️ Tarayıcı hatası: {exc}"
    return f"❌ Bilinmeyen komut: /{command}"


MISSION_BRIEF_SYSTEM_PROMPT = """Sen bir sosyal medya strateji uzmanisın. Kullanicinin serbest metin girdisini analiz ederek
exact olarak su JSON formatinda ciktı uret. Baska hicbir sey yazma, sadece gecerli JSON dondur:
{
  "vibe_concept": "<hedef kitlenin ruh hali ve estetik kimligi, 1-2 Turkce cumle>",
  "core_triggers": ["<motivasyon 1>", "<motivasyon 2>", "<en az 3 madde>"],
  "dealbreakers": ["<kacinilacak oge 1>", "<kacinilacak oge 2>", "<en az 2 madde>"],
  "search_queries": ["<konu anahtar -reklam -spam lang:tr>", "<en az 3, negatif operatorlu sorgu>"]
}"""


async def generate_mission_brief_inline(intent: str) -> Optional[Dict[str, Any]]:
    """OpenRouter'a direkt cagri yaparak MissionBrief JSON uretir."""
    if not httpx:
        return None
    try:
        async with httpx.AsyncClient(timeout=45.0) as client:
            resp = await client.post(
                "https://openrouter.ai/api/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {OPENROUTER_API_KEY}",
                    "Content-Type": "application/json",
                    "HTTP-Referer": "http://localhost:5050",
                    "X-Title": "DijitalVarlik-Cockpit",
                },
                json={
                    "model": OPENROUTER_MODEL,
                    "messages": [
                        {"role": "system", "content": MISSION_BRIEF_SYSTEM_PROMPT},
                        {"role": "user", "content": f"Analiz et ve MissionBrief uret: {intent}"},
                    ],
                    "temperature": 0.3,
                    "max_tokens": 1024,
                },
            )
            resp.raise_for_status()
            raw = resp.json()["choices"][0]["message"]["content"]
            # JSON blogu cıkar
            m = re.search(r"\{.*\}", raw, re.DOTALL)
            parsed = json.loads(m.group(0) if m else raw)
            parsed["raw_input"] = intent
            parsed["generated_at"] = datetime.now().isoformat()
            # Dosyaya kaydet (agent_core ile paylasilir)
            MISSION_BRIEF_FILE.parent.mkdir(parents=True, exist_ok=True)
            MISSION_BRIEF_FILE.write_text(
                json.dumps(parsed, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            return parsed
    except Exception as exc:
        return {"error": str(exc), "raw_input": intent}


async def process_radar(intent: str) -> None:
    """Mosyo'nun niyetini alir; MissionBrief uretir + gercek tarayici ile arama baslar."""
    agent.radar_active = True
    agent.current_intent = intent
    agent.status = "Tariyor..."
    agent.activity = f"Radar frekansi kuruldu: '{intent}'"
    memory.remember(
        "learnings",
        f"radar_{int(time.time())}",
        {"intent": intent, "ts": datetime.now().isoformat()},
    )
    await manager.broadcast(
        {"type": "radar_started", "intent": intent, "ts": datetime.now().isoformat()}
    )
    await manager.broadcast({"type": "log", "message": f"Radar: {intent}"})

    # MissionBrief uret
    await manager.broadcast({"type": "log", "message": "Gorev Karti olusturuluyor..."})
    brief = await generate_mission_brief_inline(intent)
    if brief and "error" not in brief:
        # Frontend'e gorev kartini gonder
        await manager.broadcast({
            "type": "mission_brief_ready",
            "brief": brief,
            "message": "Gorev Karti Olusturuldu",
        })
        await manager.broadcast({
            "type": "chat",
            "sender": "ajan",
            "message": (
                f"Gorev Karti Olusturuldu\n\n"
                f"Vibe: {brief.get('vibe_concept', '')[:120]}\n"
                f"Tetikleyiciler: {', '.join(brief.get('core_triggers', [])[:3])}\n"
                f"Sorgular: {brief.get('search_queries', [''])[0]}"
            ),
            "ts": datetime.now().isoformat(),
        })
    else:
        err = (brief or {}).get("error", "Bilinmeyen hata")
        await manager.broadcast({"type": "log", "message": f"MissionBrief hatasi: {err}"})

    # --- Platform bazli arama stratejisi ---
    # MissionBrief varsa ilk sorguyu kullan, yoksa ham niyeti kullan
    search_queries = []
    if brief and "error" not in brief:
        search_queries = brief.get("search_queries", [])

    first_query = (search_queries[0] if search_queries else intent).split("|")[0].strip()

    if browser.running:
        # X (Twitter) — login gerektirmez, profil arama calisiyor
        await manager.broadcast({"type": "log", "message": f"X profil arama: {first_query[:60]}"})
        result = await browser.platform_search(first_query, platform="x")
        await asyncio.sleep(2)

        # Instagram durumu
        try:
            from social_login import has_session
            if has_session("instagram"):
                await manager.broadcast({"type": "log", "message": "Instagram session aktif — explore aramasi baslatiliyor..."})
                await browser.platform_search(first_query, platform="instagram")
            else:
                # Login yoksa X'te kal, kullaniciya bildir
                await manager.broadcast({
                    "type": "chat",
                    "sender": "ajan",
                    "message": (
                        f"X profil arama AKTIF -> {result.get('url', 'x.com')[:80]}\n\n"
                        "Instagram icin:\n"
                        "/login instagram EMAIL SIFRE\n"
                        "komutunu yaz — bir kez giris yap, session kaydedilir."
                    ),
                    "ts": datetime.now().isoformat(),
                })
        except ImportError:
            pass

        await manager.broadcast({"type": "log", "message": "Tarama hazir. /page veya /links ile icerik goruntule."})


    agent.activity = f"Tarama suruyor: '{first_query}'"
    await manager.broadcast({"type": "agent_status", "agent": agent.to_dict()})


async def build_system_prompt() -> str:
    p = personality.get()
    lines = [
        p["voice"],
        f"Ton: {p['tone']}",
        "Kurallar:",
    ] + [f"- {r}" for r in p["rules"]]
    lines.append(f"İlgiler: {', '.join(p['interests'])}")
    lines.append(f"Kırmızı çizgiler: {', '.join(p['dealbreakers'])}")
    if p.get("custom_prompt"):
        lines.append(p["custom_prompt"])
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Canli ayna akisi (gerçek Playwright ekran görüntüleri)
# ---------------------------------------------------------------------------
async def mirror_stream() -> None:
    global STREAM_ENABLED
    while True:
        try:
            if STREAM_ENABLED and browser.running:
                frame = await browser.screenshot_jpeg(quality=55)
                if frame:
                    await manager.broadcast(
                        {
                            "type": "mirror_frame",
                            "image": frame,
                            "url": browser.current_url,
                            "title": browser.title,
                        }
                    )
        except Exception:
            pass
        await asyncio.sleep(0.8)


# ---------------------------------------------------------------------------
# Sohbet / komut yanitlayici
# ---------------------------------------------------------------------------
def local_reply(message: str) -> str:
    low = message.lower().strip()
    if low.startswith("/status"):
        b = "ÇALIŞIYOR" if browser.running else "KAPALI"
        return (
            f"Durum: {agent.status} | Tarayıcı: {b} | Sayfa: {browser.current_url or '—'} | "
            f"Radar: {'AÇIK' if agent.radar_active else 'KAPALI'}"
        )
    if low.startswith("/memory"):
        return f"🧠 Hafıza: {memory.stats()}"
    if low.startswith("/skills"):
        return "Aktif beceriler: " + ", ".join(skills.get_active())
    if low.startswith("/personality"):
        p = personality.get()
        return f"Kişilik: {p['name']} — ton: {p['tone']}"
    if low.startswith("/help"):
        return (
            "TARAYICI:\n"
            "/go <url> — siteye git\n"
            "/search <sorgu> — arama yap\n"
            "/back · /forward · /reload · /scroll [up]\n"
            "/type <metin> — klavyeden yaz\n"
            "/enter — Enter'a bas\n"
            "/links — sayfadaki bağlantılar\n"
            "/page — sayfa metni\n"
            "/screenshot — tek kare aynaya\n\n"
            "AJAN:\n"
            "/radar <niyet> — günün radar frekansını kur\n"
            "/status · /memory · /skills · /personality · /clear"
        )
    return (
        f"Anlaşıldı Mösyö. '{message}' not edildi. "
        "Komut listesi için /help yaz."
    )


# ---------------------------------------------------------------------------
# Rotalar
# ---------------------------------------------------------------------------
@app.get("/", response_class=HTMLResponse)
async def cockpit(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})


@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    cid = await manager.connect(ws)

    async def send_init():
        await manager.send(
            cid,
            {
                "type": "init",
                "personality": personality.get(),
                "skills": skills.get_all(),
                "memory_stats": memory.stats(),
                "agent": agent.to_dict(),
                "stream_enabled": STREAM_ENABLED,
            },
        )

    await send_init()
    try:
        while True:
            data = await ws.receive_json()
            msg_type = data.get("type")

            if msg_type == "chat":
                message = str(data.get("message", "")).strip()
                if not message:
                    continue
                await manager.broadcast(
                    {"type": "chat", "sender": "mösyö", "message": message,
                     "ts": datetime.now().isoformat()}
                )
                memory.remember("conversations", f"m_{int(time.time())}",
                                {"sender": "mösyö", "message": message})
                agent.activity = f"Sohbet: {message[:48]}"
                await manager.broadcast({"type": "agent_status", "agent": agent.to_dict()})

                parts = message.split(None, 1)
                cmd = parts[0].lower() if parts else ""
                arg = parts[1].strip() if len(parts) > 1 else ""
                reply: Optional[str] = None

                if cmd in ("/go", "/search", "/back", "/forward", "/reload", "/scroll",
                           "/type", "/enter", "/links", "/page", "/screenshot", "/login"):
                    reply = await run_browser_command(cmd[1:], arg)
                elif cmd == "/radar":
                    if arg:
                        await process_radar(arg)
                    else:
                        reply = "❌ Niyet girmelisin: /radar <niyet>"
                else:
                    system_prompt = await build_system_prompt()
                    reply = await llm_respond(system_prompt, message)
                    if reply is None:
                        await asyncio.sleep(0.2)
                        reply = local_reply(message)

                if reply:
                    await manager.broadcast(
                        {"type": "chat", "sender": "ajan", "message": reply,
                         "ts": datetime.now().isoformat()}
                    )
                    memory.remember("conversations", f"a_{int(time.time())}",
                                    {"sender": "ajan", "message": reply})

            elif msg_type == "radar":
                intent = str(data.get("intent", "")).strip()
                if intent:
                    await process_radar(intent)

            elif msg_type == "browser_goto":
                url = str(data.get("url", "")).strip()
                if url:
                    res = await browser.goto(url)
                    await manager.broadcast(
                        {"type": "log", "message": f"🌐 Gidildi: {res['url']}"}
                    )

            elif msg_type == "stream_toggle":
                global STREAM_ENABLED
                STREAM_ENABLED = bool(data.get("on", True))
                await manager.broadcast(
                    {"type": "stream_toggled", "on": STREAM_ENABLED}
                )

            elif msg_type == "toggle_skill":
                skill_id = str(data.get("skill_id", ""))
                active = skills.toggle(skill_id)
                if active is not None:
                    await manager.broadcast(
                        {"type": "skill_toggled", "skill_id": skill_id, "active": active}
                    )
                    await manager.broadcast(
                        {"type": "log", "message": f"Beceri {'AÇIK' if active else 'KAPALI'}: {skill_id}"}
                    )

            elif msg_type == "update_personality":
                updates = data.get("updates", {})
                personality.update(updates)
                await manager.broadcast(
                    {"type": "personality_updated", "personality": personality.get()}
                )
                await manager.broadcast({"type": "log", "message": "Kişilik dosyası güncellendi"})

            elif msg_type == "memory_action":
                action = data.get("action")
                category = str(data.get("category", ""))
                key = str(data.get("key", ""))
                value = data.get("value")
                if action == "remember" and category and key:
                    memory.remember(category, key, value)
                    await manager.broadcast(
                        {"type": "memory_updated", "memory": memory.data, "stats": memory.stats()}
                    )
                elif action == "forget" and category and key:
                    memory.forget(category, key)
                    await manager.broadcast(
                        {"type": "memory_updated", "memory": memory.data, "stats": memory.stats()}
                    )
                elif action == "clear":
                    memory.clear()
                    await manager.broadcast(
                        {"type": "memory_updated", "memory": memory.data, "stats": memory.stats()}
                    )

            elif msg_type == "get_state":
                await send_init()

    except WebSocketDisconnect:
        manager.disconnect(cid)
        await manager.broadcast({"type": "log", "message": f"Ayrıldı: {cid}"})
    except Exception:
        manager.disconnect(cid)


# ---------------------------------------------------------------------------
# REST API (HTTP istemciler / araçlar için)
# ---------------------------------------------------------------------------
@app.post("/api/radar")
async def api_radar(cmd: RadarCommand):
    await process_radar(cmd.intent)
    return {"status": "ok", "intent": cmd.intent}


# ---------------------------------------------------------------------------
# Platform Config API — UI buradan okur/yazar
# ---------------------------------------------------------------------------
class PlatformConfigIn(BaseModel):
    method: str = "login"
    rapidapi_key: str = ""
    chrome_profile_path: str = ""


@app.get("/api/platform/config")
async def get_platform_config():
    from platform_adapter import load_config
    return load_config()


@app.post("/api/platform/config")
async def set_platform_config(cfg: PlatformConfigIn):
    from platform_adapter import load_config, save_config
    current = load_config()
    current["method"] = cfg.method
    if cfg.rapidapi_key:
        current["rapidapi_key"] = cfg.rapidapi_key
    if cfg.chrome_profile_path:
        current["chrome_profile_path"] = cfg.chrome_profile_path
    save_config(current)
    await manager.broadcast({"type": "log", "message": f"Platform yontemi: {cfg.method}"})
    return {"ok": True, "method": cfg.method}


# ---------------------------------------------------------------------------
# Handover Alert endpoint — agent_core buraya POST atar (Telegram YOK)
# ---------------------------------------------------------------------------
class HandoverAlert(BaseModel):
    type: str = "handover_alert"
    target: str
    score: float
    achilles_heel: str
    chat_history: List[Any] = []


@app.post("/api/handover")
async def api_handover(alert: HandoverAlert):
    """agent_core'dan gelen devir sinyalini WebSocket uzerinden yayinlar."""
    payload = {
        "type": "handover_alert",
        "target": alert.target,
        "score": alert.score,
        "achilles_heel": alert.achilles_heel,
        "chat_history": alert.chat_history,
        "ts": datetime.now().isoformat(),
    }
    await manager.broadcast(payload)
    # Ayni zamanda sohbet olarak da gonder
    score_bar = "#" * int(alert.score) + "." * (10 - int(alert.score))
    await manager.broadcast({
        "type": "chat",
        "sender": "sistem",
        "message": (
            f"[DEVIR] IPLER SENDE MOSYO\n"
            f"Hedef: {alert.target}\n"
            f"Asil Tendonu: {alert.achilles_heel}\n"
            f"Frekans: {alert.score:.1f}/10  [{score_bar}]"
        ),
        "ts": datetime.now().isoformat(),
    })
    memory.remember("learnings", f"handover_{int(time.time())}", payload)
    return {"status": "broadcast", "target": alert.target}


@app.get("/api/personality")
async def get_personality():
    return personality.get()


@app.post("/api/personality")
async def update_personality(upd: PersonalityUpdate):
    personality.update(upd.updates)
    await manager.broadcast({"type": "personality_updated", "personality": personality.get()})
    return {"status": "ok"}


@app.get("/api/skills")
async def get_skills():
    return {"skills": skills.get_all()}


@app.post("/api/skills/{skill_id}/toggle")
async def toggle_skill(skill_id: str):
    active = skills.toggle(skill_id)
    if active is None:
        return JSONResponse({"error": "skill bulunamadı"}, status_code=404)
    await manager.broadcast({"type": "skill_toggled", "skill_id": skill_id, "active": active})
    return {"skill_id": skill_id, "active": active}


@app.get("/api/memory")
async def get_memory():
    return memory.data


@app.get("/api/agent/status")
async def get_agent_status():
    return agent.to_dict()


@app.get("/api/browser/status")
async def get_browser_status():
    return browser.status()


@app.get("/health")
async def health():
    return {"status": "alive", "ts": datetime.now().isoformat()}


if __name__ == "__main__":
    import uvicorn

    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    print("[START] Ajan Kokpiti baslatiliyor...")
    print("[URL]   http://localhost:5050")
    uvicorn.run(app, host="0.0.0.0", port=5050)
