## Bağımlılık Grafiği (Dependency Graph)

```mermaid
graph TD
    config([config])
    deerflow([deerflow])
    memory_delta([memory_delta])
    llm_gateway([llm_gateway])
    agent_zero([agent_zero])
    eliza([eliza])
    mission_brief([mission_brief])
    uncertainty([uncertainty])
    session_store([session_store])
    interaction([interaction])
    resonance_graph([resonance_graph])
    uitars([uitars])
    agent_core([agent_core])
    analyzer([analyzer])
    handover([handover])
    scraper([scraper])
    orchestrator([orchestrator])
    orchestrator --> memory_delta
    resonance_graph --> interaction
    agent_core --> memory_delta
    analyzer --> llm_gateway
    memory_delta --> uncertainty
    orchestrator --> eliza
    orchestrator --> llm_gateway
    orchestrator --> resonance_graph
    agent_core --> orchestrator
    mission_brief --> llm_gateway
    agent_core --> llm_gateway
    orchestrator --> agent_zero
    orchestrator --> handover
    orchestrator --> config
    resonance_graph --> handover
    agent_core --> config
    orchestrator --> deerflow
    resonance_graph --> uncertainty
    orchestrator --> scraper
    orchestrator --> session_store
    orchestrator --> uitars
    orchestrator --> analyzer
```

### Mimari Risk Analizi (Architectural Risk Assessment)

1. **God Object Anti-Pattern:**
   Grafikte görüldüğü üzere `orchestrator` neredeyse tüm diğer servislere (analyzer, scraper, eliza, agent_zero, deerflow, uitars, session_store, handover, llm_gateway, config) doğrudan bağımlıdır (tight-coupling).
   - *Risk:* Orkestratör çok fazla sorumluluk üstlendiği için herhangi bir modülün değiştirilmesi (veya bir adımın eklenip çıkarılması) orkestratördeki akışı doğrudan etkileyecektir. "Single Responsibility Principle" (Tek Sorumluluk Prensibi) ihlal ediliyor.
   - *Çözüm:* "Event Bus (Otonom İletişim Ağı)" mimarisine (Faz 2) geçilmesi planlanmalıdır. Servisler birbirini direkt çağırmak yerine, olay (event) yayınlamalı ve dinlemelidir (Pub/Sub pattern).

2. **Döngüsel (Cyclic) Bağımlılık Riski:**
   Mevcut durumda net bir döngü görünmüyor, ancak `memory_delta`'nın `uncertainty`'e, `resonance_graph`'ın ise `uncertainty` ve `handover`'a doğrudan bağımlı olması, domain-driven (DDD) bir yapıdan ziyade katmanlar arası atlamaların (layer skipping) olduğunu gösteriyor. `orchestrator`'un da bu modülleri çağırması, veri akışını karmaşıklaştırıyor.

3. **LLM Gateway Kullanımı:**
   `llm_gateway`, `analyzer`, `agent_core` ve `mission_brief` tarafından doğrudan çağrılıyor. Merkezi bir noktada (gateway pattern) kullanılması sağlıklı ancak `agent_core` (API) katmanının `llm_gateway`'e doğrudan dokunması (`/health` için dahi olsa) API ve servis katmanları arasında sızıntıya (leakage) işaret eder.

**Sonuç:**
Sistem mevcut haliyle çalışıyor olsa da ölçeklenebilirlik ve bakım açısından darboğaza gireceği yer `Orchestrator` sınıfıdır. Bir sonraki mimari hamle, **Event Bus** yapısını entegre ederek bu sıkı bağımlılığı (tight coupling) kırmak olmalıdır.
