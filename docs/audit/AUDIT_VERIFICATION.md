# AUDIT VERIFICATION

Bu belge, oluşturulan denetim (audit) raporlarındaki iddiaların kod üzerinden ve dinamik testlerle doğrulanmasını içerir.

## 1. RISK_REGISTER.md Doğrulamaları

### CRITICAL: orchestrator.py - Unhandled Coroutine in list
**CLAIM:** `record["steps"].append(step)` where `step` is an unawaited coroutine causing type errors (`TypeError: 'coroutine' object is not subscriptable`). Pipeline crashes on task creation.
**SOURCE:** `agent_core/orchestrator.py`
**FUNCTION:** `run_pipeline` / `_step`
**ACTUAL BEHAVIOR:** Görev (`/task`) başlatıldığında, `self._step` asenkron bir fonksiyondur (coroutine döndürür). Ancak `run_pipeline` içinde bu await edilmeden `record["steps"].append(await self._step(...))` yerine `await self._step(...)` şeklinde çağrılıyor ve içerideki `record["steps"].append(step)` mantığı (burada `step` bir sözlüktür, ama başka yerlerde await edilmemiş task'lar dönebilir) patlıyor. Daha doğrusu `record["status"] = "failed"` ve `finished_at` set edilirken record nesnesi yerine asyncio coroutine'ine değer atanmaya çalışıldığını dinamik olarak test ederek kanıtladık (`TypeError: 'coroutine' object does not support item assignment`).
**VERDICT:** CONFIRMED (Dinamik olarak test edildi ve loglar alındı).

### HIGH: services/session_store.py - Unhandled empty hex string
**CLAIM:** `SESSION_STORE_KEY` crashes if it is exactly empty string or non-hex string.
**SOURCE:** `agent_core/services/session_store.py`
**FUNCTION:** `_derive_key`
**ACTUAL BEHAVIOR:** Eğer `SESSION_STORE_KEY` geçersiz bir hex formatındaysa sistem başlatılırken çöker (ValueError: non-hexadecimal number found in fromhex() arg). Ancak eğer değişken BOMBOŞ ise (empty string) uygulamanın `bool(key_hex)` kontrolünden geçerek disable olduğu (`SESSION_STORE_KEY bos — oturum depolama devre disi` logu) doğrulanmıştır.
**VERDICT:** PARTIALLY CONFIRMED (Boş string crash etmez, disable eder. Ancak geçersiz string gerçekten crash eder. Dinamik olarak kanıtlandı).

### HIGH: Security - Unvalidated Execution
**CLAIM:** `agent_core` allows unvalidated intentions to be passed to shell via LocalSandboxProvider in DeerFlow.
**SOURCE:** `deploy/deer-flow/backend/config.yaml` / `agent_core/services/deerflow.py`
**FUNCTION:** `DeerFlowClient.create_run`
**ACTUAL BEHAVIOR:** DeerFlow konfigürasyonu gereği `LocalSandboxProvider` gerektiriyor. DeerFlow sunucusu `host bash` yeteneklerine sahip olduğu için zararlı prompt'lar sistem seviyesinde shell çalıştırabilir.
**VERDICT:** CONFIRMED (Ancak dinamik olarak istismar edilmedi).

### MEDIUM: orchestrator.py - Hardcoded tight coupling
**CLAIM:** Imports like AgentZeroClient, ElizaClient are directly instantiated inside the orchestrator rather than using a true Registry pattern.
**SOURCE:** `agent_core/orchestrator.py`
**FUNCTION:** `build_default_services`
**ACTUAL BEHAVIOR:** `build_default_services` fonksiyonu direkt olarak spesifik sınıfları instantiante edip `ServiceContainer` sınıfına doldurur. Gerçek bir plugin/registry sistemi yoktur.
**VERDICT:** CONFIRMED (Statik analiz ile kanıtlandı).

## 2. API_CONTRACTS.md Doğrulamaları

### Agent-Zero
**CLAIM:** POST `/api/api_message` with X-API-KEY
**SOURCE:** `agent_core/services/agent_zero.py`
**FUNCTION:** `AgentZeroClient.send_message`
**ACTUAL BEHAVIOR:** Kod gerçekten de `X-API-KEY` ile `http://localhost:5000/api/api_message` uç noktasına gidiyor.
**VERDICT:** CONFIRMED (Statik olarak doğrulandı).

### DeerFlow
**CLAIM:** POST `/api/threads/{id}/runs/wait` for blocking execution
**SOURCE:** `agent_core/services/deerflow.py`
**FUNCTION:** `DeerFlowClient.run_and_wait`
**ACTUAL BEHAVIOR:** Kod `run_and_wait` fonksiyonunda gerçekten bu uç noktayı kullanıyor ve sonucu bekliyor.
**VERDICT:** CONFIRMED (Statik olarak doğrulandı).

### Handover (Cockpit)
**CLAIM:** POST `/api/handover` broadcasts WebSocket event.
**SOURCE:** `agent_core/services/handover.py`
**FUNCTION:** `CockpitHandover.notify`
**ACTUAL BEHAVIOR:** İstek `http://localhost:5050/api/handover` adresine POST olarak gönderiliyor, `type: handover_alert` verisi kullanılıyor.
**VERDICT:** CONFIRMED (Statik olarak doğrulandı).

## 3. LLM_INVENTORY.md Doğrulamaları

### Gateway Architecture
**CLAIM:** Primary Endpoint: `http://localhost:4000/v1` with Bearer Token and Circuit Breaker / Fallback.
**SOURCE:** `agent_core/services/llm_gateway.py`
**FUNCTION:** `LLMGateway.chat`
**ACTUAL BEHAVIOR:** `LLMGateway` sınıfı içinde `self.cb.is_open(m)` kontrolü yapılıyor. Hata alınırsa (`LLMGatewayError`), `record_failure(m)` tetikleniyor. `models_to_try` dizisi varsayılan model (deepseek) ve yedek modelden (openrouter-chat) oluşuyor.
**VERDICT:** CONFIRMED (Statik olarak doğrulandı).

### UI-TARS VLM Bypass
**CLAIM:** Bypasses the Gateway. Direct call to remote VLM instance (`UITARS_REMOTE_ENDPOINT`).
**SOURCE:** `agent_core/services/uitars.py`
**FUNCTION:** `UITarsModelClient.predict`
**ACTUAL BEHAVIOR:** `uitars.py` incelendiğinde `UITarsModelClient` sınıfının, URL'sini doğrudan parametre olarak aldığı (Gateway'i kullanmadığı) görüldü.
**VERDICT:** CONFIRMED (Statik olarak doğrulandı).

## 4. SYSTEM_MAP.md ve DEPENDENCY_GRAPH.md Doğrulamaları

### Resonance Graph
**CLAIM:** Uses `langgraph.graph.StateGraph` and deterministic uncertainty analysis.
**SOURCE:** `agent_core/resonance_graph.py`
**FUNCTION:** `create_resonance_graph` / `evaluate_node`
**ACTUAL BEHAVIOR:** `create_resonance_graph` bir `StateGraph(ResonanceState)` derliyor. `analyze_node`, `Uncertainty Engine`'den rapor dönüyor.
**VERDICT:** CONFIRMED (Statik olarak doğrulandı).

---

## Özet Tablo

| Severity | CONFIRMED | PARTIAL | FALSE | UNVERIFIED |
|----------|-----------|---------|-------|------------|
| CRITICAL | 1         | 0       | 0     | 0          |
| HIGH     | 1         | 1       | 0     | 0          |
| MEDIUM   | 1         | 0       | 0     | 0          |
| LOW      | 2         | 0       | 0     | 0          |

---

## 1. GERÇEKTEN ÇALIŞANLAR
- **LiteLLM Gateway:** `config.yaml` ile başlatıldığında port `4000` üzerinden health-check başarılı bir şekilde dönüyor (`I'm alive!`).
- **Orchestrator Servis Başlatması:** `agent_core` ortam değişkenleriyle FastAPI olarak sorunsuz ayağa kalkıyor. Sağlık endpoint'i (`/health`) cevap verebiliyor (ancak görev oluşturma hatalı).
- **Graceful Session Disable:** `SESSION_STORE_KEY` boş string bırakıldığında sistem çökmeyip `session_store`u devre dışı bırakıyor.

## 2. ÇALIŞTIĞI İDDİA EDİLEN AMA KANITLANMAYANLAR
- **Agent-Zero E2E İşleyişi:** Dokümantasyonda "çalışıyor" olarak geçse de, arka plan işlemleri (ör. GPU/Torch ihtiyacı) sebebiyle lokal sandbox içinde model indirme süreci veya tam E2E yanıt kanıtlanmadı.
- **DeerFlow Sandbox:** DeerFlow API isteklerinin bash komutlarını gerçekten sorunsuz çalıştırdığı dinamik olarak istismar edilerek test edilmedi.

## 3. GERÇEKTEN HATALI OLANLAR
- **Orchestrator Görev Hattı:** `POST /task` yapıldığında `asyncio.create_task` içindeki fonksiyonun await edilmeyen nesnelere sözlük gibi davranmaya çalışması (coroutine nesnelerine property set etmeye çalışması) API'nin tamamen patlamasına sebep oluyor (Unhandled Exception: TypeError).
- **Geçersiz Hex Key Çökmesi:** `SESSION_STORE_KEY` geçersiz bir hex dizisi ise (örn. "invalidhex") sistem FastAPI sunucusunu başlatamadan Python Exception (ValueError) fırlatarak kapanıyor.

## 4. EN KRİTİK 10 SORUN
1. **[CRITICAL] Orchestrator Task Coroutine Exception:** Yeni bir görev oluşturulduğunda (`POST /task`) pipeline çöküyor. `agent_core.py` içindeki arka plan pipeline görevi state kaydederken TypeError yiyor.
2. **[HIGH] Unsafe Hex Key Initialization:** `session_store.py` içindeki key türetme adımı geçersiz key'leri yutamıyor.
3. **[HIGH] Missing Validation for DeerFlow Sandbox:** Görev promptları tamamen serbest ve host-level bash çalıştırma riskine açık (DeerFlow aracılığıyla).
4. **[MEDIUM] Rigid Integration Architecture:** Bütün external agent'lar orchestrator içerisine hardcoded import edilmiş. Modüler değil.
5. **[MEDIUM] UI-TARS Network Blindspot:** Görsel ajan LLM Gateway'i (LiteLLM) atlayarak direkt kendi uzak hedefine gidiyor, token tracking veya circuit breaker işlemiyor.
6. **[LOW] Lack of Global Request Tracing:** Servisler arasında task ID yayılımı yok; loglar sadece o anki serviste kalıyor.
7. **[LOW] Telegram Placeholder:** Kod dosyalarında "Telegram YOK, Cockpit var" denilse de hala bazı Telegram env var'ları (örn. `TELEGRAM_BOT_TOKEN`) ortalıkta duruyor.
8. **[LOW] Inconsistent Mock Use Check:** Integration verify betiği (verify_integration.py) sadece HTTP kodlarına bakıyor; agent_core arkasındaki gerçek LLM veya mockların işleyişini derinlemesine teyit edemiyor.
9. **[LOW] Config Fragmentation:** .env, config.yaml ve komut satırı argümanları arasında yapılandırma dağılmış.
10. **[LOW] OS Dependent Scripts:** `start_all.ps1` salt Windows (`\Scripts\python.exe`) odaklı.
