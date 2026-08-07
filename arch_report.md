# Pineal Gland — Evrimsel Mimari Denetim Raporu

Bu rapor, sistemi tek seferlik bir değerlendirme olarak değil, her kontrolü bir sonraki evrim aşamasına girdi yapan kapalı döngü mimari denetimi olarak ele alır.

**Denetim döngüsü:**

```text
MEVCUT DURUM
↓
AÇIKLAR / RİSKLER
↓
ÖNCELİKLİ DÜZELTME
↓
YENİ KONTROL
↓
YENİ DURUM
↓
MÜKEMMELLEŞTİRME DÖNGÜSÜ
```

Her bulgu şu formatta ilerler:

```text
SORUN
↓
NEDEN
↓
ETKİ
↓
ÇÖZÜM
↓
DOĞRULAMA TESTİ
```

---

# BÖLÜM 1 — MEVCUT DURUM RAPORU

## 1. Ürün sınırı ve etik güvenlik katmanı

### A) Mevcut mimari

Depo, kendisini otomatik ilişki veya hesap aksiyon botu değil, `human-in-the-loop` iletişim taslağı ve bağlam asistanı olarak konumlandırıyor. README; hesap kırma, gizli veri toplama, manipülatif profil çıkarımı ve tam otonom mesaj gönderme gibi davranışları açıkça kapsam dışı bırakıyor. Bu sınır ürün seviyesinde doğru yerde; ancak çalışma zamanı politika motoru olarak henüz kod tarafından zorlanmıyor.

### B) Güçlü taraflar

- İnsan onayı sınırı ürün felsefesinin merkezine alınmış.
- Hassas veri ve manipülasyon yasağı açıkça belgelenmiş.
- Sistem öneren ve kullanıcıya karar alanı bırakan bir yardımcı olarak tarif edilmiş.

### C) Kritik açıklar

```text
Sorun: Güvenlik ilkeleri dokümantasyonda güçlü, runtime enforcement katmanında zayıf.
Neden: /task girdisi için niyet politikası, platform aksiyon sınırı ve risk sınıflandırması kodda zorunlu bir geçit olarak görünmüyor.
Etki: İleride UI-TARS veya Agent-Zero daha yetkili hale geldiğinde sistem insan onayı dışına taşabilir.
Çözüm: TaskPolicyGate eklenmeli; her görev allow / needs_human_approval / deny olarak sınıflandırılmalı.
Doğrulama testi: Manipülatif, otomatik gönderim isteyen ve izinli taslak görevlerinden oluşan test setinde beklenen karar matrisi ölçülmeli.
```

### D) Olgunluk seviyesi

**7/10** — Ürün ilkeleri net; yürütme katmanında zorunlu politika denetimi eksik.

---

## 2. agent_core API geçidi ve orkestrasyon

### A) Mevcut mimari

`agent_core` FastAPI tabanlı ana giriş noktasıdır. `/task`, `/task/{id}`, `/tasks`, `/health`, `/agents`, `/sessions` ve `/ws` uçlarını sunar. Orchestrator; Agent-Zero, Deer-Flow, ElizaOS, UI-TARS, SessionStore, MemoryManager ve ProfileAnalyzer servislerini tek pipeline içinde koordine eder.

### B) Güçlü taraflar

- Servis istemcileri `ServiceContainer` üzerinden dependency injection ile bağlanıyor.
- Her pipeline adımı görev kaydına yazılıyor.
- Dış servis erişilemezse işlem tamamen çökmek yerine ilgili adım `unavailable` olarak işaretleniyor.
- Health endpoint'i servis durumlarını ve LLM gateway metriklerini yüzeye çıkarıyor.

### C) Kritik açıklar

```text
Sorun: Orkestrasyon hâlâ sıralı ve statik pipeline mantığında.
Neden: Intent → scraper → analyzer → memory → resonance → eliza → deerflow → agent_zero akışı her görev için benzer şekilde deneniyor.
Etki: Basit görevlerde gereksiz servis çağrısı, uzun görevlerde dar boğaz ve maliyet artışı oluşur.
Çözüm: Capability Registry + Planner katmanı eklenmeli; görev önce yetenek ihtiyacına ayrılmalı.
Doğrulama testi: 20 farklı görev tipi için beklenen capability seçimi, latency ve çağrılan servis sayısı ölçülmeli.
```

```text
Sorun: Task state sadece süreç içi bellekte tutuluyor.
Neden: Orchestrator `_tasks` sözlüğünü runtime içinde saklıyor.
Etki: agent_core yeniden başladığında görev geçmişi, devam eden işler ve audit trail kaybolur.
Çözüm: TaskStore arayüzü ve SQLite/Postgres backed implementasyon eklenmeli.
Doğrulama testi: Görev çalışırken agent_core restart edilip task kaydının geri yüklenmesi doğrulanmalı.
```

### D) Olgunluk seviyesi

**7/10** — Çalışan ve toleranslı bir gateway var; dinamik planlama ve kalıcı task state eksik.

---

## 3. LLM Gateway ve model routing

### A) Mevcut mimari

LLM çağrıları merkezi `LLMGateway` adaptöründen geçiyor. Gateway LiteLLM/OpenAI uyumlu `/chat/completions` çağrısı yapıyor, birincil model ve fallback model sırasını deniyor, model bazlı circuit breaker tutuyor ve token kullanım istatistiği topluyor.

### B) Güçlü taraflar

- Analyzer model detaylarından ayrıştırılmış.
- Fallback model ve circuit breaker temel dayanıklılığı artırıyor.
- Structured output için Pydantic schema doğrulaması var.
- Usage metrikleri health üzerinden okunabilecek hale getirilmiş.

### C) Kritik açıklar

```text
Sorun: Routing politikası görev bağlamına göre dinamik değil.
Neden: Gateway önce `model`, sonra `fallback_model` listesini dener; maliyet, latency, kalite veya görev riskiyle seçim yapmaz.
Etki: Basit sınıflandırma pahalı modele gidebilir; kritik analiz ucuz/yetersiz modele kalabilir.
Çözüm: ModelRouter eklenmeli; task_type, risk_level, expected_tokens, confidence_requirement ve budget politikasına göre model seçmeli.
Doğrulama testi: Sentetik görev setinde seçilen model, hedef kalite/maliyet tablosuyla karşılaştırılmalı.
```

```text
Sorun: Circuit breaker süreç içi ve kalıcı değil.
Neden: Durum class-level dict içinde tutuluyor.
Etki: Restart sonrası aynı arızalı model tekrar denenir; çoklu process altında breaker tutarsızlaşır.
Çözüm: Circuit breaker durumunu paylaşımlı KV/SQLite/Redis benzeri bir store'a taşımak.
Doğrulama testi: Model hata enjeksiyonu + process restart sonrası breaker durumunun korunduğu doğrulanmalı.
```

### D) Olgunluk seviyesi

**7/10** — Merkezi gateway doğru yönde; adaptif model seçimi ve kalıcı resilience eksik.

---

## 4. Profil analizi ve evidence sistemi

### A) Mevcut mimari

`ProfileAnalyzer`, scraper çıktısından bio ve son gönderileri alarak gözlemlenebilir iletişim sinyallerini çıkarır. Pydantic şemaları; communication signals, topic affinity, posting pattern, interaction pattern, confidence, stability, sample size ve evidence alanlarını zorunlu hale getirir. Sistem prompt'u teşhis ve mental durum çıkarımını yasaklar.

### B) Güçlü taraflar

- Psikolojik teşhis yerine gözlemlenebilir sinyal çıkarımı sınırı doğru konumlandırılmış.
- Evidence alanı model çıktısında birinci sınıf veri olarak yer alıyor.
- Confidence ve stability ayrı skorlar olarak isteniyor.
- JSON schema validation, hatalı LLM çıktısını azaltıyor.

### C) Kritik açıklar

```text
Sorun: Evidence içerikleri kaynak veriye bağlanarak doğrulanmıyor.
Neden: LLM'in döndürdüğü excerpt ve source alanları schema tarafından biçimsel doğrulanıyor, ancak excerpt gerçekten input içinde var mı kontrol edilmiyor.
Etki: Halüsinasyon evidence memory'ye ve resonance kararlarına taşınabilir.
Çözüm: EvidenceVerifier eklenmeli; excerpt fuzzy match ile kaynak metinde aranmalı, eşleşmeyen evidence düşürülmeli veya profil reddedilmeli.
Doğrulama testi: Bilerek uydurulmuş evidence içeren 100 analiz çıktısında yakalama oranı ölçülmeli.
```

```text
Sorun: Analyzer hata durumunda schema açısından eksik fallback dict döndürüyor.
Neden: Hata yakalandığında bazı alanlar `None`, bazı zorunlu alanlar eksik veya sıfır olarak dönüyor.
Etki: Downstream kodlar analyzer çıktısını geçerli profil sanabilir; memory ve resonance sessiz kalite düşüşü yaşar.
Çözüm: AnalyzerResult wrapper kullanılmalı: `{status, profile, errors, evidence_health}`.
Doğrulama testi: LLM timeout, malformed JSON ve schema error senaryolarında downstream'in profil işlemediği doğrulanmalı.
```

### D) Olgunluk seviyesi

**7.5/10** — Güvenli sinyal şeması güçlü; evidence doğrulama ve hata kontratı olgunlaştırılmalı.

---

## 5. Hafıza yönetimi

### A) Mevcut mimari

`MemoryManager`, analiz edilen profilleri JSON dosyada saklıyor. Yazma politikası `overall_confidence > 0.60` ve ortalama stability `> 0.40` eşiklerine dayanıyor. Yeni kayıtlar önceki kayıtla karşılaştırılıyor ve delta alanı üretiliyor.

### B) Güçlü taraflar

- Hafızaya doğrudan her çıktı yazılmıyor; confidence/stability eşiği var.
- Profil geçmişi append-only mantığa yakın tutuluyor.
- Delta tracking, evrimsel profil değişimi için doğru ilk adımdır.

### C) Kritik açıklar

```text
Sorun: Memory ingestion validator yok.
Neden: Yazma kararı sadece skor eşiklerine dayanıyor; evidence geçerliliği, PII riski, kaynak kalitesi ve schema version migrasyonu kontrol edilmiyor.
Etki: Yanlış, hassas veya düşük kaynaklı deneyimler kalıcı hafızaya girebilir.
Çözüm: MemoryIngestionValidator eklenmeli; schema, evidence, privacy, recency ve source_quality skorları birlikte karar vermeli.
Doğrulama testi: 1000 örnek profil ile yanlış kayıt oranı, reddetme gerekçeleri ve kabul edilen kayıtların evidence coverage oranı ölçülmeli.
```

```text
Sorun: JSON dosya storage üretim için kırılgan.
Neden: Atomic write, lock granularity, corruption recovery ve çoklu process desteği sınırlı.
Etki: Paralel görevlerde veri kaybı veya bozuk JSON riski oluşur.
Çözüm: MemoryStore arayüzü altında SQLite başlangıç seviyesi, sonra vektör/graph store evrimi uygulanmalı.
Doğrulama testi: 100 paralel profile write ve process kill enjeksiyonunda veri bütünlüğü kontrol edilmeli.
```

### D) Olgunluk seviyesi

**6/10** — Kavramsal politika var; üretim kalıcılığı, doğrulama ve semantik hafıza eksik.

---

## 6. Rezonans motoru ve karar katmanı

### A) Mevcut mimari

Orchestrator, analiz edilmiş profili LangGraph tabanlı resonance graph içine veriyor. State içinde profil, skor, strateji, message count, handover flag, status ve session cookies alanları bulunuyor.

### B) Güçlü taraflar

- Rezonans ayrı bir graph olarak ayrıştırılmış; karar mantığı tek fonksiyona gömülmemiş.
- Session bilgisi ve profil sinyali aynı karar state'inde birleştirilebiliyor.
- Hata durumunda pipeline tamamı kırılmadan ilgili adım failed olarak işaretleniyor.

### C) Kritik açıklar

```text
Sorun: Rezonans kararlarının açıklanabilirliği sınırlı.
Neden: Orchestrator sadece composite score ve strategy özetini logluyor; karar kanıtları, ağırlıklar ve karşı-argümanlar audit alanına dönüşmüyor.
Etki: Neden bu strateji seçildi sorusu cevaplanamaz; kalite döngüsü zayıflar.
Çözüm: ResonanceDecision schema oluşturulmalı: score_breakdown, evidence_refs, rejected_strategies, safety_flags.
Doğrulama testi: Her resonance çıktısının en az bir evidence_ref ve score_breakdown içerdiği kontrat testiyle doğrulanmalı.
```

### D) Olgunluk seviyesi

**6.5/10** — Graph ayrımı iyi; karar kanıt zinciri ve kalite ölçümü eksik.

---

## 7. Dış servis adaptörleri

### A) Mevcut mimari

Sistem Agent-Zero, Deer-Flow, ElizaOS ve UI-TARS'i adaptörler üzerinden çağırıyor. AGENTS runbook'unda doğrulanmış API kontratları belirtilmiş: Agent-Zero `/api/api_message`, Deer-Flow thread/run akışı, ElizaOS agent message endpoint'i, UI-TARS screenshot → VLM → action döngüsü.

### B) Güçlü taraflar

- Servisler birbirinden ayrık tutulmuş.
- Erişilemeyen servisler pipeline'ı tamamen düşürmüyor.
- Native install runbook'u servis başlatma ve port bilgilerini içeriyor.

### C) Kritik açıklar

```text
Sorun: Health contract booleana indirgenmiş.
Neden: `_service_health` sadece true/false döndürüyor; latency, version, auth failure, degraded mode ve last_error ayrıştırılmıyor.
Etki: Operasyonel sorunların kök nedeni geç anlaşılır.
Çözüm: HealthStatus schema kullanılmalı: `{ok, latency_ms, version, auth_ok, degraded, last_error, checked_at}`.
Doğrulama testi: Servis kapalı, auth hatalı, yavaş yanıt ve başarılı yanıt senaryoları ayrı ayrı beklenen status ile test edilmeli.
```

```text
Sorun: API kontratları dokümante ama otomatik contract test paketi sınırlı.
Neden: `verify_integration.py` genel E2E kontrol yapıyor; her adaptör için fixture tabanlı kontrat testi görünmüyor.
Etki: Dış servis endpoint değişiminde hata prod akışında yakalanabilir.
Çözüm: `tests/contracts/` altında her adaptör için respx/httpx mock server değil, yerel test server veya recorded contract fixture ile doğrulama eklenmeli.
Doğrulama testi: Her client için success, auth fail, timeout ve malformed response testleri çalışmalı.
```

### D) Olgunluk seviyesi

**7/10** — Adaptör sınırları iyi; health ve contract testleri daha ayrıntılı olmalı.

---

## 8. Session store ve güvenli veri saklama

### A) Mevcut mimari

SessionStore, platform/hesap bazında çerez ve refresh token kayıtlarını AES-GCM ile şifreli JSON olarak saklıyor. Anahtar hex ortam değişkeninden PBKDF2 ile türetiliyor. Save/load/list/delete/rotate API'leri var.

### B) Güçlü taraflar

- Düz metin oturum saklanmıyor.
- Platform/account izolasyonu var.
- Anahtar yoksa store devre dışı kalıyor.
- AES-GCM seçimi doğru modern simetrik şifreleme yaklaşımıdır.

### C) Kritik açıklar

```text
Sorun: Anahtar rotasyonu ve kayıt versiyonlama yok.
Neden: Şifreli blob formatında version/kid alanı bulunmuyor.
Etki: Anahtar değişiminde eski oturumlar okunamaz; kontrollü migration yapılamaz.
Çözüm: Envelope formatına `{version, kid, nonce, ciphertext, created_at}` eklenmeli.
Doğrulama testi: Eski anahtarla kaydedilmiş oturumun yeni anahtara rotate edilmesi ve eski kayıtların okunabilirliği test edilmeli.
```

```text
Sorun: Oturum kullanım yetkisi task policy ile bağlı değil.
Neden: Session yükleme, platform/account verilince çalışıyor; görev tipi ve onay durumu ile doğrudan ilişkilendirilmiyor.
Etki: Gelecekte aksiyon motoru eklendiğinde yetkisiz dış dünya eylemi riski artar.
Çözüm: Session erişimi için scoped approval token veya task_policy sonucu zorunlu olmalı.
Doğrulama testi: Onaysız görevde session load/use reddedilmeli; onaylı görevde yalnızca ilgili platform/account scope'u açılmalı.
```

### D) Olgunluk seviyesi

**7/10** — Şifreleme temeli iyi; key lifecycle ve task-scope access control eksik.

---

## 9. Gözlemlenebilirlik, test ve operasyon

### A) Mevcut mimari

FastAPI tarafında konsol + rotating file logging var. WebSocket üzerinden canlı log yayınlanıyor. `verify_integration.py`, agent_core, Cockpit, görev oluşturma ve handover endpoint'i için temel entegrasyon kontrolü sunuyor.

### B) Güçlü taraflar

- Her pipeline adımı timestamp ile loglanıyor.
- Loglar cockpit gibi UI'lara canlı aktarılabiliyor.
- Health endpoint'i merkezi durum kontrolü için uygun bir başlangıç.

### C) Kritik açıklar

```text
Sorun: Observability metrikleri standardize değil.
Neden: Structured logs, trace_id propagation, latency histogramları ve per-step error taxonomy görünmüyor.
Etki: Performans, maliyet ve hata kaynağı sistematik ölçülemez.
Çözüm: Her task için trace_id, step_duration_ms, service_name, outcome, error_code alanları zorunlu hale getirilmeli.
Doğrulama testi: Bir görev çalıştırıldığında bütün step loglarının aynı trace_id ile korele olduğu kontrol edilmeli.
```

```text
Sorun: Otonom kalite kontrol ajanları henüz pipeline'da yok.
Neden: Analyzer üretir, fakat Verifier/Critic/Refiner zinciri sistematik olarak çalışmıyor.
Etki: Hatalı veya düşük kaliteli çıktı kullanıcıya veya memory'ye ulaşabilir.
Çözüm: QualityLoop graph eklenmeli: Producer → Verifier → Critic → Refiner → Final Gate.
Doğrulama testi: Bilerek hatalı analiz ve mesaj taslaklarında critic'in hatayı yakalama oranı ölçülmeli.
```

### D) Olgunluk seviyesi

**6.5/10** — Loglama var; SLO, tracing, kalite ajanları ve hata enjeksiyonu olgun değil.

---

# BÖLÜM 2 — EVRİLME PLANI

## Faz 0 — Stabilizasyon ve kontrat kilitleme

### Amaç

Sistemin temel platform olarak değişikliklerden etkilenmeden çalışmasını sağlamak.

### Yapılacaklar

1. **TaskPolicyGate ekle**
   - Girdi: intent, target, platform, account, visual_task.
   - Çıktı: allow / needs_human_approval / deny, reason, required_scope.
   - İlk kapsam: otomatik gönderim, gizli veri toplama, platform kuralı aşma, manipülasyon ve hassas çıkarım isteklerini engelle.

2. **Health contract standardize et**
   - Boolean yerine `HealthStatus` schema.
   - Alanlar: ok, latency_ms, auth_ok, degraded, version, last_error, checked_at.

3. **TaskStore ekle**
   - İlk implementasyon: SQLite.
   - Orchestrator `_tasks` bellek içi cache olarak kalabilir; source of truth store olmalı.

4. **Structured logging getir**
   - Her step: trace_id, task_id, step, service, status, duration_ms, error_code.

5. **Contract testleri oluştur**
   - Agent-Zero, Deer-Flow, ElizaOS, SessionStore, LLMGateway için success/failure senaryoları.

### Çıktı

Sistem restart, servis arızası ve API kontrat değişimi karşısında daha güvenilir bir temel platforma dönüşür.

### Yeni kontrol

```text
Kontrol: Faz 0 Stabilizasyon Test Paketi
Başarı kriteri:
- Her servis için HealthStatus dönüyor.
- Her task restart sonrası okunabiliyor.
- Her güvenlik dışı intent policy tarafından durduruluyor.
- Contract testleri CI'da geçiyor.
```

---

## Faz 1 — Zeka katmanı ve dinamik routing

### Amaç

Ajanların daha doğru, daha ucuz ve daha açıklanabilir karar vermesini sağlamak.

### Yapılacaklar

1. **Capability Registry**
   - Servis adı değil yetenek adı kullan: `IDeepResearch`, `IPersonaMemory`, `IGuiAction`, `ICodeOrchestration`, `IProfileAnalysis`.

2. **Planner / Triage node**
   - Görevi capability ihtiyacına, risk seviyesine ve beklenen çıktı tipine ayır.

3. **ModelRouter**
   - Seçim kriterleri: task_type, risk_level, target_quality, budget, latency_slo, context_length.

4. **Confidence + Evidence Gate**
   - Analyzer, resonance ve draft çıktıları minimum confidence/evidence eşiğinden geçmeden downstream'e ilerlememeli.

5. **Decision audit schema**
   - Her karar: input_refs, evidence_refs, score_breakdown, rejected_options, final_reason.

### Çıktı

Sistem her göreve aynı pipeline'ı uygulamak yerine, ihtiyaca göre doğru organı ve doğru modeli çağıran adaptif bir Agent OS haline gelir.

### Yeni kontrol

```text
Kontrol: Routing Doğruluk Testi
Başarı kriteri:
- Basit taslak görevlerinde deep research çağrılmaz.
- Research görevlerinde UI-TARS çağrılmaz.
- Yüksek riskli görevlerde human approval zorunlu olur.
- Model maliyeti görev sınıfına göre beklenen aralıkta kalır.
```

---

## Faz 2 — Hafıza evrimi

### Amaç

Mevcut profil JSON hafızasını doğrulanmış, katmanlı ve öğrenebilir bir hafıza sistemine dönüştürmek.

### Evrim yolu

```text
Short Memory
↓
Conversation Memory
↓
Experience Memory
↓
Knowledge Memory
↓
Semantic Graph
```

### Yapılacaklar

1. **MemoryIngestionValidator**
   - Schema validity, evidence match, source quality, recency, privacy risk ve duplication kontrolü.

2. **MemoryStore abstraction**
   - SQLite ile başla; sonra vector store ve graph store bağlanabilir olsun.

3. **Memory record schema**
   - Alanlar: id, subject, platform, source_refs, evidence_refs, confidence, stability, ttl, sensitivity, created_at, supersedes.

4. **Forgetting policy**
   - Düşük confidence, eski veya çelişkili kayıtlar otomatik eskisin.

5. **Semantic graph**
   - Kişi → tema → evidence → interaction outcome ilişkileri graph olarak tutulmalı.

### Çıktı

Hafıza sadece veri yığını olmaktan çıkar; doğrulanmış deneyim, bilgi ve ilişkisel bağlam katmanına dönüşür.

### Yeni kontrol

```text
Kontrol: Memory Kalite Testi
Başarı kriteri:
- Uydurma evidence memory'ye girmez.
- Hassas veya yasaklı çıkarımlar reddedilir.
- Aynı profilin tekrar analizinde delta doğru hesaplanır.
- 100 paralel yazmada veri kaybı olmaz.
```

---

## Faz 3 — Otonom kalite kontrol

### Amaç

Her ajan çıktısının başka bir kontrol mekanizması tarafından doğrulanmasını sağlamak.

### Yapılacaklar

1. **QualityLoop graph**

```text
Producer
↓
Verifier
↓
Critic
↓
Refiner
↓
Final Gate
```

2. **Analyzer kalite zinciri**
   - Producer: profil sinyali çıkarır.
   - Verifier: evidence kaynakta var mı kontrol eder.
   - Critic: teşhis, manipülasyon, aşırı çıkarım arar.
   - Refiner: hatalı alanları düşürür veya düşük confidence'a çeker.

3. **Draft kalite zinciri**
   - Ton uygunluğu, saygı sınırı, manipülasyon riski ve human approval gereksinimi kontrol edilir.

4. **Self-evaluation skoru**
   - Her final çıktı `quality_score`, `risk_score`, `missing_evidence` alanlarıyla döner.

### Çıktı

Sistem tek model çıktısına güvenmez; kendi çıktısını denetleyen kapalı devre kalite motoruna sahip olur.

### Yeni kontrol

```text
Kontrol: Otonom Kalite Benchmark
Başarı kriteri:
- Bilerek hatalı evidence en az %95 oranında yakalanır.
- Yasaklı psikolojik çıkarımlar %100 final çıktısından temizlenir.
- Düşük kalite taslaklar final gate'ten geçmez.
```

---

## Faz 4 — Üretim seviyesi dayanıklılık

### Amaç

Sistemi servis kesintisi, yoğunluk, maliyet baskısı ve veri kaybına karşı üretim seviyesine taşımak.

### Yapılacaklar

1. **Yük testi**
   - Aynı anda 10/50/100 task senaryoları.

2. **Hata enjeksiyonu**
   - LLM timeout, Deer-Flow 500, Agent-Zero auth fail, Eliza unavailable, corrupted memory file.

3. **Servis kapanması testi**
   - Pipeline'ın degraded mode'da ne kadar iyi sonuç ürettiği ölçülmeli.

4. **Veri kaybı testi**
   - TaskStore, MemoryStore ve SessionStore için crash recovery.

5. **Maliyet optimizasyonu**
   - Token budget, per-task cost ceiling, route downgrade ve cache policy.

6. **Operasyon runbook'u**
   - Başlatma, durdurma, restart, log inceleme, secret rotation, backup/restore.

### Çıktı

Sistem sadece çalışan bir prototip değil, ölçülebilir, izlenebilir ve arızaya dayanıklı bir production-grade platform olur.

### Yeni kontrol

```text
Kontrol: Production Readiness Gate
Başarı kriteri:
- P95 task latency hedefi tanımlı ve ölçülüyor.
- Kritik servis kesintisinde sistem crash etmiyor.
- Session ve memory verisi crash sonrası bozulmuyor.
- Token maliyeti görev başına raporlanıyor.
```

---

# Öncelikli düzeltme sırası

1. **TaskPolicyGate** — insan onayı ve güvenlik sınırını runtime'a indir.
2. **HealthStatus schema** — operasyonel görünürlüğü boolean seviyesinden çıkar.
3. **TaskStore** — görev geçmişini restart dayanıklı hale getir.
4. **EvidenceVerifier** — analyzer evidence halüsinasyonunu engelle.
5. **MemoryIngestionValidator** — hafızaya sadece doğrulanmış kayıt al.
6. **Capability Registry + Planner** — statik pipeline'ı dinamik Agent OS'e dönüştür.
7. **QualityLoop graph** — Producer/Verifier/Critic/Refiner kapalı devresini kur.
8. **Production readiness tests** — yük, hata enjeksiyonu, veri kaybı ve maliyet kapılarını ekle.

---

# Nihai hedef mimari

```text
User / Cockpit
  ↓
TaskPolicyGate
  ↓
Planner + Capability Registry
  ↓
┌──────────────────────────────────────────────┐
│ Capability Layer                              │
│ - ProfileAnalysis                             │
│ - PersonaMemory                               │
│ - DeepResearch                                │
│ - GuiAction                                   │
│ - Code/Agent Orchestration                    │
└──────────────────────────────────────────────┘
  ↓
QualityLoop: Producer → Verifier → Critic → Refiner
  ↓
MemoryIngestionValidator
  ↓
Layered Memory: Short → Conversation → Experience → Knowledge → Graph
  ↓
Human Approval Boundary
  ↓
Draft / Handover / Optional UI Action
```

Bu hedefe ulaşıldığında Pineal Gland, yalnızca servisleri bağlayan bir orkestratör değil; görevleri sınıflandıran, kanıta dayalı karar veren, kendi çıktısını denetleyen ve her kontrolden sonra daha güçlü hale gelen kapalı döngü bir ajan işletim sistemi olur.
