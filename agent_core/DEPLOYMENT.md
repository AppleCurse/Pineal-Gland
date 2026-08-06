# Kapalı Devre Dağıtım Runbook'u (Native / Container'sız)

Bu belge, 5 deposu `agent_core` kapalı devresine bağlamak için **sahada doğrulanmış**
adımları içerir. Bu makinede Docker yok; her servis kendi süreci olarak native çalıştırılır.

> Durum: **LiteLLM AI Gateway + Deer-Flow + Agent-Zero bağlı ve GERÇEK LLM ile E2E doğrulandı**
> (DeepSeek doğrudan + OpenRouter yedek). Kalan: ElizaOS / Postiz / UI-TARS.

---

## 0. LLM AI Gateway (LiteLLM) — ✅ DOĞRULANDI

Tüm LLM tüketen servisler **tek uç** olarak `http://localhost:4000`'e bağlanır; sağlayıcı
anahtarları yalnızca gateway'de durur.

### Kurulum
```powershell
cd deploy/litellm
uv venv .venv
uv pip install --python .venv\Scripts\python.exe "litellm[proxy]"
uv pip install --python .venv\Scripts\python.exe "fastapi<0.116"   # 1.95 ile uyum (get_flat_dependant)
```

### `deploy/litellm/.env`
```env
OPENROUTER_API_KEY=<openrouter>
DEEPSEEK_API_KEY=<deepseek>          # dogrudan deepseek-chat/reasoner (daha ucuz)
LITELLM_MASTER_KEY=<uretilmis-64-hex>  # gateway auth anahtari (tum servisler bunu kullanir)
```

### Başlatma
```powershell
cd deploy/litellm
$env:OPENROUTER_API_KEY=...; $env:DEEPSEEK_API_KEY=...; $env:LITELLM_MASTER_KEY=...
.venv\Scripts\litellm.exe --config config.yaml --port 4000
```

### Doğrulama
```bash
curl localhost:4000/health/liveliness            # "I'm alive!"
curl localhost:4000/v1/chat/completions -H "Authorization: Bearer <MASTER>" \
  -d '{"model":"deepseek-chat","messages":[{"role":"user","content":"merhaba"}]}'
```

Notlar:
- `model_list` → DeepSeek doğrudan (PRIMARY) + OpenRouter (fallback & vision/embedding dışı modeller).
- `router_settings.fallbacks` → DeepSeek hata verirse OpenRouter'a düşer.
- **DB'siz mod** çalışır; sanal anahtar/bütçe istiyorsanız Postgres `database_url` şart.
- Model fiyatları `register_model` uyarısı verir (OpenRouter üzerinden geçtiği için cache cost 0) — zararsız.

---

## 1. Servis Matrisi

| Servis | Port | Başlatma | Durum |
|---|---|---|---|
| LiteLLM AI Gateway | 4000 | `deploy\litellm\.venv\Scripts\litellm.exe` | ✅ çalışıyor |
| `agent_core` (API ağ geçidi) | 5060 | `python agent_core.py` | ✅ çalışıyor |
| Deer-Flow gateway | 8001 | `uvicorn app.gateway.app:app` | ✅ çalışıyor + GERÇEK LLM E2E |
| Agent-Zero | 5000 | `cockpit\third_party\agent-zero\.venv\Scripts\python.exe run_ui.py` | ✅ kuruldu + E2E doğrulandı |
| ElizaOS | 3000 | `pnpm start` (agent) | ⏳ kurulum gerekli |
| Postiz | 5000 | `docker compose up` veya native | ⏳ Postgres+Redis gerekli |
| UI-TARS VLM | — | `vllm serve ByteDance/UI-TARS-1.5-7B` | ⏳ GPU gerekli |
| Cockpit | 5050 | static server | ✅ çalışıyor |

---

## 1. Deer-Flow — ✅ DOĞRULANDI

### Kurulum
```powershell
cd cockpit/third_party/deer-flow/backend
uv sync --extra browser        # deerflow-harness + langgraph + fastapi
```

### `backend/config.yaml` (minimal — DOĞRULANMIŞ şema)
```yaml
config_version: 1
log_level: info
sandbox:
  use: deerflow.sandbox.LocalSandboxProvider
  allow_host_bash: false
database:
  backend: sqlite
  path: ./data/deerflow.db
models:
  - name: demo
    use: langchain_openai:ChatOpenAI      # <-- modül:Sınıf formatı ŞART
    model: deepseek-chat                  # LiteLLM gateway model adı
    api_key: $LITELLM_MASTER_KEY          # deer-flow $VAR sözdizimi
    base_url: http://localhost:4000/v1    # LiteLLM gateway (tek uç)
```
Kritik noktalar:
- `use` alanı `langchain_openai.ChatOpenAI` DEĞİL, **`langchain_openai:ChatOpenAI`** olmalı (yoksa `ImportError: doesn't look like a variable path`).
- `sandbox.use` zorunlu alandır (`deerflow.sandbox.LocalSandboxProvider` = host bash).
- Config hot-reload'ludur: dosya değişince yeniden başlatmaya gerek yok.
- Sağlayıcı anahtarı deer-flow'da DURMAZ; yalnızca gateway'de. deer-flow `$LITELLM_MASTER_KEY` ile gateway'e bağlanır.

### Başlatma (auth kapalı — programatik erişim için)
```powershell
$env:DEER_FLOW_AUTH_DISABLED = "1"
$env:DEER_FLOW_CONFIG_PATH   = "C:\...\deer-flow\backend\config.yaml"
$env:LITELLM_MASTER_KEY      = "<gateway master key>"
& "C:\...\deer-flow\backend\.venv\Scripts\python.exe" -m uvicorn app.gateway.app:app `
  --host 127.0.0.1 --port 8001
```
Auth kapalı mod olmadan tüm POST istekleri `403 CSRF token missing` döner.

### Doğrulama
```bash
curl -X POST localhost:8001/api/threads -H "Content-Type: application/json" -d '{"assistant_id":"default"}'
# => {"thread_id":"...","status":"idle",...}

curl -X POST localhost:8001/api/threads/<id>/runs/wait -H "Content-Type: application/json" \
  -d '{"input":{"messages":[{"role":"user","content":"merhaba"}]}}'
# => final state (LLM hatasında dahi gerçek fallback mesajıyla döner)
```

---

## 2. Agent-Zero (ana orkestratör) — ✅ DOĞRULANDI

Agent-Zero `torch + openai-whisper + sentence-transformers` içerir (~2.5GB); native Windows
kurulumu `uv` ile doğrulandı. Tüm LLM trafiği LiteLLM gateway'ine (:4000) bağlanır.

### Kurulum
```powershell
cd cockpit\third_party\agent-zero
uv venv .venv
uv pip install --python .venv\Scripts\python.exe -r requirements.txt   # ~311 paket (torch 2.13, whisper)
```

### Model → LiteLLM gateway
- `conf/model_providers.yaml` → `chat:` altına `llmgateway` eklendi:
  ```yaml
  llmgateway:
    name: LLM Gateway (LiteLLM :4000)
    litellm_provider: openai
    kwargs:
      a0_api_mode: chat
      api_base: http://localhost:4000/v1
  ```
- `usr/plugins/_model_config/presets.yaml` → "Default" preset: chat/utility=`llmgateway/deepseek-chat`,
  embedding=`huggingface/sentence-transformers/all-MiniLM-L6-v2` (yerel, ilk kullanımda iner).

### `usr/.env`
```env
AUTH_LOGIN=admin
AUTH_PASSWORD=<üretilmiş>
LLMGATEWAY_API_KEY=<LITELLM_MASTER_KEY>     # provider adından türetilir (üstü büyük + _API_KEY)
WEB_UI_PORT=5000
A0_SET_MCP_SERVER_TOKEN=<agent_core AGENT_ZERO_API_KEY ile aynı>  # X-API-KEY doğrulaması
```

### Başlatma
```powershell
cd cockpit\third_party\agent-zero
.venv\Scripts\python.exe run_ui.py          # :5000
```

### Windows yamaları (repo içinde, kalıcı)
1. `helpers/persist_chat.py::_write_atomic` — dizin fsync'i `os.open(dizin)` Windows'ta
   PermissionError verir; `os.name != "nt"` guard'ına alındı.
2. `helpers/runtime.py::call_development_function` — RFC URL/password yapılandırılmamışsa
   fonksiyonu doğrudan çağırır (Docker'daki RFC çağrısına yerel fallback).
3. `helpers/settings.py::normalize_settings` — `mcp_server_token` önce `A0_SET_MCP_SERVER_TOKEN`
   env'inden okunur; yoksa rastgele üretilir (böylece istemci anahtarı önceden bilebilir).

### Doğrulama (E2E)
```bash
curl -X POST localhost:5000/api/api_message \
  -H "X-API-KEY: <MCP_SERVER_TOKEN>" -H "Content-Type: application/json" \
  -d '{"message":"merhaba","lifetime_hours":24}'
# → {"context_id": "...", "response": "<gerçek DeepSeek yanıtı>"}
```
`agent_core/.env`: `AGENT_ZERO_API_KEY` = yukarıdaki `MCP_SERVER_TOKEN`; `/health` → `agent_zero: true`.
**Not:** `/api/message` web-oturum doğrulamalıdır; API-anahtarı ucu `/api/api_message`'dır
(dosya adından türetilir). `agent_core/services/agent_zero.py` buna göre güncellendi.

---

## 3. ElizaOS (persona + RAG hafıza) — native

```bash
cd eliza
cp .env.example .env       # OPENAI_API_KEY vb. gir
pnpm install && pnpm build
pnpm start --characters=characters/<persona>.character.json
```
`agent_core` adaptörü `GET /agents` + `POST /:agentId/message {text, roomId, userId}` kullanır;
hedef başına sabit `roomId` → RAG hafızası oda kapsamında tutulur.

---

## 4. Postiz (planlama / yayınlama) — Postgres + Redis gerekli

```bash
# A: Docker (önerilen)
cd postiz
docker compose up -d

# B: Native (Node 18+)
#   .env: POSTGRESQL_URL, REDIS_URL, JWT_SECRET, ACCESS_TOKEN doldur
#   pnpm install && pnpm build && pnpm start
```
`agent_core` yalnızca oturum/cookie deposu mantığını Postiz'den alır (AES-GCM ile
uygulanır, harici Postiz süreci opsiyoneldir).

---

## 5. UI-TARS (piksel tabanlı görsel ajan) — GPU gerekli

```bash
vllm serve ByteDance/UI-TARS-1.5-7B \
  --chat-template examples/chat_template_ui_tars.jinja
```
`agent_core/.env` → `UITARS_REMOTE_ENDPOINT=<vllm URL>/v1`, `UITARS_MODEL=ui-tars-1.5`.
Adaptör döngüsü: `screenshot(base64) → VLM → click(start_box='(x,y)') → execute`.

---

## 6. agent_core bağlantı ayarları (`agent_core/.env`)

```env
AGENT_ZERO_URL=http://localhost:5000
AGENT_ZERO_API_KEY=<MCP_SERVER_TOKEN>
DEERFLOW_URL=http://localhost:8001
ELIZA_URL=http://localhost:3000
UITARS_REMOTE_ENDPOINT=<varsa>
SESSION_STORE_KEY=<python -c "import secrets; print(secrets.token_hex(32))">
```

### E2E doğrulama
```bash
curl localhost:5060/health
# => {"status":"alive","services":{"agent_zero":false,"deerflow":true,"eliza":false}}

curl -X POST localhost:5060/task -H "Content-Type: application/json" \
  -d '{"intent":"research","prompt":"viral icerik oner","handle":"test"}'
curl localhost:5060/task/<task_id>
# => steps: intent->ok, eliza->unavailable, deerflow->ok (gerçek thread+run), finish->ok
```

---

## 7. Bu makinede eksik olan (kapalı devrenin kalanı için)

1. **LLM API anahtarı** (OpenAI/Anthropic/local) — agent-zero, eliza ve deer-flow'un
   gerçek akıl yürütmesi için. Anahtar girilirse deer-flow `config.yaml`'deki `base_url`
   gerçek endpoint'e çevrilir ve ajan gerçek araştırma üretir.
2. **GPU** — UI-TARS görsel ajanı için (vLLM).
3. **Postgres/Redis** (opsiyonel) — Postiz için.

Bu üçü sağlandığında `agent_core` kapalı devresi 5 servisin tamamıyla canlı çalışır;
cockpit (5050) hepsini `green` gösterir.
