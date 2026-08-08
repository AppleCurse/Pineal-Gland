"""Kapalı devre orkestratör.

Pipeline (her adım loglanır; servis ayakta değilse adım "unavailable" olarak
işaretlenir ve sistem durmaz):

    1. INTENT     : görevin kaydı
    2. PLAN       : routing + validation planı
    3. EXECUTION  : servis çağrıları (Eliza, DeerFlow, Analyzer, Resonance)
    4. VALIDATION : sonuç doğrulama (COLLECT_MORE döngüsü dahil)
    5. SUCCESS/FAILED/PARTIAL : gerçek durum

Dependency Injection: tüm servis istemcileri constructor'dan alinir.
Yarin Agent-Zero yerine baska orchestrator takmak tek satir degisikliktir.
"""
from __future__ import annotations

import asyncio
import json
import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional, Protocol

from config import Settings
from services.agent_zero import AgentZeroClient
from services.deerflow import DeerFlowClient
from services.eliza import ElizaClient
from services.canonical_memory import get_canonical_memory, CanonicalMemoryAdapter
from services.handover import FrequencyLimiter, CockpitHandover
from services.scraper import scrape_target
from services.session_store import SessionStore
from services.uitars import GUIAgent, PlaywrightOperator, UITarsModelClient
from services.analyzer import ProfileAnalyzer
from services.llm_gateway import LLMGateway
from services.memory_delta import record_profile
from resonance_graph import create_resonance_graph

logger = logging.getLogger("agent_core.orchestrator")


# ---------------------------------------------------------------------------
# Task State Persistence — RAM'den kalıcı depolamaya geçiş
# ---------------------------------------------------------------------------

class TaskStateStore:
    """Task state'leri kalıcı olarak saklar (JSON dosya).
    
    Process restart sonrası task history kaybolmaz.
    """
    
    def __init__(self, storage_path: str = "./data/task_state.json"):
        self.storage_path = Path(storage_path)
        self.storage_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = asyncio.Lock()
        self._cache: Dict[str, Dict[str, Any]] = {}
        self._load_from_disk()
    
    def _load_from_disk(self) -> None:
        """Diskten state yükle."""
        if self.storage_path.exists():
            try:
                with open(self.storage_path, "r", encoding="utf-8") as f:
                    self._cache = json.load(f)
                logger.info("Task state store yüklendi: %d task", len(self._cache))
            except Exception as exc:
                logger.warning("Task state load hatası: %s — boş cache ile başlıyor", exc)
                self._cache = {}
        else:
            self._cache = {}
    
    async def save_to_disk(self) -> None:
        """Cache'i diske yaz."""
        async with self._lock:
            try:
                with open(self.storage_path, "w", encoding="utf-8") as f:
                    json.dump(self._cache, f, indent=2, ensure_ascii=False)
                logger.debug("Task state store kaydedildi: %d task", len(self._cache))
            except Exception as exc:
                logger.error("Task state save hatası: %s", exc)
    
    async def set_task(self, task_id: str, record: Dict[str, Any]) -> None:
        """Task state güncelle ve diske yaz."""
        async with self._lock:
            self._cache[task_id] = record
        await self.save_to_disk()
    
    def get_task(self, task_id: str) -> Optional[Dict[str, Any]]:
        """Task state oku."""
        return self._cache.get(task_id)
    
    def list_tasks(self) -> Dict[str, Dict[str, Any]]:
        """Tüm taskları listele."""
        return dict(self._cache)
    
    async def delete_task(self, task_id: str) -> bool:
        """Task sil."""
        async with self._lock:
            if task_id in self._cache:
                del self._cache[task_id]
                await self.save_to_disk()
                return True
        return False


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
        
        # Task State Persistence — RAM yerine kalıcı depolama
        task_state_path = getattr(settings, 'task_state_path', './data/task_state.json')
        self.task_store = TaskStateStore(task_state_path)
        self._lock = asyncio.Lock()

    # ------------------------------------------------------------------
    async def register_task(self, task_id: str, intent: str) -> Dict[str, Any]:
        record = {
            "task_id": task_id,
            "intent": intent,
            "status": "running",
            "steps": [],
            "created_at": datetime.now(timezone.utc).isoformat(),
            "finished_at": None,
            "result": None,
            "error": None,
            "validation_status": None,  # SUCCESS, FAILED, PARTIAL, BLOCKED, NEEDS_HUMAN
        }
        await self.task_store.set_task(task_id, record)
        return record

    async def _step(self, record: Dict[str, Any], name: str, status: str, detail: str) -> None:
        step = {"step": name, "status": status, "detail": detail,
                "ts": datetime.now(timezone.utc).isoformat()}
        record["steps"].append(step)
        logger.info("[%s] %s -> %s: %s", record["task_id"], name, status, detail)
        # Her adım sonrası state'i kalıcı hale getir
        await self.task_store.set_task(record["task_id"], record)

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
    def _plan(intent: str) -> Dict[str, Any]:
        """Deterministic routing + plan: hangi servisler calisacak? (LLM yok)
        
        Gerçek planlama adımları:
        1. observe (scrape)
        2. analyze (behavioral signals)
        3. verify (uncertainty check)
        4. research (opsiyonel, derin analiz)
        5. generate (strategy)
        6. human_approval (aksiyon öncesi)
        
        Bu sadece routing filtresi, gerçek Planner değil.
        """
        intent_lower = (intent or "").lower()
        words = intent_lower.split()
        # Stem match: keyword herhangi bir kelimenin basinda/icinde var mi?
        persona_kw = ["konus", "etkiles", "cevapla", "sohbet", "mesaj", "yorum", "karsilik", "diyalog"]
        research_kw = ["arastir", "incele", "rapor", "karsilastir", "derinlemesine", "analiz"]
        orch_kw = ["olustur", "calistir", "gonder", "gorev", "otomatik", "planla", "uretim", "icerik"]
        action_kw = ["takip", "gonder", "mesaj", "yorum", "beğen", "paylas"]
        
        need_action = any(kw in w for kw in action_kw for w in words)
        
        return {
            "need_persona": any(kw in w for kw in persona_kw for w in words),
            "need_research": any(kw in w for kw in research_kw for w in words) or "analiz et" in intent_lower,
            "need_orchestration": any(kw in w for kw in orch_kw for w in words) or "yap" in words,
            "need_human_approval": need_action,  # Dış dünya aksiyonları için insan onayı gerekli
            "steps": [
                "observe",      # scrape
                "analyze",      # behavioral signals
                "verify",       # uncertainty check
                "generate",     # strategy
            ] + (["human_approval"] if need_action else []) + ["execute"],
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
                            
                            # Canonical Memory — tekil memory sistemine de kaydet
                            try:
                                canonical = get_canonical_memory()
                                result = canonical.store_profile(
                                    platform=platform or "unknown",
                                    username=target.split("/")[-1] if target else "unknown",
                                    profile=analyzed_profile,
                                    source="orchestrator"
                                )
                                report["canonical_memory"] = result
                                logger.info(f"Canonical memory: {result['status']} - {result.get('key', 'N/A')}")
                            except Exception as exc:
                                logger.warning("Canonical Memory hatasi: %s", exc)
                                report["canonical_memory_error"] = str(exc)
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

                                # COLLECT_MORE döngüsü — yeniden scrape + analyze + Resonance tekrar
                                uncertainty = graph_result.get("uncertainty") or {}
                                if uncertainty.get("collect_more_count", 0) > 0:
                                    try:
                                        logger.info("COLLECT_MORE tetiklendi — yeniden scrape + analyze + Resonance: %s", target)
                                        scraped_retry = await scrape_target(target, platform, force_refresh=True)
                                        retry_profile = await self.analyzer.analyze(scraped_retry)
                                        retry_profile["username"] = scraped_retry.get("username")
                                        retry_profile["platform"] = scraped_retry.get("platform")
                                        
                                        # Yeniden Resonance Engine'e gönder
                                        initial_state_retry = {
                                            "profile": retry_profile,
                                            "score": 0.0,
                                            "strategy": "",
                                            "messages_sent": 0,
                                            "handover_ready": False,
                                            "status": "init",
                                            "cookies": cookies,
                                        }
                                        graph_result_retry = await self.resonance_graph.ainvoke(initial_state_retry)
                                        report["resonance_engine_retry"] = graph_result_retry
                                        
                                        await self._step(record, "scraper_retry", "ok",
                                                         f"COLLECT_MORE: retry + Resonance tamamlandi, guven={retry_profile.get('overall_confidence', 0):.2f}")
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

            # 7. VALIDATION — görev başarısını doğrula
            validation_status = self._validate_task_completion(record, report)
            record["validation_status"] = validation_status
            
            # 8. FINISH — gerçek duruma göre set et
            if validation_status == "SUCCESS":
                record["status"] = "success"
                await self._step(record, "finish", "ok", "Görev başarıyla tamamlandı")
            elif validation_status == "PARTIAL":
                record["status"] = "partial"
                await self._step(record, "finish", "ok", "Görev kısmen tamamlandı")
            elif validation_status == "NEEDS_HUMAN":
                record["status"] = "blocked"
                await self._step(record, "finish", "blocked", "İnsan onayı bekliyor")
            else:  # FAILED
                record["status"] = "failed"
                await self._step(record, "finish", "failed", "Görev doğrulama başarısız")
        except Exception as exc:
            record["status"] = "failed"
            record["error"] = str(exc)
            record["validation_status"] = "FAILED"
            logger.exception("[%s] görev başarısız", task_id)
            await self._step(record, "finish", "failed", f"Hata: {exc}")
        finally:
            record["finished_at"] = datetime.now(timezone.utc).isoformat()
        return record

    def _validate_task_completion(self, record: Dict[str, Any], report: Dict[str, Any]) -> str:
        """Görev başarısını doğrula: SUCCESS, PARTIAL, FAILED, NEEDS_HUMAN.
        
        'finished' artık yalnızca gerçekten doğrulanmış başarıda kullanılır.
        """
        steps = record.get("steps", [])
        step_statuses = [s.get("status") for s in steps]
        
        # Kritik adımların başarısını kontrol et
        critical_failed = any(
            s.get("status") == "failed" 
            for s in steps 
            if s.get("step") in ("analyzer", "resonance_engine", "scraper")
        )
        
        if critical_failed:
            return "FAILED"
        
        # Resonance Engine sonucu var mı?
        resonance = report.get("resonance_engine_retry") or report.get("resonance_engine")
        if resonance:
            uncertainty = resonance.get("uncertainty") or {}
            flagged_count = uncertainty.get("flagged_count", 0)
            
            # FLAG çok yüksekse insan onayı gerekli
            if flagged_count > 3:
                return "NEEDS_HUMAN"
            
            # Handover ready mi?
            if resonance.get("handover_ready"):
                return "SUCCESS"
            
            # Strategy belirlenmişse en azından partial
            if resonance.get("strategy"):
                return "PARTIAL"
        
        # Analyzer çalıştıysa ve sonuç ürettiyse partial
        if report.get("analyzed_profile"):
            return "PARTIAL"
        
        # Hiçbir kritik adım başarısız değil ama sonuç da yok
        if all(s.get("status") in ("ok", "skipped", "unavailable") for s in steps):
            return "PARTIAL"
        
        return "FAILED"

    def get_task(self, task_id: str) -> Optional[Dict[str, Any]]:
        return self.task_store.get_task(task_id)

    def list_tasks(self) -> Dict[str, Dict[str, Any]]:
        return self.task_store.list_tasks()

    async def health_async(self) -> Dict[str, bool]:
        return await self._service_health()
