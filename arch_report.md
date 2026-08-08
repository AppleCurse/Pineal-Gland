# BÖLÜM 1 — MEVCUT DURUM RAPORU

Sistemin "Organ / Capability" mantığına geçişini sağlamak üzere dört ana açık kaynak projenin (Agent-Zero, DeerFlow, ElizaOS, UI-TARS) mimari analizi yapılmıştır.

## 1. Agent-Zero (Düşünce ve İşletim Sistemi Köprüsü)

**Durum:**
İzole bir Docker (Alpine) ortamında çalışan, host makine ile köprü (A0 CLI) kurabilen, canlı dosya ve terminal erişimine sahip "bilgisayar kullanan ajan" platformudur.

**Güçlü Taraflar:**
*   **Docker Isolation & Host Bridge:** Güvenlik ile yeteneği aynı anda sunar (host'ta sadece izin verilen dizinlerde çalışma).
*   **Agnostik Yaklaşım:** Model ve promptlar kolayca değişir. Çoklu ajan (multi-agent) alt görev dağıtımı yeteneği vardır.
*   **Time Travel / State Snapshot:** Workspace üzerinde dosya geçmişini takip etme (geri alma, fark görme).

**Kritik Açıklar:**
*   **Sosyal Analiz & Persona Eksikliği:** İnsan-gibi davranma, uzun vadeli (RAG) hafıza kurma ve iletişim (DM, tweet) konusunda hiçbir uzmanlığı yoktur; sadece bir "çalışan"dır.
*   **Karar Alma Yükü:** Bütün yük tek bir ajanın "düşünce" balonunda kalırsa context penceresi aşırı şişer.

**Olgunluk Seviyesi:** 8/10 (Sistem otomasyonu için).

## 2. DeerFlow (Derin Araştırma - Research)

**Durum:**
ByteDance tarafından geliştirilen, LangGraph + LangChain üzerine kurulu, açık kaynaklı uzun-dönem (long-horizon) "SuperAgent" harness (koşum) sistemidir. Alt ajanlar (sub-agents), beceriler (skills) ve hafıza sistemini barındırır.

**Güçlü Taraflar:**
*   **Uzun Erimli İşlemler (Long-Horizon Tasks):** Saatlerce sürecek araştırmaları, web aramalarını, Python sandbox execution'larını bölüp yürütebilme yeteneği.
*   **Context Compaction:** Aşırı şişen araştırma verilerini özetleme / sıkıştırma mekanizmaları.

**Kritik Açıklar:**
*   **Ağır ve Hantal:** Basit bir sosyal medya DM'si veya hızlı rezonans ölçümü için aşırı karmaşık bir altyapı başlatır.
*   **Entegrasyon Zorluğu:** Agent OS içinde sürekli arka planda çalışması yerine, sadece "Büyük Veri Araştırması (Deep Research)" gerektiğinde API ile tetiklenmelidir.

**Olgunluk Seviyesi:** 9/10 (Research & Data anlamında).

## 3. ElizaOS (Hafıza, Persona ve İletişim)

**Durum:**
Ajanlara "kişilik (persona)" ve "Platform bağlantısı (Twitter, Discord vb.)" sağlayan, RAG (Vector-based) tabanlı açık kaynaklı çoklu-ajan framework'üdür.

**Güçlü Taraflar:**
*   **Character Files & Context:** `.json` formatındaki karakter dosyalarıyla ajanın tonunu (tone), geçmişini ve tepki verme biçimini mükemmel yönetir.
*   **RAG Memory:** Ajana uzun dönemli anımsama yeteneği kazandırır.
*   **Plugins / Providers:** Context'e veri akıtan ve ajan yeteneklerini modüler kılan mükemmel eklenti mimarisi.

**Kritik Açıklar:**
*   **Dar Kapsam:** Sadece "sosyal medya ajanı" veya "sohbet botu" olarak kalma eğilimindedir. İşletim sistemine (dosyalara, tarayıcıya) hakim değildir.

**Olgunluk Seviyesi:** 8.5/10 (Sosyal ve RAG katmanında).

## 4. UI-TARS (Görsel Algı ve Fiziksel Eylem)

**Durum:**
Ekran görüntülerini (raw screenshots) alıp doğrudan mouse tıklaması, klavye girişi üreten ByteDance / Tsinghua çıkışlı saf *vision-based* (görsel tabanlı) GUI otomasyon sistemidir.

**Güçlü Taraflar:**
*   **Saf Görsel Algı (DOM'a İhtiyaç Yok):** Instagram, X veya herhangi bir platform DOM'unu (HTML) değiştirse bile UI-TARS bozulmaz, çünkü insan gibi ekrana bakarak anlar.
*   **Lokal / Gizlilik:** Buluta (Claude Computer Use gibi) görüntü göndermeden yerel çalışabilir.

**Kritik Açıklar:**
*   **Yüksek Donanım İhtiyacı / Gecikme:** Görsel dil modelleri (VLM) 2B, 7B veya 72B parametreli olduğundan her tıklama için model çalıştırmak süre ve donanım gücü (GPU) gerektirir.
*   **Muhakeme Eksikliği:** Ne yapması gerektiğini bilir ama "Neden yapıyorum?" veya "Kullanıcı profilinden ne anladım?" gibi konularda muhakemesi zayıftır; yönlendirilmeye (Planner'a) ihtiyaç duyar.

**Olgunluk Seviyesi:** 8/10 (Aksiyon motoru olarak).


---
# BÖLÜM 2 — EVRİLME PLANI (Agent OS Mimarisi)

Bu 4 aracın birbiriyle yarışması veya peş peşe statik (hardcoded) çalışması mimari bir hatadır. Sistem, "Capability Registry" (Yetenek Kaydı) prensibiyle evrilmelidir.

### Faz 0 — Capability Registry (Yetenek Sözleşmeleri)

**Amaç:** Ajanların sistemde bir "servis" olarak değil, bir "Organ / Yetenek" olarak tanımlanması.

**Yapılacaklar:**
1.  **Sözleşme (Interface) Tanımları:** Her araç, Agent OS'e yeteneklerini (capabilities) beyan eden bir katman (adapter) arkasına alınır.
    *   *Agent-Zero -> `ICodeExec`, `IOSBridge`*
    *   *DeerFlow -> `IDeepResearch`, `IWebCrawl`*
    *   *ElizaOS -> `IPersona`, `ILongTermMemory`*
    *   *UI-TARS -> `IVision`, `IGuiAction`*
2.  **Kaldırılacaklar:** Orchestrator'daki `self.az`, `self.df`, `self.eliza` gibi statik referanslar kaldırılıp dinamik bir `CapabilityRegistry` nesnesine geçirilecek.

**Çıktı:** Sistem, "Bana DeerFlow'u ver" demek yerine "Bana 'DeepResearch' yapabilen bir modül ver" diyecektir.

### Faz 1 — Dinamik Planner (Planlayıcı Zeka)

**Amaç:** İşe (Task) göre uygun organı (Capability) dinamik seçmek.

**Yapılacaklar:**
1.  **Task Triage (Görev Yönlendirme):** Kullanıcıdan/Sistemden gelen emir önce Planner'a (LLM) gider.
2.  **Örnek Akış (Routing):**
    *   *Görev:* "Rakip analizi yap." -> Planner sadece `IDeepResearch` (DeerFlow) çağırır.
    *   *Görev:* "DM kutusunda gezin ve şu mesaja uygun bir üslupla cevap yaz." -> Planner `IVision` (UI-TARS) ve `IPersona` (ElizaOS) çağırır.
    *   *Görev:* "Bir python betiği yaz ve çalıştır." -> Planner `ICodeExec` (Agent-Zero) çağırır.

**Çıktı:** İhtiyaç olmayan modüller uyur, sistem hızlanır ve maliyet (token) düşer.

### Faz 2 — Event Bus (Otonom İletişim Ağı)

**Amaç:** Organların birbirleriyle asenkron ve otonom haberleşmesi.

**Yapılacaklar:**
1.  Senkron/Await pipeline kaldırılacak. Yerine olay (Event) mantığı gelecek.
2.  *Örnek Döngü:*
    *   `ProfileAnalyzer` bitince `Event(PROFILE_ANALYZED)` fırlatır.
    *   `MemoryManager` bu eventi dinler, deltayı yazar ve `Event(MEMORY_UPDATED)` fırlatır.
    *   `ResonanceEngine` memory güncellendiğini görünce otonom uyanır, skoru hesaplar, stratejiyi seçer ve `Event(ACTION_REQUIRED)` fırlatır.
    *   `Planner` eylemi alır ve `UI-TARS`ı tetikler.

**Çıktı:** Sistemin herhangi bir yerinden (Telegram, CLI, başka bir ajan) fırlatılan bir event, doğru organları otomatik harekete geçirir. Statik darboğazlar kalkar.

### Faz 3 — Otonom Geri Besleme (Self-Reflection & Feedback Loop)

**Amaç:** Hata durumunda veya belirsizlik (Uncertainty) durumunda ajanın kendine görev çıkarabilmesi.

**Yapılacaklar:**
1.  `UncertaintyEngine`'den `COLLECT_MORE` çıkarsa, sistem doğrudan Planner'a `Event(NEED_MORE_DATA)` gönderir.
2.  Planner, `IWebCrawl` (DeerFlow) veya `IVision` (UI-TARS) kullanarak otonom şekilde eksik kanıtı toplar ve Analyzer'ı yeniden tetikler.

**Çıktı:** Ajan dışarıdan emir beklemeden kendi belirsizliğini kendi kendine gideren, gerçek "Agentic" bir yapıya kavuşur.
