# Pineal-Gland — Mimari Bağımlılık Grafı Analizi

```
Oluşturulma: 2026-08-07
Commit: c6fcc15
```

---

## 1. Mimari Genel Görünüm

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                           agent_core.py (FastAPI)                          │
│                                                                             │
│  /health ───────────────┐                                                  │
│  /task ─────────────────┼──► Orchestrator.run_pipeline()                    │
│  /sessions ──────────────┤     1. _plan() [routing]                        │
│  /memory/{p}/{u} ────────┘     2. scrape_target()                          │
│                               3. analyzer.analyze()                         │
│                               4. resonance_graph.ainvoke()                 │
│                               5. eliza.recall() [conditional]               │
│                               6. df.run_research() [conditional]            │
│                               7. az.send_message() [conditional]            │
│                               8. GUIAgent.run() [if visual_task]            │
│                               9. sessions.load()                            │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 2. Tam Bağımlılık Grafı

```
                    ┌──────────────────────────────────────┐
                    │         EXTERNAL SERVICES             │
                    │                                      │
                    │  Agent-Zero :5000   [agent_orchestrator]│
                    │  DeerFlow   :8001   [research_client]  │
                    │  ElizaOS    :3000   [persona_client]   │
                    │  LLM-Gateway:4000   [llm_gateway]      │
                    └──────────┬──────────────────┬────────┘
                               │                  │
                    ServiceContainer           build_default_services()
                    ┌──────────────────────────────┐
                    │  agent_orchestrator           │
                    │  research_client             │
                    │  persona_client              │
                    │  profile_analyzer  ───────────┼──► LLMGateway
                    │  session_store               │
                    │  llm_gateway                 │
                    └──────────────────────────────┘
                                    │
                          Orchestrator.__init__()
                                    │
         ┌───────────────────────────┼───────────────────────────┐
         │                           │                           │
  ┌──────┴──────┐         ┌─────────┴──────────┐      ┌───────┴───────┐
  │  HARDKODLU  │         │   SERVICE CLIENTS   │      │  PIPELINE     │
  │ limiter     │         │  az                 │      │ run_pipeline() │
  │ handover    │         │  df                 │      │ _plan()        │
  │ resonance   │         │  eliza              │      │ register_task()│
  │ _tasks      │         │  analyzer           │      │ health_async() │
  └─────────────┘         │  sessions           │      └───────────────┘
                          └─────────────────────┘

```

### 2.1 Orchestrator → Servis Çağrı Matrisi

| Servis | Alan | Yöntem | Kullanım |
|--------|------|--------|----------|
| `analyzer` | `svc.profile_analyzer` | `.analyze()` | Her scrape sonrası |
| `az` | `svc.agent_orchestrator` | `.send_message()`, `.health()` | `plan["need_orchestration"]` |
| `df` | `svc.research_client` | `.run_research()`, `.health()` | `plan["need_research"]` |
| `eliza` | `svc.persona_client` | `.recall()`, `.health()` | `plan["need_persona"]` |
| `sessions` | `svc.session_store` | `.load()`, `.save()` | Platform/hesap verilince |
| `scraper` | module-level | `scrape_target()` | Her target verilince |
| `resonance_graph` | hardcoded | `.ainvoke()` | Profil analiz sonrası |
| `limiter` | hardcoded | `.check_and_wait()` | Her target verilince |
| `handover` | hardcoded | — | Cockpit'e bildirim |

---

## 3. Veri Modeli Bağımlılıkları

```
ScrapedData
    │
    ▼
ProfileAnalyzer.analyze()
    │  ┌───────────────────────────────────────┐
    ├──► BehavioralProfile (Pydantic)           │
    │     ├── CommunicationSignals             │
    │     │     └── Evidence[excerpt,src,ts]  │  ◄── Structured Evidence
    │     ├── TopicAffinity                    │
    │     ├── PostingPattern                   │
    │     ├── InteractionPattern               │
    │     ├── compatibility_vector             │
    │     └── behavioral_signals, stability    │
    │  └───────────────────────────────────────┘
    │
    ▼
record_profile()  ──► MemoryDelta ──► profile_history.json
    │                              (snapshots)
    ▼
ResonanceGraph.ainvoke()
    │  ┌──────────────────────────────────────┐
    ├──► CompatibilityVector                 │
    │     ├── platform_fit: float             │
    │     ├── audience_overlap: float         │
    │     ├── topic_resonance: float         │
    │     └── composite: float               │
    │  └──────────────────────────────────────┘
    │
    ▼
UncertaintyReport
    │  ├── verdict: FLAG | COLLECT_MORE | OK
    │  └── collect_more_count: int
    │
    ▼ (if COLLECT_MORE)
scrape_target(force_refresh=True) ──► retry analyze

```

---

## 4. LLM Gateway — İç Mimari

```
LLMGateway
    │
    ├── CircuitBreaker
    │     ├── is_open(model) → bool
    │     ├── record_failure(model)
    │     ├── record_success(model)
    │     └── status(model) → {closed, half_open, open, failure_count}
    │
    ├── TokenBudget
    │     ├── add(model, prompt_tokens, completion_tokens)
    │     └── get_stats() → {total_tokens, cost_estimate}
    │
    ├── chat(message) → str
    │     ├── CB.is_open? → fallback_model'e geç
    │     └── TokenBudget.add()
    │
    └── chat_and_parse(system, user, response_format) → parsed

```

---

## 5. API Endpoints

```
GET  /health                              → services + llm_gateway (CB + usage)
POST /task   {intent, target, platform}   → Orchestrator.run_pipeline()
GET  /task/{task_id}                     → get_task()
GET  /tasks                               → list_tasks()
GET  /sessions                            → session list
GET  /memory/{platform}/{username}        → get_history()
GET  /memory/{platform}/{username}/latest → get_latest()
GET  /agents                              → eliza.get_agents()
```

---

## 6. CRİTİK MİMARİ SORUNLAR

### 🔴 SORUN 1: MemoryManager Kullanılmıyor

**Şu an:**
```
services/memory_manager.py  ✓ YAZILDI (Jules)
orchestrator.py             ✗ MemoryManager IMPORT EDİLMEMİŞ
ServiceContainer            ✗ memory_manager ALANI YOK
```

Jules `process_profile()` yazdı ama orchestrator o sınıfı `import` etmiyor, `ServiceContainer`'a koymadı, `run_pipeline`'da çağırmadı. Kod ölü.

**Etki:** Memory write policy çalışmıyor. Sadece `memory_delta` (`record_profile()`) aktif.

**Risk:** İki hafıza sistemi (`memory_delta` + `memory_manager`) birlikte kullanılacaksa bağlantı yok.

**Çözüm:** Ya `memory_manager` orchestratore entegre edilir, ya da silinir. Yarım bırakılmış.

---

### 🔴 SORUN 2: ServiceContainer Tanımsız Referans

**Şu an:**
```
ServiceContainer tanımlı:
  agent_orchestrator, research_client, persona_client,
  profile_analyzer, session_store, llm_gateway

Orchestrator.__init__ bekliyor:
  profile_analyzer → self.analyzer
  research_client  → self.df
  persona_client  → self.eliza
  agent_orchestrator → self.az
  session_store   → self.sessions

EK: self.limiter, self.handover, self.resonance_graph, self._tasks, self._lock
    → ServiceContainer'DA YOK, hardcoded
```

**Risk:** `ServiceContainer` yarım kontrat. Eklenen her servis iki yerde güncellenmeli (container + orchestrator __init__). Bug'a açık.

**Çözüm:** `limiter`, `handover`, `resonance_graph` da `ServiceContainer`'a alınmalı. Ya da kontrat belgelenmeli.

---

### 🟡 SORUN 3: two memory write path

```
run_pipeline():
  if self.memory:                    ← MemoryManager (OLASI ÖLÜ KOD)
      mem_res = self.memory.process_profile(...)
      report["memory_delta"] = mem_res

  delta = record_profile(...)         ← memory_delta (AKTİF)
      report["memory_delta"] = {...}
```

**Şu an:** `self.memory` hiçbir yerde `None` değil çünkü `MemoryManager` import bile edilmiş değil. İlk `if` asla çalışmaz. Sadece `record_profile()` aktif.

**Risk:** Yarın `MemoryManager` entegre edilirse iki `report["memory_delta"]` üst üste yazılır.

**Çözüm:** Tek hafıza yolu. Ya `memory_manager` entegre edilir, ya da `memory_delta` ile birleştirilir.

---

### 🟡 SORUN 4: analyzer.gateway — Dolaylı Bağımlılık

```
agent_core.py /health
  → orch.analyzer.gateway.cb.status()  ✓ aktif

LLMGateway.get_usage_stats()
  → analyzer üzerinden erişiliyor       ✓ aktif

Ama:
  services/llm_gateway.py
    get_llm_gateway() → module-level singleton  ⚠

  services/analyzer.py
    def __init__(self, gateway=None)
    → gateway or get_llm_gateway()  ✓ DI var ama fallback var
```

**Risk:** İki farklı `LLMGateway` instance olabilir — biri `build_default_services()`'den, biri `get_llm_gateway()` singleton'undan. CircuitBreaker state'i iki instance'da ayrı tutulur.

**Çözüm:** `LLMGateway` singleton pattern veya App-level inject.

---

### 🟡 SORUN 5: resonance_graph State-free Değil

```
create_resonance_graph()   ← her Orchestrator yaratılışında yeni instance
  → LangGraph StateGraph
  → uncertainty.evaluate_profile()
  → InteractionAgent (state içinde tutuluyor mu?)
```

**Risk:** Graph state tutuyorsa, stateless değildir. Thread-safety sorunu olabilir. `_lock` sadece task kaydında, graph invoke'unda lock yok.

**Çözüm:** Graph'un stateful olup olmadığı belgelenmeli. Thread-safe değilse lock eklenmeli.

---

### 🟢 SORUN 6: analyzer Gateway DI Zorunlu Değil

```
class ProfileAnalyzer:
    def __init__(self, gateway: Optional[LLMGateway] = None):
        self.gateway = gateway or get_llm_gateway()  ← fallback var
```

**Etki:** Test edilebilirlik düşük. Mock zorunlu değil.

**Risk:** Düşük. Fallback pratikte sorun değil ama kötü pattern.

---

## 7. KOD KALİTESİ METRİKLERİ

| Metric | Değer | Not |
|--------|-------|-----|
| Toplam dosya | 12 | agent_core/ |
| Toplam satır (yaklaşık) | ~3000 | |
| Servis katmanı dosya sayısı | 11 | |
| Protocol kontrat sayısı | 0 | ❌ Hiç yok |
| Hardcoded bağımlılık | 3 | limiter, handover, resonance_graph |
| Ölü kod (MemoryManager) | 1 dosya | 🔴 |
| İmplisit singleton | 1 | get_llm_gateway() |
| API endpoint | 8 | |
| Pipeline adımı | 9 | (routing dahil) |
| Yapılandırılmış veri modeli | 7 | Pydantic (BehavioralProfile + altmodeller) |
| exception handling kapsamı | Orta | Her adımda try/except var |
| Loglama | Var | logger her adımda |

---

## 8. ÖNCELİK SIRALAMASI

| # | Sorun | Öncelik | Emek |
|---|-------|---------|------|
| 1 | MemoryManager entegre et veya sil | 🔴 Kritik | 30 dk |
| 2 | ServiceContainer kontratı belgele | 🔴 Kritik | 15 dk |
| 3 | LangGraph thread-safety kontrol et | 🟡 Yüksek | 20 dk |
| 4 | LLMGateway singleton tek instance | 🟡 Yüksek | 15 dk |
| 5 | Protocol kontratları yaz | 🟡 Orta | 1 saat |

---

## 9. ÖNERİLEN HEDEF DURUM

```
ServiceContainer (TAM KONTRAKT)
├── agent_orchestrator: AgentOrchestratorProtocol
├── research_client:    ResearchClientProtocol
├── persona_client:     PersonaClientProtocol
├── profile_analyzer:   ProfileAnalyzerProtocol
├── session_store:      SessionStoreProtocol
├── llm_gateway:        LLMGatewayProtocol
├── memory:             MemoryManager  ← EKLENDI (ya da kaldirildi)
├── limiter:            FrequencyLimiter  ← EKLENDI
├── handover:           CockpitHandover    ← EKLENDI
└── resonance_graph:    ResonanceGraph     ← EKLENDI
```

---

## 10. Dependency Matrix

```
                   orch az  df  eliza  ana  ses  scr  rg  lim  ho  cb  tb  mem  un
orchestrator       -   D   D   D     D    D   C    C   -   -   -   -   -   -
agent_zero.py      C   -   -   -     -    -   -    -   -   -   -   -   -   -
deerflow.py        C   -   -   -     -    -   -    -   -   -   -   -   -   -
eliza.py           C   -   -   -     -    -   -    -   -   -   -   -   -   -
analyzer.py        -   -   -   -     -    -   -    -   -   -   -   -   D   -
scraper.py         C   -   -   -     -    -   -    -   -   -   -   -   -   -
resonance_graph.py C   -   -   -     -    -   -    -   -   -   -   -   -   D
llm_gateway.py     -   -   -   -     -    -   -    -   -   -   -   D   D   -
session_store.py   C   -   -   -     -    -   -    -   -   -   -   -   -   -
memory_delta.py    -   -   -   -     -    -   -    -   -   -   -   -   -   D
memory_manager.py  -   -   -   -     -    -   -    -   -   -   -   -   -   -
uncertainty.py     -   -   -   -     -    -   -    -   -   -   -   -   -   -
agent_core.py      D   -   -   -     -    -   -    -   -   -   -   -   -   -

D = Dependency (A uses B)
C = Composition (A creates/manages B)
```

**Kısaltmalar:** orch=Orchestrator, az=AgentZero, df=DeerFlow, eliza=ElizaOS, ana=Analyzer, ses=SessionStore, scr=Scraper, rg=ResonanceGraph, lim=Limiter, ho=Handover, cb=CircuitBreaker, tb=TokenBudget, mem=MemoryDelta/MemoryManager, un=UncertaintyEngine
