# AGENTS.md — Mösyö'nün Otonom Sosyal Medya Ajan Sistemi

Kullanıcı, Instagram/X için **LangGraph tabanlı dinamik niyet + rezonans motoru** ve
**otonom psikolojik profil analizi** üzerine kapalı devre bir ajan sistemi kuruyor.
Docker YOK (native install). **Kritik gereksinim: yalnızca gerçek kod, sıfır mock/placeholder.**

## Mimari (5 repo = 5 servis)
- **UI-TARS** — piksel tabanlı görsel ajan (GPU/vLLM gerekli)
- **Agent-Zero** — dinamik alt-ajan orkestratörü (:5000)
- **Deer-Flow** — uzun bağlamlı derin analiz (gateway :8001)
- **Postiz** — planlama/yayın (cookie/session deposu mantığı AES-GCM ile agent_core'a gömülü)
- **ElizaOS** — persona + RAG hafıza (:3000)
- **agent_core** (Python/FastAPI :5060) — API ağ geçidi + orkestratör + şifreli session store
- **Cockpit** (:5050) — statik kontrol paneli

## Çalışan servisler (bu sandbox)
- `agent_core` :5060 — PID'ye bakma, yeniden başlat: `agent_core\.venv\Scripts\python.exe agent_core.py`
- **Agent-Zero** :5000 — `cockpit\third_party\agent-zero\.venv\Scripts\python.exe run_ui.py`
  (cwd=agent-zero kökü; config `usr\.env`: `AUTH_LOGIN/AUTH_PASSWORD`, `LLMGATEWAY_API_KEY`,
  `WEB_UI_PORT=5000`, `A0_SET_MCP_SERVER_TOKEN`; model preset `usr\plugins\_model_config\presets.yaml`)
- **LiteLLM AI Gateway** :4000 — `deploy\litellm\.venv\Scripts\litellm.exe --config config.yaml --port 4000`
  (env: `.env` dosyasından; `OPENROUTER_API_KEY` + `DEEPSEEK_API_KEY` + `LITELLM_MASTER_KEY`)
  - DeepSeek doğrudan (`deepseek-chat`, `deepseek-reasoner`) + OpenRouter (`openrouter-chat`, `gpt-4o-mini`, `llama-3.3-70b`, `qwen3-vl-8b`)
  - Fallback: `deepseek-*` düşerse → `openrouter-chat` (LiteLLM `router_settings.fallbacks`)
  - fastapi `<0.116` pin'li (1.95 ile uyum). DB'siz mod (virtual key/bütçe için Postgres şart)
- Deer-Flow gateway :8001 — `backend\.venv\Scripts\python.exe -m uvicorn app.gateway.app:app --port 8001`
  (env: `DEER_FLOW_AUTH_DISABLED=1`, `DEER_FLOW_CONFIG_PATH=<backend>\config.yaml`, `LITELLM_MASTER_KEY`)
  - `config.yaml` model: `demo` → `langchain_openai:ChatOpenAI`, `base_url: http://localhost:4000/v1`, `api_key: $LITELLM_MASTER_KEY` (deer-flow `$VAR` sözdizimi)
- Otomasyon backend :18001 (platform) — `HBK2gLdmEx1cRIGA\Scripts\python.exe -m uvicorn openhands.automation.app:app --host 127.0.0.1 --port 18001`
  env (kritik, lokal mod): `AUTOMATION_AGENT_SERVER_URL=http://localhost:18000`,
  `AUTOMATION_AGENT_SERVER_API_KEY=<agent-canvas\api-key.txt>`, `AUTOMATION_LOCAL_API_KEY=<ayni>`,
  `AUTOMATION_DB_URL=sqlite+aiosqlite:///C:\Users\Administrator\.openhands\agent-canvas\storage\automations.db`,
  `AUTOMATION_WORKSPACE_BASE=<agent-canvas>\workspaces`, `FILE_STORE=local`,
  `LOCAL_STORAGE_PATH=<agent-canvas>\storage`, `AUTOMATION_KV_SECRET=<herhangi>`, `OPENHANDS_AUTOMATION_API_KEY=<api-key.txt>`
- Cockpit :5050 — `cockpit\.venv\Scripts\python.exe main.py` (cwd=cockpit)

## Kritik öğrenimler
1. **Süreç bulma:** `--port` argümanı eşleştirmesi tehlikelidir — `18001` içindeki `8001` de eşleşir.
   Servisleri durdururken daima tam port veya PID ile hedefle. Otomasyon backend'i
   kazara öldürülürse yukarıdaki env'lerle yeniden başlat (auth anahtarı `api-key.txt` == `OPENHANDS_AUTOMATION_API_KEY`).
2. **Deer-Flow `config.yaml`:**
   - `use` alanı **`langchain_openai:ChatOpenAI`** formatında (modül:Sınıf). Nokta formatı `ImportError` verir.
   - `sandbox.use` zorunlu → `deerflow.sandbox.LocalSandboxProvider`.
   - Config mtime hot-reload'ludur.
   - Auth kapalı mod şart (CSRF 403 verir): `DEER_FLOW_AUTH_DISABLED=1`.
   - Doğrulama: `POST /api/threads` → `{thread_id}`; `POST /api/threads/{id}/runs/wait` → final state.
3. **agent_core başlatma:** Eski süreç `python.exe agent_core.py` (port argümansız) ile çalışır;
   `.env` değişince yeniden başlatmak için PID'e göre kill et. Venv python'u Windows'ta
   base Python görünümünde çıkar (Win32_Process path farklı olabilir).
4. **Agent-Zero (:5000)** — kuruldu, çalışıyor, E2E doğrulandı (`agent_zero: true`).
   - Kurulum: `uv` ile (torch/whisper dahil ~2.5GB); venv `.venv`.
   - **Model** → LiteLLM gateway: `conf/model_providers.yaml`'a `llmgateway` (openai-uyumlu,
     `api_base: http://localhost:4000/v1`, API key `LLMGATEWAY_API_KEY`); `usr\plugins\_model_config\presets.yaml`
     "Default" preset: chat/utility=`llmgateway/deepseek-chat`, embedding=`huggingface/sentence-transformers/all-MiniLM-L6-v2`.
   - `usr\.env`: `A0_SET_MCP_SERVER_TOKEN` (X-API-KEY), `AUTH_LOGIN/AUTH_PASSWORD`, `WEB_UI_PORT=5000`.
   - **Windows yamaları:** (a) `helpers/persist_chat.py` `_write_atomic` — dizin fsync'i `os.name != "nt"` guard'ına
     alındı (`os.open(dizin)` Windows'ta PermissionError); (b) `helpers/runtime.py` `call_development_function` —
     RFC URL/password yapılandırılmamışsa fonksiyonu doğrudan çağırır (yerel mod). (c) `helpers/settings.py`
     `normalize_settings` — `A0_SET_MCP_SERVER_TOKEN` env'de varsa onu kullanır (yoksa rastgele üretir).
   - **Kontrat dikkat:** `/api/message` web-oturum doğrulamalı (api/message.py); API-anahtarı ucu
     `/api/api_message`'dır (dosya adından türetilir). `agent_core/services/agent_zero.py` buna göre güncellendi.
5. E2E akış: `/task` → intent → eliza → deerflow → agent_zero → finish. Çalışmayan
   servisler `unavailable` olarak işaretlenir (crash olmaz). Deer-Flow + Agent-Zero bağlıyken
   `/health` `deerflow: true, agent_zero: true` döner.

## Doğrulanmış API kontratları
| Servis | Kontrat |
|---|---|
| Agent-Zero | `POST /api/api_message` header `X-API-KEY: <MCP_SERVER_TOKEN>` body `{context_id?, message, attachments?, lifetime_hours?, project_name?, agent_profile?}` → `{context_id, response}`; health `GET /api/health` |
| Deer-Flow | `POST /api/threads` → `{thread_id}`; `/runs/wait` → final state; `GET /api/threads/{id}/messages` |
| UI-TARS | `screenshot(base64) → VLM predict → click(start_box='(x,y)') → execute`; regex parser iç içe parantez güvenli |
| ElizaOS | `GET /agents`; `POST /:agentId/message` body `{text, roomId, userId}` → `[{text, user,...}]`; RAG roomId kapsamında |
| Session store | AES-GCM; `save/load/list/delete` doğrulandı |

## Deployment runbook
`agent_core/DEPLOYMENT.md` — tüm servisler için doğrulanmış native adımlar + env şablonları.
