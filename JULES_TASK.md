# Jules Sonraki Gorev: Dinamik Planner + COLLECT_MORE Auto-Retry

## Durum

10 dosya, 573 satir yeni kod pushlandi. Pipeline bu:
Scrape -> Analyzer -> Memory -> Resonance -> Eliza -> DeerFlow -> AgentZero -> Session

## Sorun

Pipeline HER gorevde butun servisleri calistiriyor. "analiz et" dense de Eliza, DeerFlow,
AgentZero bosuna calisiyor. COLLECT_MORE sinyali hic islenmiyor.

## GOREV 1: Planner routing

`orchestrator.py` icine `_plan()` metodu ekle. Deterministic, LLM cagirma:

```python
def _plan(self, intent: str) -> dict:
    intent_lower = (intent or "").lower()
    need_persona = any(kw in intent_lower for kw in ["konus", "etkiles", "cevapla", "sohbet", "mesaj", "yorum"])
    need_research = any(kw in intent_lower for kw in ["arastir", "analiz et", "incele", "rapor", "karsilastir"])
    need_orch = any(kw in intent_lower for kw in ["olustur", "yap", "calistir", "gonder", "gorev", "otomatik"])
    return {"need_persona": need_persona, "need_research": need_research, "need_orchestration": need_orch}
```

`run_pipeline` icinde Eliza, DeerFlow, AgentZero adimlarini `if plan["need_X"]` ile sarmala.
Scrape, Analyzer, Memory, Resonance, Session her zaman calsin.

## GOREV 2: COLLECT_MORE auto-retry

Resonance sonrasi uncertainty check:

```python
uncertainty = graph_result.get("uncertainty", {})
if uncertainty and uncertainty.get("collect_more_count", 0) > 0:
    scraped_data = await scrape_target(target, platform, force_refresh=True)
    analyzed_profile = await self.analyzer.analyze(scraped_data)
    # ...ikinci analiz sonucunu report["analyzed_profile_retry"] olarak ekle
```

Maksimum 1 ek deneme. Ikincide de COLLECT_MORE gelirse
`report["retry_status"] = "still_insufficient"` yaz, devam et.

## Kisitlar

- SADECE `orchestrator.py` degistir
- Sifir yeni dosya
- LLM cagirma (planner deterministic)
- `run_pipeline` imzasi ayni kalsin

## Teslim

1. `orchestrator.py` — `_plan()` + routing + COLLECT_MORE retry
2. `python -c "import ast; ast.parse(open('agent_core/orchestrator.py').read())"`
3. PR ac: `feat: dynamic planner + COLLECT_MORE auto-retry`
