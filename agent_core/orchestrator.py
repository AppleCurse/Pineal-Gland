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

Dependency Injection: tüm servis istemcileri constructor'dan alinir.
Yarin Agent-Zero yerine baska orchestrator takmak tek satir degisikliktir.
"""
from __future__ import annotations

import asyncio
import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, Optional, Protocol

from config import Settings
from services.agent_zero import AgentZeroClient
from services.deerflow import DeerFlowClient
from services.eliza import ElizaClient
from services.handover import FrequencyLimiter, CockpitHandover
from services.scraper import scrape_target
from services.session_store import SessionStore
from services.uitars import GUIAgent, PlaywrightOperator, UITarsModelClient
from services.analyzer import ProfileAnalyzer
from services.llm_gateway import LLMGateway
from resonance_graph import create_resonance_graph

logger = logging.getLogger("agent_core.orchestrator")


class OrchestratorError(RuntimeError):
    pass


# ---------------------------------------------------------------------------
# Service protocols — bagimliliklari soyutlar
# ---------------------------------------------------------------------------


class AgentOrchestratorProtocol(Protocol):
    """Herhangi bir alt-ajan orkestratorunun uymasi gereken kontrat."""

    async def send_message(self, message: str, context_id: Optional[str] = None,
                           agent_profile: Optional[str] = None) -> Dict[str, Any]: ...
    async def health(self) -> bool: ...


class ResearchClientProtocol(Protocol):
    """Derin arastirma istemcisi kontrati."""

    async def run_research(self, query: str, assistant_id: Optional[str] = None,
                           context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]: ...
    async def health(self) -> bool: ...


class PersonaClientProtocol(Protocol):
    """Persona + RAG hafiza istemcisi kontrati."""

    async def recall(self, room_id: str) -> str: ...
    async def get_agents(self) -> Any: ...
    async def health(self) -> bool: ...


class ProfileAnalyzerProtocol(Protocol):
    """Profil analiz servisi kontrati."""

    async def analyze(self, scraped_data: Dict[str, Any]) -> Dict[str, Any]: ...


# ---------------------------------------------------------------------------
# Service container (DI)
# ---------------------------------------------------------------------------


@dataclass
class ServiceContainer:
    """Tum servis bagimliliklarini tek bir yerde toplar.

    Orchestrator bu container'daki servisleri kullanir.
    Her servis opsiyoneldir — None ise o adim atlanir.
    """

    agent_orchestrator: Optional[AgentOrchestratorProtocol] = None
    research_client: Optional[ResearchClientProtocol] = None
    persona_client: Optional[PersonaClientProtocol] = None
    profile_analyzer: Optional[ProfileAnalyzerProtocol] = None
    session_store: Optional[SessionStore] = None
    llm_gateway: Optional[LLMGateway] = None


def build_default_services(settings: Settings) -> ServiceContainer:
    """Settings'ten varsayilan servis istemcilerini olusturur."""
    return ServiceContainer(
        agent_orchestrator=AgentZeroClient(
            settings.agent_zero_url, settings.agent_zero_api_key,
            timeout=settings.http_timeout, max_retries=settings.max_retries,
        ),
        research_client=DeerFlowClient(
            settings.deerflow_url, timeout=settings.http_timeout * 2,
        ),
        persona_client=ElizaClient(
            settings.eliza_url, settings.eliza_agent_id, settings.eliza_token,
        ),
        profile_analyzer=ProfileAnalyzer(
            gateway=LLMGateway(
                base_url=settings.llm_gateway_url,
                api_key=settings.llm_gateway_api_key,
                model=settings.llm_model,
                fallback_model=settings.llm_fallback_model,
            ),
        ),
        session_store=SessionStore(
            settings.session_store_path, settings.session_store_key,
        ),
    )


class Orchestrator:
    def __init__(self, settings: Settings, services: Optional[ServiceContainer] = None):
        self.settings = settings
        svc = services or build_default_services(settings)

        # Agent orkestratoru (Agent-Zero veya muadili)
        self.az = svc.agent_orchestrator

        # Derin arastirma (Deer-Flow veya muadili)
        self.df = svc.research_client

        # Persona + hafiza (ElizaOS veya muadili)
        self.eliza = svc.persona_client

        # Profil analiz (behavioral signal extractor)
        self.analyzer = svc.profile_analyzer

        # Oturum deposu
        self.sessions = svc.session_store

        # Altyapi servisleri (bunlar DI'den bagimsiz, hafif)
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
        result: Dict[str, bool] = {}
        if self.az:
            result["agent_zero"] = await self.az.health()
        else:
            result["agent_zero"] = False
        if self.df:
            result["deerflow"] = await self.df.health()
        else:
            result["deerflow"] = False
        if self.eliza:
            result["eliza"] = await self.eliza.health()
        else:
            result["eliza"] = False
        return result

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

                    # Davranissal sinyal cikarimi (behavioral signal extraction)
                    analyzed_profile = None
                    try:
                        if self.analyzer:
                            analyzed_profile = await self.analyzer.analyze(scraped_data)
                            analyzed_profile["username"] = scraped_data.get("username")
                            analyzed_profile["platform"] = scraped_data.get("platform")
                            report["analyzed_profile"] = analyzed_profile
                            confidence = analyzed_profile.get("overall_confidence", 0.0)
                            await self._step(record, "analyzer", "ok",
                                             f"Sinyal cikarimi tamamlandi: guven={confidence:.2f}")
                        else:
                            report["analyzed_profile"] = None
                            await self._step(record, "analyzer", "unavailable", "Profil analiz servisi yapilandirilmamis")

                        # Rezonans motoru (LangGraph)
                        if analyzed_profile:
                            try:
                                current_account = account or "default"
                                session_data = None
                                if platform and self.sessions:
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
                                cv = graph_result.get("compatibility", {})
                                await self._step(record, "resonance_engine", "ok",
                                                 f"Rezonans: composite={cv.get('composite', 0):.2f}, strateji={graph_result.get('strategy')}")
                            except Exception as exc:
                                report["resonance_engine"] = None
                                await self._step(record, "resonance_engine", "failed", f"Rezonans motoru hatası: {exc}")
                        else:
                            report["resonance_engine"] = None

                    except Exception as exc:
                        report["analyzed_profile"] = None
                        await self._step(record, "analyzer", "failed", f"Profil analizi yapılamadı: {exc}")

                except Exception as exc:
                    report["scraped_data"] = None
                    report["analyzed_profile"] = None
                    await self._step(record, "scraper", "failed", f"Tarama yapılamadı: {exc}")

            # 2. ELIZA — persona bağlamı
            room = target or intent[:40]
            if self.eliza:
                try:
                    ctx = await self.eliza.recall(room)
                    report["eliza_context"] = ctx
                    await self._step(record, "eliza", "ok",
                                     f"Persona hafızası okundu (room={room}, {len(ctx)} karakter)")
                except Exception as exc:
                    report["eliza_context"] = None
                    await self._step(record, "eliza", "unavailable", f"Eliza erişilemedi: {exc}")
            else:
                report["eliza_context"] = None
                await self._step(record, "eliza", "unavailable", "Persona servisi yapilandirilmamis")

            # 3. DEER-FLOW — uzun bağlamlı analiz
            if self.df:
                query = f"Kültürel frekans analizi hedefi: {target or intent}"
                try:
                    research = await self.df.run_research(query, self.settings.deerflow_assistant_id)
                    report["research"] = research
                    await self._step(record, "deerflow", "ok",
                                     f"Derin analiz tamamlandı (thread={research.get('thread_id')})")
                except Exception as exc:
                    report["research"] = None
                    await self._step(record, "deerflow", "unavailable", f"Deer-Flow erişilemedi: {exc}")
            else:
                report["research"] = None
                await self._step(record, "deerflow", "unavailable", "Derin analiz servisi yapilandirilmamis")

            # 4. AGENT-ZERO — ana orkestratöre emir (iç alt-ajanları o yönetir)
            if self.az:
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
            else:
                report["agent_zero"] = None
                await self._step(record, "agent_zero", "unavailable", "Agent orkestratoru yapilandirilmamis")

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
            if platform and account and self.sessions:
                try:
                    existing = self.sessions.load(platform, account)
                    if existing:
                        await self._step(record, "session", "ok",
                                         f"Oturum yüklendi ({platform}/{account}, {len(existing.get('cookies', {}))} çerez)")
                        report["session"] = {"loaded": True, "platform": platform, "account": account}
                    else:
                        await self._step(record, "session", "ok",
                                         f"Oturum bulunamadı ({platform}/{account}) — canlı giriş gerekli")
                        report["session"] = {"loaded": False, "platform": platform, "account": account}
                except Exception as exc:
                    await self._step(record, "session", "unavailable", f"Oturum deposu hatası: {exc}")
                    report["session"] = {"loaded": False, "error": str(exc)}

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
