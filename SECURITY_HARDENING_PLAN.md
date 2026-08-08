# Security Hardening Plan — CRITICAL BULGULAR

## Mevcut Durum Analizi

### 1. API Authentication Eksikliği (CRITICAL)

**Bulgu:** Cockpit endpoint'lerinin tamamında authentication yok.

**Riskli Endpoint'ler:**
- `GET/POST /api/platform/config` — Platform yapılandırmasını okur/değiştirir
- `GET /api/memory` — Tüm profilleri döndürür
- `GET /api/personality` — Persona ayarlarını döndürür
- `POST /api/handover` — İnsan onayına görev devreder
- `GET /api/skills` — Yetenek listesini döndürür

**Kod:** `cockpit/main.py` satır 789-875

**Kanıt:**
```python
@app.get("/api/memory")
async def get_memory():
    # ❌ Hiçbir auth kontrolü yok
    return memory_data
```

**Etki:**
- Ağdaki herhangi biri memory'yi okuyabilir
- Platform config değiştirilebilir
- Handover manipüle edilebilir

---

### 2. Secret Management (HIGH)

**Bulgu:** API key'ler environment variable'dan geliyor ama validation yok.

**Kod:** `cockpit/main.py` satır 51
```python
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "")
# ❌ Boş olabilir, validation yok
```

**Risk:**
- API key boşsa sistem çalışmaz ama hata mesajı belirsiz
- Hard-coded fallback yok (bu iyi), ama startup validation eksik

---

### 3. Host Binding (MEDIUM - DÜZELTİLDİ)

**Önceki Durum:** `host="0.0.0.0"` (tüm arayüzlere açık)

**Şu Anki Durum:** ✅ DÜZELTİLDİ
```python
host = os.getenv("COCKPIT_HOST", "127.0.0.1")  # ✅ Sadece localhost
```

**Kod:** `cockpit/main.py` satır 903

---

### 4. CORS Policy (MEDIUM)

**Bulgu:** CORS ayarı belirsiz/gözden kaçmış.

**Kontrol Edilmesi Gereken:**
- FastAPI CORS middleware kullanılıyor mu?
- Hangi origin'lere izin veriliyor?
- Credentials flag var mı?

---

### 5. Rate Limiting (HIGH)

**Bulgu:** Hiçbir endpoint'te rate limiting yok.

**Risk:**
- DoS saldırılarına açık
- LLM token budget hızlıca tüketilebilir
- Browser automation abuse edilebilir

---

### 6. Input Validation (MEDIUM)

**Bulgu:** Bazı endpoint'lerde input validation yetersiz.

**Örnek:**
```python
@app.post("/api/radar")
async def radar(req: RadarRequest):
    # req doğrulanıyor mu?
```

---

## ÖNERİLEN DÜZELTMELER

### 1. API Token Authentication (CRITICAL)

**Çözüm:** Basit API token sistemi

```python
# cockpit/auth.py
from fastapi import Depends, HTTPException, status
from fastapi.security import APIKeyHeader

API_KEY_HEADER = APIKeyHeader(name="X-API-Key", auto_error=False)

async def get_api_key(api_key_header: str = Depends(API_KEY_HEADER)) -> str:
    if not api_key_header:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="API key required"
        )
    
    # Environment'dan beklenen key'i al
    expected_key = os.getenv("COCKPIT_API_KEY")
    if not expected_key:
        # Development mode: key yoksa auth skip et
        logger.warning("COCKPIT_API_KEY set değil — auth bypass ediliyor")
        return api_key_header
    
    if api_key_header != expected_key:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid API key"
        )
    
    return api_key_key

# Kullanım
@app.get("/api/memory")
async def get_memory(api_key: str = Depends(get_api_key)):
    # Auth geçtiyse çalışır
    return memory_data
```

**Environment:**
```bash
# .env
COCKPIT_API_KEY=your-secret-key-here
```

---

### 2. Startup Validation (HIGH)

**Çözüm:** Startup'ta kritik ayarları doğrula

```python
@app.on_event("startup")
async def startup_validation():
    required_vars = ["OPENROUTER_API_KEY"]
    missing = [var for var in required_vars if not os.getenv(var)]
    
    if missing:
        logger.error(f"Kritik environment değişkenleri eksik: {missing}")
        raise RuntimeError(f"Startup failed: {missing}")
    
    logger.info("Startup validation OK")
```

---

### 3. Rate Limiting (HIGH)

**Çözüm:** slowapi veya basit decorator

```python
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address

limiter = Limiter(key_func=get_remote_address)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

@app.post("/api/radar")
@limiter.limit("10/minute")  # Dakikada 10 istek
async def radar(request: Request, req: RadarRequest):
    ...
```

---

### 4. CORS Policy (MEDIUM)

**Çözüm:** Explicit CORS ayarı

```python
from fastapi.middleware.cors import CORSMiddleware

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],  # Sadece belirli origin
    allow_credentials=True,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)
```

---

### 5. Input Validation Strengthening (MEDIUM)

**Çözüm:** Pydantic validator'ları kullan

```python
from pydantic import BaseModel, Field, validator

class RadarRequest(BaseModel):
    platform: str = Field(..., min_length=1, max_length=50)
    username: str = Field(..., min_length=1, max_length=100)
    
    @validator('platform')
    def validate_platform(cls, v):
        allowed = ["instagram", "x", "linkedin"]
        if v.lower() not in allowed:
            raise ValueError(f"Platform must be one of: {allowed}")
        return v.lower()
```

---

## UYGULAMA SIRASI

1. **API Token Authentication** (CRITICAL) — Hemen
2. **Startup Validation** (HIGH) — Hemen
3. **Rate Limiting** (HIGH) — Bugün
4. **CORS Policy** (MEDIUM) — Bugün
5. **Input Validation** (MEDIUM) — Bu hafta

---

## DOĞRULAMA TESTLERİ

### Test 1: Auth olmadan erişim
```bash
curl http://localhost:5050/api/memory
# Beklenen: 401 Unauthorized
```

### Test 2: Yanlış key ile erişim
```bash
curl -H "X-API-Key: wrong" http://localhost:5050/api/memory
# Beklenen: 403 Forbidden
```

### Test 3: Doğru key ile erişim
```bash
curl -H "X-API-Key: correct-key" http://localhost:5050/api/memory
# Beklenen: 200 OK + data
```

### Test 4: Rate limit aşımı
```bash
for i in {1..15}; do
  curl -H "X-API-Key: correct-key" http://localhost:5050/api/radar -X POST
done
# Beklenen: 11. istekten itibaren 429 Too Many Requests
```

---

## SONRAKİ ADIM

Security hardening kodlarını uygulamaya başlıyorum:

1. `cockpit/auth.py` — Authentication modülü
2. `cockpit/main.py` — Auth dependency injection
3. Rate limiting entegrasyonu
4. Startup validation

