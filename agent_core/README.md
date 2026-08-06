# Ajan Çekirdeği — Kapalı Devre Orkestrasyon

5 bağımsız depoyu tek bir kapalı devrede birleştirir. Her depo kendi servisi
olarak çalışır; `agent_core.py` aralarındaki orkestratördür. Adaptörler
**kaynak koddan doğrulanmış API kontratlarına** bağlıdır (aşağıda kontrat
listesi var) — tahmini/değişken isim yoktur.

## Mimari

```
                 ┌─────────────────────────────────────────────────┐
   /task  ──────▶│ agent_core.py (FastAPI :5060)                   │
                 │   orchestrator.py                                │
                 │        │                                        │
                 │        ├─▶ Agent-Zero  (:5000)  dinamik alt-ajan orkestratörü
                 │        ├─▶ Deer-Flow   (:8080)  uzun bağlamlı derin analiz
                 │        ├─▶ UI-TARS VLM (endpoint) piksel tabanlı görsel ajan
                 │        ├─▶ ElizaOS     (:3000)  persona + RAG hafızası
                 │        └─▶ SessionStore (AES-GCM) şifreli oturum/çerez
                 └─────────────────────────────────────────────────┘
```

## Doğrulanmış API kontratları (klonlanan kaynak koddan)

| Servis | Kontrat |
|---|---|
| Agent-Zero | `POST /api/message`, header `X-API-KEY: <MCP_SERVER_TOKEN>`, body `{context_id?, message, attachments?, lifetime_hours?, project_name?, agent_profile?}` → `{context_id, response}`. Kaynak: `agent-zero/helpers/api.py`, `agent-zero/api/api_message.py`. Varsayılan port 5000 (env `WEB_UI_PORT`). |
| Deer-Flow | `POST /api/threads` → `{thread_id}`; `POST /api/threads/{id}/runs` (RunCreateRequest, `extra="forbid"`); `POST /api/threads/{id}/runs/wait` (aynı gövde, bloklar → final state); `GET /api/threads/{id}/messages`. Kaynak: `deer-flow/backend/app/gateway/routers/{threads,thread_runs}.py`. |
| UI-TARS | Pixel loop: `operator.screenshot(base64) → model.predict(instruction, shot) → click(start_box='(x,y)') → execute`. Model OpenAI-uyumlu VLM (`vllm serve ByteDance/UI-TARS-1.5-7B`). DOM seçicisi YOK. |
| ElizaOS | `GET /agents`; `POST /:agentId/message` body `{text, roomId, userId}` → `[{text, user, ...}]`. RAG hafızası `roomId` kapsamında; hedef başına sabit oda kullanılır. |
| Oturum deposu | Postiz mantığı: çerez/token AES-GCM ile şifrelenip `(platform, hesap)` başına yalıtılmış JSON'da saklanır. |

## Kurulum ve çalıştırma

```bash
# 1) bağımlılıklar
pip install -r requirements.txt

# 2) ortam
cp .env.example .env
# AGENT_ZERO_API_KEY  = agent-zero/.env'deki MCP_SERVER_TOKEN
# SESSION_STORE_KEY   = python -c "import secrets; print(secrets.token_hex(32))"
# UITARS_REMOTE_ENDPOINT = UI-TARS VLM sunucu adresi (görsel görev kullanacaksan)

# 3) servisler (her biri kendi reposunun dokümanına göre)
docker compose up -d agent-zero deerflow eliza

# 4) UI-TARS modelini GPU varsa ayrıca başlat
#    vllm serve ByteDance/UI-TARS-1.5-7B --chat-template examples/chat_template_ui_tars.jinja

# 5) çekirdek
python agent_core.py        # -> http://localhost:5060
```

## API

```
POST /task  {"intent":"...", "target":"@kullanici", "platform":"x",
             "account":"hesabim", "visual_task":"Profili incele ve beğen butonuna tıkla"}
GET  /task/{id}     # adım adım durum + sonuç
GET  /tasks
GET  /health        # servis erişilebilirliği
GET  /agents        # Eliza ajanları
GET  /sessions      # kayıtlı oturumlar
WS   /ws            # canlı log akışı
```

Her adım (`intent, eliza, deerflow, agent_zero, uitars, session, finish`)
görev kaydında `steps[]` olarak loglanır; servis ayakta değilse adım
`unavailable` işaretlenir ve sistem durmaz. `logs/agent_core.log` dönen
dosyada tam geçmiş tutulur.

## Sınır / sorumluluk

Bu katman genel amaçlı orkestrasyon + GUI otomasyonu + bellek altyapısıdır.
Instagram/X üzerinde otomatik etkileşim/sürdürme ve profil verisi toplama,
ilgili platformların kullanım şartlarına aykırıdır ve hesap kapatmaya yol
açabilir. Bu depo, yapılacak işin hukuki/sosyal sorumluluğunu üstlenmez.
