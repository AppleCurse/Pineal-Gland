"""Kapalı devre orkestratörü.

Pipeline (her adım loglanır; servis ayakta değilse adım "unavailable" olarak
işaretlenir ve sistem durmaz):

    1. INTENT     : görevin kaydı
    2. ELIZA      : persona + RAG hafızasından hedef bağlamı çek
    3. DEER-FLOW  : uzun bağlamlı derin analiz raporu üret
    4. AGENT-ZERO : emri (rapor+bağlam ile) ana orkestratöre ilet; iç dinamik
                    alt-ajanları o kendi yaratır
    5. UI-TARS    : görsel görev verilmişse piksel tabanlı ajanı çalıştır
    6. SESSION    : platform/hesap verilmişse şifreli oturumu kaydet/yenile
    7. FINISH     : özet + sonuç döndür
"""
from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from config import Settings
from services.agent_zero import AgentZeroClient
from services.deerflow import DeerFlowClient
from services.eliza import ElizaClient
from services.handover import FrequencyLimiter, CockpitHandover
from services.scraper import scrape_target
from services.session_store import SessionStore
from services.uitars import GUIAgent, PlaywrightOperator, UITarsModelClient
from services.analyzer import ProfileAnalyzer
from resonance_graph import create_resonance_graph

logger = logging.getLogger("agent_core.orchestrator")


class OrchestratorError(RuntimeError):
    pass


class Orchestrator:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.az = AgentZeroClient(
            settings.agent_zero_url, settings.agent_zero_api_key,
            timeout=settings.http_timeout, max_retries=settings.max_retries,
        )
        self.df = DeerFlowClient(settings.deerflow_url, timeout=settings.http_timeout * 2)
        self.eliza = ElizaClient(settings.eliza_url, settings.eliza_agent_id, settings.eliza_token)
        self.sessions = SessionStore(settings.session_store_path, settings.session_store_key)
        self.analyzer = ProfileAnalyzer()
        self.limiter = FrequencyLimiter()
        self.handover = CockpitHandover()
        self.resonance_graph = create_resonance_graph()
        self._tasks: Dict[str, Dict[str, Any]] = {}
        self._lock = asyncio.Lock()

    # ------------------------------------------------------------------
    def register_task(self, task_id: str, intent: str) -> Dict[str, Any]:
        record = {
            "task_id": task_id,
            "intent": intent,
            "status": "running",
            "steps": [],
            "created_at": datetime.now(timezone.utc).isoformat(),
            "finished_at": None,
            "result": None,
            "error": None,
        }
        self._tasks[task_id] = record
        return record

    async def _step(self, record: Dict[str, Any], name: str, status: str, detail: str) -> None:
        step = {"step": name, "status": status, "detail": detail,
                "ts": datetime.now(timezone.utc).isoformat()}
        record["steps"].append(step)
        logger.info("[%s] %s -> %s: %s", record["task_id"], name, status, detail)

    async def _service_health(self) -> Dict[str, bool]:
        return {
            "agent_zero": await self.az.health(),
            "deerflow": await self.df.health(),
            "eliza": await self.eliza.health(),
        }

    # ------------------------------------------------------------------
    async def run_pipeline(
        self,
        intent: str,
        target: Optional[str] = None,
        platform: Optional[str] = None,
        account: Optional[str] = None,
        visual_task: Optional[str] = None,
        task_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        task_id = task_id or uuid.uuid4().hex[:12]
        record = self.register_task(task_id, intent)
        report: Dict[str, Any] = {"intent": intent, "target": target}
        try:
            # 1. INTENT & SCRAPE
            await self._step(record, "intent", "ok", f"Görev kaydedildi: {intent}")
            if target:
                report["target"] = target
                # Frekans ve ısınma kontrolü
                await self.limiter.check_and_wait(target)
                try:
                    scraped_data = await scrape_target(target, platform)
                    report["scraped_data"] = scraped_data
                    await self._step(record, "scraper", "ok", f"Hedef tarandı: {target} (takipçi: {scraped_data.get('followers')})")

                    # Psikolojik profil analizi
                    try:
                        analyzed_profile = await self.analyzer.analyze(scraped_data)
                        analyzed_profile["username"] = scraped_data.get("username")
                        analyzed_profile["platform"] = scraped_data.get("platform")
                        report["analyzed_profile"] = analyzed_profile
                        await self._step(record, "analyzer", "ok", f"Profil analiz edildi: Rezonans {analyzed_profile.get('resonance_score')}")

                        # Rezonans motoru (LangGraph)
                        try:
                            current_account = account or "default"
                            session_data = None
                            if platform:
                                session_data = self.sessions.load(platform, current_account)

                            cookies = session_data.get("cookies", []) if session_data else []

                            initial_state = {
                                "profile": analyzed_profile,
                                "score": 0.0,
                                "strategy": "",
                                "messages_sent": 0,
                                "handover_ready": False,
                                "status": "init",
                                "cookies": cookies,
                            }
                            graph_result = await self.resonance_graph.ainvoke(initial_state)
                            report["resonance_engine"] = graph_result
                            await self._step(record, "resonance_engine", "ok", f"Rezonans motoru çalıştı: strateji={graph_result.get('strategy')}")
                        except Exception as exc:
                            report["resonance_engine"] = None
                            await self._step(record, "resonance_engine", "failed", f"Rezonans motoru hatası: {exc}")

                    except Exception as exc:
                        report["analyzed_profile"] = None
                        await self._step(record, "analyzer", "failed", f"Profil analizi yapılamadı: {exc}")

                except Exception as exc:
                    report["scraped_data"] = None
                    report["analyzed_profile"] = None
                    await self._step(record, "scraper", "failed", f"Tarama yapılamadı: {exc}")

            # 2. ELIZA — persona bağlamı
            room = target or intent[:40]
            try:
                ctx = await self.eliza.recall(room)
                report["eliza_context"] = ctx
                await self._step(record, "eliza", "ok",
                                 f"Persona hafızası okundu (room={room}, {len(ctx)} karakter)")
            except Exception as exc:
                report["eliza_context"] = None
                await self._step(record, "eliza", "unavailable", f"Eliza erişilemedi: {exc}")

            # 3. DEER-FLOW — uzun bağlamlı analiz
            query = f"Kültürel frekans analizi hedefi: {target or intent}"
            try:
                research = await self.df.run_research(query, self.settings.deerflow_assistant_id)
                report["research"] = research
                await self._step(record, "deerflow", "ok",
                                 f"Derin analiz tamamlandı (thread={research.get('thread_id')})")
            except Exception as exc:
                report["research"] = None
                await self._step(record, "deerflow", "unavailable", f"Deer-Flow erişilemedi: {exc}")

            # 4. AGENT-ZERO — ana orkestratöre emir (iç alt-ajanları o yönetir)
            command = (
                f"Yeni görev. Niyet: {intent}\n"
                f"Hedef: {target or 'belirtilmedi'}\n"
                f"Derin analiz raporu: {str(report.get('research'))[:800]}\n"
                f"Persona bağlamı: {str(report.get('eliza_context'))[:400]}\n"
                "Bu görev için gerekli alt-ajanları dinamik olarak oluştur, işi "
                "yürüt ve tamamlanınca sonlandır. Sonucu raporla."
            )
            try:
                az_result = await self.az.send_message(command, agent_profile="default")
                report["agent_zero"] = az_result
                await self._step(record, "agent_zero", "ok",
                                 f"Orkestrasyon yanıtı alındı (context={az_result.get('context_id')})")
            except Exception as exc:
                report["agent_zero"] = None
                await self._step(record, "agent_zero", "unavailable", f"Agent-Zero erişilemedi: {exc}")

            # 5. UI-TARS — piksel tabanlı görsel görev
            if visual_task:
                try:
                    operator = PlaywrightOperator(start_url=target or "https://example.com")
                    model = UITarsModelClient(self.settings.uitars_remote_endpoint)
                    agent = GUIAgent(operator, model, visual_task)
                    uitars_result = await agent.run()
                    report["uitars"] = uitars_result
                    await self._step(record, "uitars", "ok",
                                     f"Görsel görev tamamlandı (adım {uitars_result.get('step')})")
                except Exception as exc:
                    report["uitars"] = None
                    await self._step(record, "uitars", "unavailable", f"UI-TARS çalışamadı: {exc}")

            # 6. SESSION — şifreli oturum (varsa)
            if platform and account:
                existing = self.sessions.load(platform, account)
                if existing:
                    await self._step(record, "session", "ok",
                                     f"Oturum yüklendi ({platform}/{account}, {len(existing.get('cookies', {}))} çerez)")
                    report["session"] = {"loaded": True, "platform": platform, "account": account}
                else:
                    await self._step(record, "session", "ok",
                                     f"Oturum bulunamadı ({platform}/{account}) — canlı giriş gerekli")
                    report["session"] = {"loaded": False, "platform": platform, "account": account}

            # 7. FINISH
            record["status"] = "finished"
            record["result"] = report
            await self._step(record, "finish", "ok", "Görev tamamlandı")
        except Exception as exc:
            record["status"] = "failed"
            record["error"] = str(exc)
            logger.exception("[%s] görev başarısız", task_id)
            await self._step(record, "finish", "failed", f"Hata: {exc}")
        finally:
            record["finished_at"] = datetime.now(timezone.utc).isoformat()
        return record

    def get_task(self, task_id: str) -> Optional[Dict[str, Any]]:
        return self._tasks.get(task_id)

    def list_tasks(self) -> Dict[str, Dict[str, Any]]:
        return dict(self._tasks)

    async def health_async(self) -> Dict[str, bool]:
        return await self._service_health()
