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
from services.memory_delta import record_profile
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

        # Load tasks from disk
        self._load_tasks()

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
    @staticmethod
    def _plan(intent: str) -> Dict[str, bool]:
        """Deterministic routing: hangi servisler calisacak? (LLM yok)"""
        intent_lower = (intent or "").lower()
        words = intent_lower.split()
        # Stem match: keyword herhangi bir kelimenin basinda/icinde var mi?
        persona_kw = ["konus", "etkiles", "cevapla", "sohbet", "mesaj", "yorum", "karsilik", "diyalog"]
        research_kw = ["arastir", "incele", "rapor", "karsilastir", "derinlemesine", "analiz"]
        orch_kw = ["olustur", "calistir", "gonder", "gorev", "otomatik", "planla", "uretim", "icerik"]
        return {
            "need_persona": any(kw in w for kw in persona_kw for w in words),
            "need_research": any(kw in w for kw in research_kw for w in words) or "analiz et" in intent_lower,
            "need_orchestration": any(kw in w for kw in orch_kw for w in words) or "yap" in words,
        }

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
            # 0. ROUTING PLAN
            plan = self._plan(intent)
            report["plan"] = plan

            # 1. INTENT & SCRAPE
            await self._step(record, "intent", "ok", f"Görev kaydedildi: {intent}")

            # HUMAN APPROVAL BOUNDARY
            action_kws = ["follow", "message", "send_dm", "comment", "post", "mesaj at", "takip et"]
            if any(kw in intent.lower() for kw in action_kws):
                record["status"] = "NEEDS_HUMAN"
                await self._step(record, "human_approval", "blocked", "Dış dünya aksiyonu tespit edildi. İnsan onayı bekleniyor.")
                # We stop the pipeline right here if an explicit action requires human oversight.
                # In a fully realized event system, the pipeline would pause and wait for a callback.
                return record
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

                            # MemoryDelta — profili history'ye kaydet
                            try:
                                delta = record_profile(analyzed_profile)
                                if delta:
                                    report["memory_delta"] = {
                                        "changed_fields": delta.changed_fields,
                                        "reason": delta.reason,
                                    }
                                    await self._step(record, "memory", "ok", f"Delta kaydedildi: {delta.reason}")
                                else:
                                    await self._step(record, "memory", "ok", "Ilk kayit, delta yok")
                            except Exception as exc:
                                logger.warning("MemoryDelta hatasi: %s", exc)
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

                                # COLLECT_MORE auto-retry (maksimum 1 ek deneme)
                                uncertainty = graph_result.get("uncertainty") or {}
                                if uncertainty.get("collect_more_count", 0) > 0:
                                    try:
                                        logger.info("COLLECT_MORE tetiklendi — force_refresh ile yeniden scrape: %s", target)
                                        scraped_retry = await scrape_target(target, platform, force_refresh=True)
                                        retry_profile = await self.analyzer.analyze(scraped_retry)
                                        retry_profile["username"] = scraped_retry.get("username")
                                        retry_profile["platform"] = scraped_retry.get("platform")
                                        report["analyzed_profile_retry"] = retry_profile
                                        await self._step(record, "scraper_retry", "ok",
                                                         f"COLLECT_MORE: retry tamamlandi, guven={retry_profile.get('overall_confidence', 0):.2f}")
                                    except Exception as exc:
                                        logger.warning("COLLECT_MORE retry basarisiz: %s", exc)
                                        report["retry_status"] = "failed"
                                else:
                                    report["retry_status"] = "not_needed"
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

            # 2. ELIZA — persona bağlamı (sadece plan gerektiriyorsa)
            if plan["need_persona"]:
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
                    await self._step(record, "eliza", "skipped", "Persona servisi yapilandirilmamis")
            else:
                report["eliza_context"] = None
                await self._step(record, "eliza", "skipped", "Plan gerektirmiyor")

            # 3. DEER-FLOW — uzun bağlamlı analiz (sadece plan gerektiriyorsa)
            if plan["need_research"]:
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
                    await self._step(record, "deerflow", "skipped", "Derin analiz servisi yapilandirilmamis")
            else:
                report["research"] = None
                await self._step(record, "deerflow", "skipped", "Plan gerektirmiyor")

            # 4. AGENT-ZERO — ana orkestratöre emir (sadece plan gerektiriyorsa)
            if plan["need_orchestration"]:
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
                    await self._step(record, "agent_zero", "skipped", "Agent orkestratoru yapilandirilmamis")
            else:
                report["agent_zero"] = None
                await self._step(record, "agent_zero", "skipped", "Plan gerektirmiyor")

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

            # 7. FINISH - Evaluate semantics based on step success
            has_failures = any(step["status"] == "failed" for step in record["steps"])
            has_unavailable = any(step["status"] == "unavailable" for step in record["steps"])

            if has_failures:
                record["status"] = "FAILED"
                await self._step(record, "finish", "failed", "Görev hatalarla sonlandı")
            elif has_unavailable:
                record["status"] = "PARTIAL"
                await self._step(record, "finish", "partial", "Görev kısmi başarıyla sonlandı (bazı servisler kapalıydı)")
            elif record.get("status") == "NEEDS_HUMAN":
                # Preserved if set by human approval boundary
                await self._step(record, "finish", "blocked", "Görev insan onayı bekliyor")
            else:
                record["status"] = "SUCCESS"
                await self._step(record, "finish", "ok", "Görev başarıyla tamamlandı")

            record["result"] = report

        except Exception as exc:
            record["status"] = "FAILED"
            record["error"] = str(exc)
            logger.exception("[%s] görev başarısız", task_id)
            await self._step(record, "finish", "failed", f"Kritik Hata: {exc}")
        finally:
            record["finished_at"] = datetime.now(timezone.utc).isoformat()
        return record


    def _load_tasks(self):
        try:
            if os.path.exists(TASKS_FILE):
                with open(TASKS_FILE, "r") as f:
                    self._tasks = json.load(f)
            else:
                os.makedirs(os.path.dirname(TASKS_FILE), exist_ok=True)
                self._tasks = {}
        except Exception as exc:
            logger.error(f"Error loading tasks from disk: {exc}")
            self._tasks = {}

    def _save_tasks(self):
        try:
            os.makedirs(os.path.dirname(TASKS_FILE), exist_ok=True)
            with open(TASKS_FILE, "w") as f:
                json.dump(self._tasks, f, indent=2, ensure_ascii=False)
        except Exception as exc:
            logger.error(f"Error saving tasks to disk: {exc}")

    def get_task(self, task_id: str) -> Optional[Dict[str, Any]]:
        return self._tasks.get(task_id)

    def list_tasks(self) -> Dict[str, Dict[str, Any]]:
        return dict(self._tasks)

    async def health_async(self) -> Dict[str, bool]:
        return await self._service_health()
